"""Тест санитайза недостоверной макс. скорости (GPS-сбой)."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from omnicomm_report import validator  # noqa: E402
from omnicomm_report.models import Severity, VehicleMetrics  # noqa: E402


def test_impossible_speed_dropped_and_flagged():
    """655 км/ч — сбой GPS: убираем из KPI, помечаем «требует проверки»."""
    v = VehicleMetrics("1", "КАМАЗ", mileage_km=100, fuel_l=50, max_speed_kmh=655)
    validator.validate([v])
    assert v.max_speed_kmh is None     # исключено из показателей
    assert any(a.severity == Severity.REVIEW and "скорост" in a.message.lower()
               for a in v.anomalies)


def test_high_but_possible_speed_kept():
    """140 км/ч — высоко, но возможно: оставляем, только флажим."""
    v = VehicleMetrics("2", "Авто", mileage_km=100, fuel_l=50, max_speed_kmh=140)
    validator.validate([v])
    assert v.max_speed_kmh == 140.0
    assert any("скорост" in a.message.lower() for a in v.anomalies)


def test_normal_speed_no_flag():
    v = VehicleMetrics("3", "Авто", mileage_km=100, fuel_l=50, max_speed_kmh=90)
    validator.validate([v])
    assert v.max_speed_kmh == 90.0
    assert not any("скорост" in a.message.lower() for a in v.anomalies)
