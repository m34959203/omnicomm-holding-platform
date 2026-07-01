"""Тест выбора дефолтного снимка: свежий конец периода + штатное окно, не последний-по-synced_at."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api import cache  # noqa: E402


def _save(tmp, key, synced_at, veh):
    cache.save_snapshot({"fleet": {"vehicles": veh}}, period_key=key,
                        path=tmp, synced_at=synced_at)


def test_latest_prefers_recent_end_over_last_written(tmp_path):
    db = str(tmp_path / "snap.db")
    # 30-дн окно, кончается 2026-07-01 (свежие данные), записан РАНЬШЕ
    _save(db, "2026-06-01_2026-07-01", synced_at=1000, veh=2006)
    # 2-дн backfill окно в прошлом, записан ПОЗЖЕ (был бы «latest by synced_at»)
    _save(db, "2026-06-20_2026-06-22", synced_at=9999, veh=1998)
    snap = cache.latest_snapshot(path=db)
    # дефолт = окно со свежайшим концом, а не последнее записанное
    assert snap["_meta"]["period_key"] == "2026-06-01_2026-07-01"
    assert snap["fleet"]["vehicles"] == 2006


def test_latest_same_end_prefers_standard_window(tmp_path):
    db = str(tmp_path / "snap.db")
    # оба кончаются сегодня; дефолт — ближе к штатному 30-дн окну, не 365 и не 2-дн
    _save(db, "2025-07-01_2026-07-01", synced_at=5000, veh=2006)  # год
    _save(db, "2026-06-29_2026-07-01", synced_at=5001, veh=1500)  # 2 дня
    _save(db, "2026-06-01_2026-07-01", synced_at=4000, veh=2006)  # месяц (30)
    snap = cache.latest_snapshot(path=db)
    assert snap["_meta"]["period_key"] == "2026-06-01_2026-07-01"


def test_latest_none_on_empty(tmp_path):
    assert cache.latest_snapshot(path=str(tmp_path / "none.db")) is None
