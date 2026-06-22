"""Тесты контроля ТО."""

from omnicomm_report import maintenance as mt


def _rec(date, worked_sec=0, mileage_km=0.0):
    return {"date": date, "worked_sec": worked_sec, "mileage_km": mileage_km}


def test_compute_since_sums_from_t0_idempotent():
    recs = [_rec(100, 3600, 10), _rec(200, 1800, 5), _rec(50, 7200, 99)]  # 50 < T0=100
    mh, km = mt.compute_since(recs, since_ts=100)
    assert mh == 1.5 and km == 15.0     # запись до T0 исключена


def test_from_consolidated_extracts_daily():
    rows = [{"consolidatedReport": {"vehicleId": 7, "date": 100,
                                    "mv": {"worked": 3600, "mileage": 12.0}}}]
    recs = mt.from_consolidated(rows)
    assert recs["7"][0]["worked_sec"] == 3600 and recs["7"][0]["mileage_km"] == 12.0


def test_evaluate_statuses():
    plan = mt.MaintenancePlan("7", interval_mh=250, remind_before_mh=20)
    assert mt.evaluate(plan, 100, 0).status == "ok"
    assert mt.evaluate(plan, 235, 0).status == "ожидается"   # осталось 15 ≤ 20
    assert mt.evaluate(plan, 260, 0).status == "просрочено"  # превышено


def test_evaluate_by_mileage():
    plan = mt.MaintenancePlan("7", interval_km=10000, remind_before_km=500)
    assert mt.evaluate(plan, 0, 9800).status == "ожидается"
    assert mt.evaluate(plan, 0, 10500).status == "просрочено"


def test_confirm_resets_cycle():
    st = mt.MaintenanceState("7", t0=100)
    st2 = mt.confirm_to(st, at_ts=5000)
    assert st2.t0 == 5000 and st2.last_to_at == 5000


def test_fleet_status_sorted():
    plans = {"1": mt.MaintenancePlan("1", interval_mh=250),
             "2": mt.MaintenancePlan("2", interval_mh=250)}
    states = {"1": mt.MaintenanceState("1", t0=0), "2": mt.MaintenanceState("2", t0=0)}
    recs = {"1": [{"date": 1, "worked_sec": 100 * 3600, "mileage_km": 0}],   # ok
            "2": [{"date": 1, "worked_sec": 300 * 3600, "mileage_km": 0}]}   # просрочено
    out = mt.fleet_status(plans, states, recs)
    assert out[0].terminal_id == "2" and out[0].status == "просрочено"


def test_maintenance_persistence(tmp_path):
    from omnicomm_report import store
    db = str(tmp_path / "reg.db")
    plans = {"7": mt.MaintenancePlan("7", interval_mh=250, interval_km=10000)}
    states = {"7": mt.MaintenanceState("7", t0=1000, last_to_at=1000)}
    store.save_maintenance(plans, states, db)
    p2, s2 = store.load_maintenance(db)
    assert p2["7"].interval_mh == 250 and p2["7"].interval_km == 10000
    assert s2["7"].t0 == 1000
