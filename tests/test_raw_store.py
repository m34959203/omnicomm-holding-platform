"""Тест сырого хранилища инкрементального синка (upsert суток/визитов, диапазон)."""

from api import raw_store


def test_daily_upsert_overwrite_and_range(tmp_path):
    p = str(tmp_path / "raw.db")
    recs = [
        {"consolidatedReport": {"vehicleId": 1, "date": 1000, "mv": {"mileage": 10}}},
        {"consolidatedReport": {"vehicleId": 1, "date": 1000, "mv": {"mileage": 99}}},  # тот же день → перезапись
        {"consolidatedReport": {"vehicleId": 2, "date": 2000, "mv": {}}},
    ]
    assert raw_store.upsert_daily(recs, p) == 3
    loaded = raw_store.load_daily(0, 5000, p)
    assert len(loaded) == 2                              # (1,1000) перезаписан, (2,2000)
    by = {raw_store._cr(r)["vehicleId"]: raw_store._cr(r)["mv"].get("mileage") for r in loaded}
    assert by[1] == 99                                   # сохранилось последнее значение
    assert len(raw_store.load_daily(1500, 5000, p)) == 1  # фильтр по диапазону
    cov = raw_store.coverage(p)
    assert cov["daily_rows"] == 2 and cov["date_min"] == 1000 and cov["date_max"] == 2000


def test_visits_upsert_dedup(tmp_path):
    p = str(tmp_path / "raw.db")
    vis = [
        {"vehicleId": 1, "geozoneName": "z", "geoInfo": {"startDate": 1000}},
        {"vehicleId": 1, "geozoneName": "z", "geoInfo": {"startDate": 1000}},  # дубль
        {"vehicleId": 1, "geozoneName": "z", "geoInfo": {"startDate": 2000}},
    ]
    raw_store.upsert_visits(vis, p)
    assert len(raw_store.load_visits(0, 5000, p)) == 2


def test_empty_store_safe(tmp_path):
    p = str(tmp_path / "none.db")
    assert raw_store.load_daily(0, 9999, p) == []
    assert raw_store.coverage(p)["daily_rows"] == 0


def test_prune(tmp_path):
    p = str(tmp_path / "raw.db")
    raw_store.upsert_daily([
        {"consolidatedReport": {"vehicleId": 1, "date": 100}},
        {"consolidatedReport": {"vehicleId": 1, "date": 9000}},
    ], p)
    assert raw_store.prune_before(5000, p) == 1
    assert raw_store.coverage(p)["daily_rows"] == 1
