"""Тесты календарного учёта цены ГСМ (история изменений по датам)."""

from __future__ import annotations

import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from omnicomm_report import price_history as ph  # noqa: E402


def _seed(tmp_path):
    p = str(tmp_path / "fuel_prices.json")
    ph.add_price("2026-01-01", 320, path=p)
    ph.add_price("2026-06-01", 340, path=p)
    return p


def test_price_on_specific_day(tmp_path):
    p = _seed(tmp_path)
    assert ph.price_on("2026-05-31", p) == 320     # до повышения
    assert ph.price_on("2026-06-01", p) == 340     # в день повышения
    assert ph.price_on("2026-07-15", p) == 340     # после
    assert ph.price_on("2025-12-01", p) is None    # раньше первой записи


def test_effective_price_blended_over_period(tmp_path):
    p = _seed(tmp_path)
    # май: 31 день по 320 → 320
    assert ph.effective_price("2026-05-01", "2026-05-31", p) == 320
    # период через повышение: 10 дней по 320 (22..31 мая) + 30 дней по 340 (июнь)
    eff = ph.effective_price("2026-05-22", "2026-06-30", p)
    assert 320 < eff < 340                          # средневзвешенная по дням


def test_price_for_period_falls_back_to_manual(tmp_path):
    p = str(tmp_path / "empty.json")
    price, blended = ph.price_for_period(333.0, "2026-05-01", "2026-05-31", path=p)
    assert price == 333.0 and blended is False      # календаря нет → ручная цена


def test_price_for_period_uses_calendar(tmp_path):
    p = _seed(tmp_path)
    price, blended = ph.price_for_period(999.0, "2026-06-01", "2026-06-30", path=p)
    assert price == 340 and blended is True         # календарь перекрывает ручную


def test_add_price_updates_same_date(tmp_path):
    p = str(tmp_path / "fuel_prices.json")
    ph.add_price("2026-06-01", 340, path=p)
    hist = ph.add_price("2026-06-01", 345, path=p)  # та же дата → обновление
    assert len(hist) == 1 and hist[0]["price"] == 345
    assert ph.price_on(date(2026, 6, 2), hist) == 345
