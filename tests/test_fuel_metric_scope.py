"""Жёсткие маркеры типа в топливной аналитике (kb-15, вводные директора 02.07):
моточасная техника никогда не в л/100, дорожная — никогда в л/мч,
электрическая — вне топливной аналитики вообще."""

import json
import sqlite3

from omnicomm_report import vehicle_types as vt


def test_new_power_types_classified():
    assert vt.classify_from_name("ДЭС(AKSA-200) №3") == "des"
    assert vt.classify_from_name("Компрессор (эл. Atlas XAXS600E)№23") == "compressor_electric"
    assert vt.classify_from_name("Atlas Copco V900 №8") == "compressor"
    assert vt.classify_from_name("Грейдер ГС-14.02") == "loader"
    # электрический — вне топливной аналитики; дизельный — только моточасы
    assert vt.profile("compressor_electric").primary_metric == "none"
    assert vt.profile("compressor").primary_metric == "l_per_mh"
    assert vt.profile("des").primary_metric == "l_per_mh"


def _seed(path, tid, name, *, days=10, km_per_day=0.0, worked_h_per_day=0.0, fuel_l_per_day=0.0):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE IF NOT EXISTS fact_daily (terminal_id TEXT, date INTEGER, "
                 "payload TEXT, PRIMARY KEY(terminal_id,date))")
    for i in range(days):
        payload = json.dumps({"consolidatedReport": {
            "vehicleId": tid, "date": i * 86400, "vehicleName": name,
            "mv": {"mileage": km_per_day, "worked": worked_h_per_day * 3600},
            "fuel": {"fuelConsumption": fuel_l_per_day},
        }})
        conn.execute("INSERT OR REPLACE INTO fact_daily VALUES (?,?,?)", (str(tid), i * 86400, payload))
    conn.commit(); conn.close()


def test_metric_scope_hard_filter(tmp_path):
    from api import fuel_norms as fnm
    raw = str(tmp_path / "raw.db")
    # дизельный компрессор: много моточасов И (аномально) пробег — л/100 всё равно нельзя
    _seed(raw, 1, "Atlas Copco V900 №8", days=10, km_per_day=50, worked_h_per_day=10, fuel_l_per_day=80)
    # электрический компрессор: моточасов полно — но топливной аналитики быть не должно
    _seed(raw, 2, "Компрессор (эл. Atlas XAXS600E)№23", days=10, worked_h_per_day=10, fuel_l_per_day=5)
    # легковой: пробег есть, моточасов много — л/мч нельзя (дорожный маркер)
    _seed(raw, 3, "TOYOTA Hilux 240BC13", days=10, km_per_day=200, worked_h_per_day=8, fuel_l_per_day=20)
    out = fnm.build_fuel_norms(from_iso="1970-01-01", to_iso="1970-01-11", raw_path=raw)
    rows = {r["vehicleId"]: r for r in out["rows"]}

    diesel = rows["1"]
    assert diesel["metric_scope"] == "l_per_mh"
    assert diesel["fact_l100"] is None          # моточасный — НИКОГДА л/100
    assert diesel["fact_lmh"] is not None       # л/мч считается

    electric = rows["2"]
    assert electric["metric_scope"] == "none"
    assert electric["fact_l100"] is None and electric["fact_lmh"] is None
    assert electric["mode"] is None             # вне топливной аналитики

    car = rows["3"]
    assert car["metric_scope"] == "l_per_100km"
    assert car["fact_lmh"] is None              # дорожный — НИКОГДА л/мч
    assert car["fact_l100"] is not None
