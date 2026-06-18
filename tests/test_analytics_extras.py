"""Тесты расширенной аналитики: использование, деньги (₸), рейтинги, тренды."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from omnicomm_report import analytics, history  # noqa: E402
from omnicomm_report.models import FleetKPI, ReportPeriod, VehicleMetrics  # noqa: E402


def _vehicles():
    return [
        # мобильный: большой пробег на моточас
        VehicleMetrics("1", "Грузовик", mileage_km=5000, fuel_l=2000,
                       engine_hours=100, engine_idle_hours=20, fuel_idle_l=300,
                       max_speed_kmh=90, speeding_count=10),
        # спецтехника: почти нет пробега, много моточасов
        VehicleMetrics("2", "Экскаватор", mileage_km=5, fuel_l=1500,
                       engine_hours=120, engine_idle_hours=80, fuel_idle_l=600,
                       max_speed_kmh=12),
    ]


def _period():
    return ReportPeriod(start=datetime(2026, 5, 1, tzinfo=timezone.utc),
                        end=datetime(2026, 5, 31, tzinfo=timezone.utc))


def test_idle_and_utilization():
    kpi = analytics.compute_kpi(_vehicles())
    assert kpi.total_engine_hours == 220.0
    assert kpi.total_idle_hours == 100.0
    assert kpi.movement_hours == 120.0
    assert round(kpi.idle_hours_share, 3) == round(100 / 220, 3)


def test_money_in_tenge():
    kpi = analytics.compute_kpi(_vehicles(), fuel_price_kzt=320.0)
    assert kpi.total_fuel_cost == 3500 * 320          # (2000+1500)*320
    assert kpi.idle_fuel_cost == 900 * 320            # (300+600)*320
    assert kpi.potential_savings == round(900 * 320 * 0.30, 0)
    # без цены — денег нет
    assert analytics.compute_kpi(_vehicles()).total_fuel_cost == 0


def test_vehicle_classification():
    kpi = analytics.compute_kpi(_vehicles())
    assert kpi.mobile_count == 1
    assert kpi.stationary_count == 1


def test_is_stationary_property():
    v = _vehicles()
    assert v[0].is_stationary is False        # грузовик
    assert v[1].is_stationary is True         # экскаватор
    assert v[1].fuel_per_motorhour == 12.5    # 1500/120


def test_dynamic_recommendations_reference_data():
    vs = _vehicles()
    kpi = analytics.compute_kpi(vs, fuel_price_kzt=320.0)
    recs = analytics.build_recommendations(vs, kpi)
    joined = " ".join(recs)
    assert "холостой ход" in joined.lower()
    assert "₸" in joined                       # экономия в деньгах упомянута


def test_trends_deltas():
    prev = FleetKPI(total_mileage_km=1000, total_fuel_l=500)
    cur = FleetKPI(total_mileage_km=1200, total_fuel_l=450)
    trends = analytics.compute_trends(cur, prev)
    assert trends["total_mileage_km"] == 20.0   # +20%
    assert trends["total_fuel_l"] == -10.0      # -10%
    assert analytics.compute_trends(cur, None) == {}


def test_history_save_and_load(tmp_path):
    """Снапшот KPI сохраняется и подтягивается как «прошлый период»."""
    hist = str(tmp_path)
    # прошлый период (апрель)
    apr = ReportPeriod(start=datetime(2026, 4, 1, tzinfo=timezone.utc),
                       end=datetime(2026, 4, 30, tzinfo=timezone.utc))
    rep_apr = analytics.analyze(_vehicles(), apr, "ООО Тест", fuel_price_kzt=320.0)
    history.save_snapshot(rep_apr, history_dir=hist)

    # текущий период (май) — должен найти апрельский снапшот
    prev = history.load_previous("ООО Тест", _period(), history_dir=hist)
    assert prev is not None
    assert prev.total_mileage_km == rep_apr.kpi.total_mileage_km
    # для несуществующего клиента — None
    assert history.load_previous("Другой", _period(), history_dir=hist) is None
