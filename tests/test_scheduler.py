"""Тесты планировщика: расписание (is_due/last_occurrence), состояние."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from omnicomm_report import scheduler  # noqa: E402


def _dt(y, m, d, h=12, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=timezone.utc)


def test_last_occurrence_daily():
    sch = {"enabled": True, "freq": "daily", "hour": 6}
    # сейчас 12:00 → последний слот сегодня 06:00
    occ = scheduler.last_occurrence(sch, _dt(2026, 6, 10, 12))
    assert occ.hour == 6 and occ.date() == _dt(2026, 6, 10).date()
    # сейчас 05:00 → слот был вчера 06:00
    occ2 = scheduler.last_occurrence(sch, _dt(2026, 6, 10, 5))
    assert occ2.date().day == 9


def test_last_occurrence_monthly():
    sch = {"enabled": True, "freq": "monthly", "hour": 6, "day": 1}
    occ = scheduler.last_occurrence(sch, _dt(2026, 6, 10))
    assert occ.day == 1 and occ.month == 6
    # 1-го числа в 05:00 → слот в прошлом месяце
    occ2 = scheduler.last_occurrence(sch, _dt(2026, 6, 1, 5))
    assert occ2.month == 5


def test_last_occurrence_weekly():
    sch = {"enabled": True, "freq": "weekly", "hour": 6, "weekday": 0}  # Пн
    # 2026-06-10 — среда → последний Пн = 2026-06-08
    occ = scheduler.last_occurrence(sch, _dt(2026, 6, 10))
    assert occ.weekday() == 0 and occ.day == 8


def test_is_due_logic():
    sch = {"enabled": True, "freq": "daily", "hour": 6}
    now = _dt(2026, 6, 10, 12)
    occ = scheduler.last_occurrence(sch, now).timestamp()
    assert scheduler.is_due(sch, None, now) is True            # ни разу не запускали
    assert scheduler.is_due(sch, occ - 1, now) is True         # последний прогон до слота
    assert scheduler.is_due(sch, occ + 1, now) is False        # уже прогоняли после слота
    assert scheduler.is_due({"enabled": False}, None, now) is False


def test_state_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(scheduler, "STATE_DIR", str(tmp_path))
    scheduler.save_state("Клиент", {"last_run_ts": 123.0, "last_ok": True})
    assert scheduler.load_state("Клиент")["last_run_ts"] == 123.0


def test_heartbeat(tmp_path, monkeypatch):
    monkeypatch.setattr(scheduler, "HEARTBEAT_PATH", str(tmp_path / "hb.json"))
    scheduler.write_heartbeat(datetime.now(timezone.utc))
    assert scheduler.heartbeat_alive(max_age_s=60) is True


def test_preset_period_last_month():
    p = scheduler.preset_period("last-month", _dt(2026, 6, 10))
    assert p.start.month == 5 and p.end.month == 5


def test_snapshot_fuel_price_writes_calendar(tmp_path, monkeypatch):
    """Ежедневный снапшот пишет цену дня в календарь и не дублирует за день."""
    from omnicomm_report import price_history
    fuel_state = str(tmp_path / "fuel_state.json")
    cal = str(tmp_path / "fuel_prices.json")
    monkeypatch.setattr(scheduler, "FUEL_STATE_PATH", fuel_state)
    monkeypatch.setattr(price_history, "DEFAULT_PATH", cal)
    monkeypatch.setattr(scheduler.fuel_price, "get_reference",
                        lambda season: {"diesel": 342.0})
    now = _dt(2026, 6, 8, 6)
    assert scheduler.snapshot_fuel_price(now) == 342.0
    assert price_history.price_on("2026-06-08", cal) == 342.0
    # повторно в тот же день — no-op
    assert scheduler.snapshot_fuel_price(now) is None


def test_snapshot_fuel_price_cooldown_on_failure(tmp_path, monkeypatch):
    """При сбое парсера — кулдаун, не дёргаем каждый тик; календарь пуст."""
    from omnicomm_report import price_history
    monkeypatch.setattr(scheduler, "FUEL_STATE_PATH", str(tmp_path / "s.json"))
    monkeypatch.setattr(price_history, "DEFAULT_PATH", str(tmp_path / "c.json"))
    monkeypatch.setattr(scheduler.fuel_price, "get_reference", lambda season: None)
    now = _dt(2026, 6, 8, 6)
    assert scheduler.snapshot_fuel_price(now) is None
    assert price_history.load_history(str(tmp_path / "c.json")) == []
    # следующий тик в пределах часа — кулдаун (no-op)
    assert scheduler.snapshot_fuel_price(_dt(2026, 6, 8, 6, 5)) is None
