"""Тесты авто-сигналов: холостой ход исключает спецтехнику; перерасход; данные."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from omnicomm_report import alerts  # noqa: E402
from omnicomm_report.models import (  # noqa: E402
    FleetKPI, FleetReport, ReportPeriod, VehicleMetrics,
)


def _report(vehicles, **kpi_kw):
    period = ReportPeriod(datetime(2026, 5, 1, tzinfo=timezone.utc),
                          datetime(2026, 5, 31, tzinfo=timezone.utc))
    kpi = FleetKPI(vehicles_total=len(vehicles),
                   vehicles_with_data=sum(1 for v in vehicles if v.has_data), **kpi_kw)
    return FleetReport(period=period, client_name="Т", vehicles=vehicles, kpi=kpi)


def test_idle_alert_skips_stationary_equipment():
    """Погрузчик 100% «стоя» — это работа, не простой → не сигналим."""
    loader = VehicleMetrics("1", "Погрузчик", engine_hours=100, engine_idle_hours=100,
                            vehicle_type="loader")               # primary_metric l_per_mh
    truck = VehicleMetrics("2", "КАМАЗ", engine_hours=100, engine_idle_hours=63,
                           mileage_km=4000, vehicle_type="dump_truck")
    out = alerts.build_alerts(_report([loader, truck]))
    joined = " ".join(out)
    assert "Погрузчик" not in joined           # спецтехника исключена
    assert "КАМАЗ" in joined                    # подвижный транспорт сигналит
    assert "63%" in joined


def test_idle_alert_uses_unproductive_when_loading_known():
    """С разбивкой погрузки сигналим по НЕпродуктивному простою, а не всему стоя."""
    v = VehicleMetrics("1", "Мусоровоз", engine_hours=100, engine_idle_hours=80,
                       mileage_km=3000, vehicle_type="refuse_truck",
                       loading_hours=40, unproductive_idle_hours=55)  # 55% непрод.
    out = alerts.build_alerts(_report([v]))
    assert any("Непродуктивный простой" in a and "55%" in a for a in out)


def test_overrun_alert_threshold():
    v = VehicleMetrics("1", "КАМАЗ", overrun_cost_kzt=163_000, overrun_l=478)
    low = VehicleMetrics("2", "Малый", overrun_cost_kzt=50_000, overrun_l=100)
    out = alerts.build_alerts(_report([v, low]))
    assert any("Перерасход" in a and "КАМАЗ" in a for a in out)
    assert not any("Малый" in a for a in out)   # ниже порога 100k


def test_nodata_alert():
    veh = [VehicleMetrics(str(i), f"ТС{i}") for i in range(9)]
    veh += [VehicleMetrics("x", "Тёмный", has_data=False)]
    out = alerts.build_alerts(_report(veh))      # 1/10 = 10% ≥ порога
    assert any("без данных" in a for a in out)
