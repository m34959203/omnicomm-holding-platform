"""Тесты норм расхода и перерасхода (api/fuel_norms.py).

Проверяют: дорожный/моточасный режим, перерасход(+)/экономия(−), вентиль доверия
(АТЗ/не-ТС/малый пробег → перерасход «—»). Инвариант: перерасход только там, где
факт достоверен.
"""

import datetime as dt

import pytest

from api import fuel_norms


def _daily(vid, name, *, mileage=0.0, fuel=0.0, worked_h=0.0,
           norm100=0.0, norm_mh=0.0, refuel=0.0):
    return {"consolidatedReport": {
        "vehicleId": vid, "vehicleName": name,
        "mv": {"mileage": mileage, "worked": worked_h * 3600},
        "fuel": {"fuelConsumption": fuel, "normCons100": norm100,
                 "normConsumptionMH": norm_mh, "refuelling": refuel,
                 "draining": 0, "delivery": 0},
    }}


@pytest.fixture
def rows(monkeypatch):
    data = [
        _daily("over", "ГАЗель", mileage=1000, fuel=600, norm100=40),     # факт 60 > норма 40 → перерасход
        _daily("econ", "ГАЗель-2", mileage=1000, fuel=300, norm100=50),   # факт 30 < норма 50 → экономия
        _daily("atz", "АТЗ-9", mileage=1000, fuel=5000, norm100=40),      # факт 500 → вентиль → «—»
        _daily("tank", "Ёмкость №1", mileage=1000, fuel=600, norm100=40), # не-ТС → «—»
        _daily("moto", "Экскаватор", worked_h=100, fuel=2500),           # 25 л/мч > кат.18 → перерасход(мч)
        _daily("idle", "Кран", mileage=50, worked_h=5, fuel=100),         # малый пробег+мч → «—»
    ]
    monkeypatch.setattr(fuel_norms, "NORMS_FILE", "/nonexistent.json")     # код-дефолты
    monkeypatch.setattr(fuel_norms.raw_store, "coverage",
                        lambda path=None: {"date_max": int(dt.datetime(2026, 6, 30, tzinfo=dt.timezone.utc).timestamp())})
    monkeypatch.setattr(fuel_norms.raw_store, "load_daily",
                        lambda a, b, path=None: data)
    res = fuel_norms.build_fuel_norms(from_iso="2026-06-01", to_iso="2026-06-30")
    return {r["vehicleId"]: r for r in res["rows"]}, res


def test_road_overrun(rows):
    by_id, _ = rows
    r = by_id["over"]
    assert r["mode"] == "km"
    assert r["fact_l100"] == 60.0 and r["norm_l100"] == 40.0
    assert r["over_l"] == pytest.approx(200.0)   # (60-40)*1000/100


def test_road_economy(rows):
    r = rows[0]["econ"]
    assert r["mode"] == "km"
    assert r["over_l"] == pytest.approx(-200.0)   # экономия


def test_atz_filtered(rows):
    r = rows[0]["atz"]
    assert r["fact_l100"] is None     # факт >130 л/100 → вентиль
    assert r["over_l"] is None        # перерасход не выводим


def test_non_transport_filtered(rows):
    r = rows[0]["tank"]
    assert r["fact_l100"] is None and r["over_l"] is None


def test_motohour_overrun(rows):
    r = rows[0]["moto"]
    assert r["mode"] == "mh"
    assert r["fact_lmh"] == 25.0 and r["norm_lmh"] == 18.0
    assert r["over_l"] == pytest.approx(700.0)    # (25-18)*100 мч


def test_low_usage_filtered(rows):
    r = rows[0]["idle"]
    assert r["over_l"] is None


def test_totals_exclude_untrusted(rows):
    _, res = rows
    # в суммарный перерасход попадают только over+ (over 200 + moto 700 = 900); экономия 200
    assert res["over_l_total"] == pytest.approx(900.0)
    assert res["economy_l_total"] == pytest.approx(200.0)
