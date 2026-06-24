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


# refresh_days по умолчанию = INGEST_WINDOW_DAYS=2 → свежие завершённые сутки: T-1, T-2.
def _seed_aggregates(path):
    # T0 (неполный, текущий): Авто-1 ехал 50 → НЕ архивируем (skipped_incomplete)
    # T-1 (завершён, свежий):  Авто-1 ехал 30 → забираем, при повторе ПЕРЕЗАБИРАЕМ
    # T-3 (завершён, старый):  Авто-2 ехал 20 → забираем, при повторе ЗАМОРОЖЕН
    # T-2,T-4..: агрегатов нет (no_aggregate_day)
    raw_store.upsert_daily([
        _daily("1", TODAY0, 50),
        _daily("1", TODAY0 - DAY, 30),
        _daily("2", TODAY0 - 3 * DAY, 20),
    ], path)


def test_backfill_skips_incomplete_day_and_idle(tmp_path):
    p = str(tmp_path / "raw.db")
    _seed_aggregates(p)
    cl = FakeClient()
    res = track_backfill.run_track_backfill(
        lambda *_: None, days=7, raw_path=p, client=cl,
        rate_per_min=1e9, name_map={"1": "Авто-1", "2": "Авто-2"}, now=NOW)

    assert res["pulled"] == 2                 # Авто-1@T-1 и Авто-2@T-3 (завершённые)
    assert cl.track_calls == 2
    assert res["skipped_incomplete"] == 1     # текущий неполный день (T0) НЕ заморожен
    assert res["no_aggregate_days"] == 4      # T-2,T-4,T-5,T-6 без агрегатов
    # трека за текущий неполный день в архиве нет (не морозим частичный)
    assert raw_store.load_track("1", TODAY0, TODAY0 + DAY, p) == []
    cov = raw_store.track_coverage(p)
    assert cov["track_days"] == 2


def test_backfill_freezes_old_refreshes_recent(tmp_path):
    """Правило свежести зеркалит агрегаты: старый завершённый день заморожен,
    последние INGEST_WINDOW_DAYS суток перезабираются (поглощают опоздавшие точки)."""
    p = str(tmp_path / "raw.db")
    _seed_aggregates(p)
    track_backfill.run_track_backfill(
        lambda *_: None, days=7, raw_path=p, client=FakeClient(),
        rate_per_min=1e9, name_map={"1": "a", "2": "b"}, now=NOW)
    cl2 = FakeClient()
    res2 = track_backfill.run_track_backfill(
        lambda *_: None, days=7, raw_path=p, client=cl2,
        rate_per_min=1e9, name_map={"1": "a", "2": "b"}, now=NOW)
    assert res2["pulled"] == 0                # новых дней нет
    assert res2["refreshed"] == 1             # T-1 (свежий) перезабран
    assert res2["skipped_present"] == 1       # T-3 (старый) заморожен
    assert cl2.track_calls == 1               # старый день Omnicomm НЕ тронул


def test_backfill_wall_clock_cap(tmp_path):
    p = str(tmp_path / "raw.db")
    _seed_aggregates(p)
    cl = FakeClient()
    res = track_backfill.run_track_backfill(
        lambda *_: None, days=7, raw_path=p, client=cl,
        rate_per_min=1e9, max_seconds=0, now=NOW)
    assert res["stopped_by_cap"] is True
    assert res["pulled"] == 0                 # кап = 0 → сразу выходим, Omnicomm не трогаем
    assert cl.track_calls == 0


def test_backfill_stores_simplified(tmp_path):
    p = str(tmp_path / "raw.db")
    _seed_aggregates(p)
    cl = FakeClient()
    track_backfill.run_track_backfill(
        lambda *_: None, days=7, raw_path=p, client=cl,
        rate_per_min=1e9, name_map={"1": "a", "2": "b"}, now=NOW)
    pts = raw_store.load_track("1", TODAY0 - DAY, TODAY0, p)   # завершённый день T-1
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
