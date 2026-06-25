"""Тест поштучно-резюмируемого забора агрегатов (journal ingest_progress)."""

from __future__ import annotations

import os
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from api import raw_store, sync  # noqa: E402

DAY = 86400


def test_ingest_progress_journal(tmp_path):
    p = str(tmp_path / "raw.db")
    raw_store.mark_unit_done(1000, 1000 + 3 * DAY, "abc", p)
    raw_store.mark_unit_done(1000, 1000 + 3 * DAY, "abc", p)   # идемпотентно
    assert raw_store.done_units(0, 10 ** 12, p) == {(1000, 1000 + 3 * DAY, "abc")}
    raw_store.prune_before(1000 + 3 * DAY + 1, p)              # ретеншн чистит журнал
    assert raw_store.done_units(0, 10 ** 12, p) == set()


def test_aligned_windows_stable_across_now():
    # окна привязаны к сетке, не к now → стабильны между запусками
    w1 = sync._aligned_windows(100 * DAY, 110 * DAY, 3)
    w2 = sync._aligned_windows(100 * DAY, 110 * DAY, 3)
    assert w1 == w2 and len(w1) >= 3
    assert all((b - a) <= 3 * DAY for a, b in w1)


class FakeClient:
    """Сводный отчёт-заглушка: считает обращения, отдаёт строки по пачке×окну."""

    def __init__(self):
        self.calls = 0
        self._lock = threading.Lock()

    def get_consolidated_report(self, chunk, period):
        with self._lock:
            self.calls += 1
        wb = period.start_ts
        return [{"consolidatedReport": {"vehicleId": tid, "date": wb,
                                        "mv": {"mileage": 1}}} for tid in chunk]


def _run(fake, p, refresh_floor=0):
    return sync._resumable_ingest(
        lambda *_: None, [str(i) for i in range(120)],   # 3 пачки (50/50/20)
        100 * DAY, 131 * DAY, raw_path=p, workers=3, max_seconds=60,
        refresh_floor=refresh_floor, make_client=lambda: fake)


def test_resume_skips_done_units(tmp_path):
    p = str(tmp_path / "raw.db")
    f1 = FakeClient()
    r1 = _run(f1, p, refresh_floor=200 * DAY)           # все окна исторические → чекпоинт
    assert r1["already_done"] == 0
    assert r1["units_run"] == r1["units_total"] > 0
    assert f1.calls == r1["units_run"]                  # забрали все единицы
    # повторный запуск — НИЧЕГО не перезабирает (всё в журнале)
    f2 = FakeClient()
    r2 = _run(f2, p, refresh_floor=200 * DAY)
    assert r2["units_run"] == 0
    assert r2["already_done"] == r1["units_total"]
    assert f2.calls == 0                                # Omnicomm не тронут


def test_fresh_window_always_refetched(tmp_path):
    p = str(tmp_path / "raw.db")
    f1 = FakeClient()
    _run(f1, p, refresh_floor=0)                        # we > 0 → всё «свежее», не чекпоинтим
    f2 = FakeClient()
    r2 = _run(f2, p, refresh_floor=0)
    assert r2["units_run"] == r2["units_total"]         # свежие окна тянем заново
    assert f2.calls == r2["units_total"]
