"""Тесты учёта автошин по пробегу: движок, стор, сборка секции."""

import json
import sqlite3

from omnicomm_report import tyres


# --- Движок ------------------------------------------------------------------

def test_evaluate_statuses_and_wear():
    plan = tyres.TyrePlan("7", resource_km=60000, cost_kzt=400000, remind_before_km=3000)
    assert tyres.evaluate(plan, 10000).status == "ok"
    assert tyres.evaluate(plan, 50000).status == "приближается"     # 83% ресурса
    assert tyres.evaluate(plan, 58000).status == "пора менять"      # осталось 2000 ≤ 3000
    over = tyres.evaluate(plan, 66000)
    assert over.status == "просрочено" and over.km_left == -6000


def test_wear_kzt_proportional_and_capped():
    plan = tyres.TyrePlan("7", resource_km=100000, cost_kzt=500000)
    assert tyres.evaluate(plan, 50000).wear_kzt == 250000            # 50% × стоимость
    assert tyres.evaluate(plan, 200000).wear_kzt == 500000          # кап по стоимости


def test_confirm_change_resets_cycle():
    st = tyres.TyreState("7", installed_ts=100)
    st2 = tyres.confirm_change(st, at_ts=9000)
    assert st2.installed_ts == 9000 and st2.last_change_at == 9000


def test_fleet_status_sorted_by_urgency():
    plans = {"a": tyres.TyrePlan("a", resource_km=60000, cost_kzt=1),
             "b": tyres.TyrePlan("b", resource_km=60000, cost_kzt=1)}
    km = {"a": 1000, "b": 70000}      # b просрочено
    out = tyres.fleet_status(plans, {}, km)
    assert out[0].terminal_id == "b" and out[0].status == "просрочено"


# --- Стор --------------------------------------------------------------------

def test_store_set_plan_and_replace(tmp_path):
    from api import tyre_store
    p = str(tmp_path / "tyres.db")
    tyre_store.set_plan("7", resource_km=50000, cost_kzt=900000, brand="Nokian",
                        updated_at=1, path=p)
    row = tyre_store.get_all(p)["7"]
    assert row["resource_km"] == 50000 and row["brand"] == "Nokian"

    # частичный upsert не затирает бренд
    tyre_store.set_plan("7", cost_kzt=1000000, updated_at=2, path=p)
    row = tyre_store.get_all(p)["7"]
    assert row["brand"] == "Nokian" and row["cost_kzt"] == 1000000

    # замена → новый installed_ts + журнал
    tyre_store.replace("7", changed_ts=5000, km_at_change=48000, note="сезон", path=p)
    assert tyre_store.get_all(p)["7"]["installed_ts"] == 5000
    hist = tyre_store.history("7", path=p)
    assert hist[0]["changed_ts"] == 5000 and hist[0]["km_at_change"] == 48000


def test_store_replace_creates_row_when_absent(tmp_path):
    from api import tyre_store
    p = str(tmp_path / "tyres.db")
    tyre_store.replace("9", changed_ts=42, path=p)
    assert tyre_store.get_all(p)["9"]["installed_ts"] == 42


# --- Сборка секции из архива -------------------------------------------------

def _seed_raw(path, terminal, per_day_km, days, start=0, step=86400):
    """Насыпать fact_daily: `days` суток по `per_day_km` км с даты `start`."""
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE IF NOT EXISTS fact_daily (terminal_id TEXT, date INTEGER, "
                 "payload TEXT, PRIMARY KEY(terminal_id,date))")
    for i in range(days):
        d = start + i * step
        payload = json.dumps({"consolidatedReport": {
            "vehicleId": terminal, "date": d, "mv": {"mileage": per_day_km}}})
        conn.execute("INSERT OR REPLACE INTO fact_daily VALUES (?,?,?)", (str(terminal), d, payload))
    conn.commit()
    conn.close()


class _V:
    def __init__(self, vid, name="Самосвал КамАЗ", km=8000.0, eh=100.0):
        self.vehicle_id, self.name = vid, name
        self.mileage_km, self.engine_hours, self.max_speed_kmh = km, eh, 0.0
        self.has_data = True


def test_build_tyres_accumulates_full_archive(tmp_path):
    from api import tyres as tyres_api
    raw = str(tmp_path / "raw.db")
    store = str(tmp_path / "tyres.db")
    # 300 суток по 250 км = 75 000 км ⇒ сверх ресурса heavy (50 000) ⇒ просрочено
    _seed_raw(raw, 7, per_day_km=250, days=300)
    section = tyres_api.build_tyres([_V(7)], now_ts=400 * 86400,
                                    raw_path=raw, store_path=store)
    item = section["items"][0]
    assert item["terminal_id"] == "7"
    assert abs(item["km_since"] - 75000) < 1
    assert item["status"] == "просрочено"
    assert section["wear_kzt_total"] > 0


def test_build_tyres_installed_ts_subtracts_prior(tmp_path):
    from api import tyres as tyres_api, tyre_store
    raw = str(tmp_path / "raw.db")
    store = str(tmp_path / "tyres.db")
    _seed_raw(raw, 7, per_day_km=250, days=300)     # всего 75 000 км
    # комплект установлен на 200-е сутки → до него 200×250=50 000 км вычитаются
    tyre_store.set_plan("7", installed_ts=200 * 86400, updated_at=1, path=store)
    section = tyres_api.build_tyres([_V(7)], now_ts=400 * 86400,
                                    raw_path=raw, store_path=store)
    item = section["items"][0]
    assert abs(item["km_since"] - 25000) < 300      # 75000 − 50000
    assert item["installed_ts"] == 200 * 86400


def test_build_tyres_skips_stationary():
    from api import tyres as tyres_api
    # буровая: моточасы есть, пробег ~0 → пропускается
    drill = _V(8, name="Буровая БУ-8", km=0.0, eh=500.0)
    section = tyres_api.build_tyres([drill], now_ts=86400, raw_path="/nonexistent.db",
                                    store_path="/nonexistent_store.db")
    assert section["items"] == []
