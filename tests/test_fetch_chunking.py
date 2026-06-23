"""Тест оконного чанкинга забора (лекарство от зависания на длинных периодах)."""

from datetime import datetime, timezone

from omnicomm_report.models import ReportPeriod
from api import fetch


def _period(d1, d2):
    return ReportPeriod(start=datetime(2026, 6, d1, tzinfo=timezone.utc),
                        end=datetime(2026, 6, d2, tzinfo=timezone.utc))


def test_time_windows_slice_contiguous():
    p = _period(1, 10)                      # 9 суток
    w = fetch._time_windows(p, 3)
    assert len(w) == 3                       # 9 / 3
    assert w[0].start == p.start and w[-1].end == p.end
    for a, b in zip(w, w[1:]):               # без дыр и нахлёстов
        assert a.end == b.start


def test_time_windows_none_is_whole_period():
    p = _period(1, 5)
    assert fetch._time_windows(p, None) == [p]
    assert fetch._time_windows(p, 0) == [p]


def test_fetch_expands_units_by_window():
    calls = []

    def call(c, chunk, period):
        calls.append((len(chunk), period.start_ts, period.end_ts))
        return [{"u": 1}]

    ids = [str(i) for i in range(120)]       # 120/50 = 3 батча ТС
    p = _period(1, 7)                        # 6 суток / 3 = 2 окна
    res = fetch.fetch_report_parallel(
        lambda: object(), ids, p, call=call, label="t", workers=4, window_days=3)
    assert len(calls) == 3 * 2               # 3 батча × 2 окна = 6 единиц
    assert len(res) == 6


def test_fetch_no_window_single_unit_per_batch():
    calls = []
    res = fetch.fetch_report_parallel(
        lambda: object(), [str(i) for i in range(120)], _period(1, 30),
        call=lambda c, ch, p: (calls.append(1) or [{"u": 1}]),
        label="t", workers=4)               # без window_days
    assert len(calls) == 3                    # 3 батча × 1 окно
