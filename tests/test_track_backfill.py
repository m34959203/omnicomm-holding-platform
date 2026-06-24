"""Тесты бережного бэкфилла GPS-треков и локального архива (fact_track)."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from api import raw_store, track_backfill, vehicle  # noqa: E402

DAY = 86400
NOW = 100 * DAY + 5000           # фиксированное «сейчас» (детерминизм)
TODAY0 = (NOW // DAY) * DAY


def _daily(vid, ds, km):
    return {"consolidatedReport": {"vehicleId": vid, "date": ds, "mv": {"mileage": km}}}


def _rawpt(lat, lon, ts, speed=40, sat=8):
    return {"latitude": lat, "longitude": lon, "date": ts,
            "speed": speed, "satellitesCount": sat}


class FakeClient:
    """Минимальный клиент Omnicomm: считает забранные треки, отдаёт фикс-точки."""

    def __init__(self):
        self.track_calls = 0

    def list_vehicles(self):
        return [{"terminal_id": "1", "name": "Авто-1"},
                {"terminal_id": "2", "name": "Авто-2"}]

    def get_track(self, tid, period):
        self.track_calls += 1
        b = period.start_ts
        # «маршрут» с одним поворотом (упрощение оставит ~3 точки)
        return [_rawpt(43.20, 76.90, b + 0),
                _rawpt(43.21, 76.90, b + 60),
                _rawpt(43.21, 76.92, b + 120, speed=55)]


def _seed_aggregates(path):
    # день TODAY0: Авто-1 ехал (50 км), Авто-2 стоял (0 км → idle-skip)
    # день TODAY0-1: Авто-1 ехал (30 км)
    # день TODAY0-2: агрегатов НЕТ (no_aggregate_day)
    raw_store.upsert_daily([
        _daily("1", TODAY0, 50), _daily("2", TODAY0, 0),
        _daily("1", TODAY0 - DAY, 30),
    ], path)


def test_backfill_only_moving_days(tmp_path):
    p = str(tmp_path / "raw.db")
    _seed_aggregates(p)
    cl = FakeClient()
    res = track_backfill.run_track_backfill(
        lambda *_: None, days=3, raw_path=p, client=cl,
        rate_per_min=1e9, name_map={"1": "Авто-1", "2": "Авто-2"}, now=NOW)

    assert res["pulled"] == 2                 # Авто-1 за 2 дня; Авто-2 (стоял) пропущен
    assert cl.track_calls == 2                # ровно столько обращений в Omnicomm
    assert res["idle_days"] == 0              # день TODAY0 НЕ idle (Авто-1 ехал)
    assert res["no_aggregate_days"] == 1      # TODAY0-2 без агрегатов
    cov = raw_store.track_coverage(p)
    assert cov["track_days"] == 2 and cov["vehicles"] == 1


def test_backfill_idempotent_resume(tmp_path):
    p = str(tmp_path / "raw.db")
    _seed_aggregates(p)
    cl = FakeClient()
    track_backfill.run_track_backfill(
        lambda *_: None, days=3, raw_path=p, client=cl,
        rate_per_min=1e9, name_map={"1": "a", "2": "b"}, now=NOW)
    # Повторный запуск НИЧЕГО не перезабирает (уже в архиве).
    cl2 = FakeClient()
    res2 = track_backfill.run_track_backfill(
        lambda *_: None, days=3, raw_path=p, client=cl2,
        rate_per_min=1e9, name_map={"1": "a", "2": "b"}, now=NOW)
    assert res2["pulled"] == 0
    assert cl2.track_calls == 0               # сервер Omnicomm не тронут вовсе
    assert res2["skipped_present"] == 2


def test_backfill_wall_clock_cap(tmp_path):
    p = str(tmp_path / "raw.db")
    _seed_aggregates(p)
    cl = FakeClient()
    res = track_backfill.run_track_backfill(
        lambda *_: None, days=3, raw_path=p, client=cl,
        rate_per_min=1e9, max_seconds=0, now=NOW)
    assert res["stopped_by_cap"] is True
    assert res["pulled"] == 0                 # кап = 0 → сразу выходим, Omnicomm не трогаем
    assert cl.track_calls == 0


def test_backfill_stores_simplified(tmp_path):
    p = str(tmp_path / "raw.db")
    _seed_aggregates(p)
    cl = FakeClient()
    track_backfill.run_track_backfill(
        lambda *_: None, days=1, raw_path=p, client=cl,
        rate_per_min=1e9, name_map={"1": "a", "2": "b"}, now=NOW)
    pts = raw_store.load_track("1", TODAY0, TODAY0 + DAY, p)
    assert 0 < len(pts) <= 3                   # упрощено, не сырьё
    assert all({"lat", "lon", "speed", "ts"} <= set(pt) for pt in pts)


def test_fact_track_upsert_load_prune(tmp_path):
    p = str(tmp_path / "raw.db")
    raw_store.upsert_track("9", TODAY0, [
        {"lat": 43.2, "lon": 76.9, "speed": 10, "ts": TODAY0 + 5},
        {"lat": 43.3, "lon": 76.9, "speed": 80, "ts": TODAY0 + 60},
    ], path=p)
    assert raw_store.has_track("9", TODAY0, p) is True
    cov = raw_store.track_coverage(p)
    assert cov["track_days"] == 1 and cov["track_points"] == 2
    assert raw_store.load_track("9", TODAY0, TODAY0 + DAY, p)[0]["speed"] == 10
    # ретеншн чистит и треки
    raw_store.upsert_track("9", TODAY0 - 400 * DAY, [
        {"lat": 1, "lon": 1, "speed": 0, "ts": TODAY0 - 400 * DAY}], path=p)
    raw_store.prune_before(TODAY0 - 365 * DAY, p)
    assert raw_store.track_coverage(p)["track_days"] == 1


def test_vehicle_card_reads_store_no_omnicomm(tmp_path):
    p = str(tmp_path / "raw.db")
    raw_store.upsert_track("7", TODAY0, [
        {"lat": 43.2, "lon": 76.9, "speed": 12, "ts": TODAY0 + 10},
        {"lat": 43.25, "lon": 76.95, "speed": 60, "ts": TODAY0 + 120}], path=p)
    # Подменяем дефолтный путь архива на временный → карточка читает локально.
    orig = raw_store.DEFAULT_PATH
    raw_store.DEFAULT_PATH = p
    try:
        card = vehicle.track_detail("7", TODAY0, TODAY0 + DAY)
    finally:
        raw_store.DEFAULT_PATH = orig
    assert card["source"] == "store"           # из архива, без обращения в Omnicomm
    assert card["track_points"] == 2
    assert card["track_max_speed"] == 60
