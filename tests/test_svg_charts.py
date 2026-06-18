"""Тесты hero-SVG графиков HTML-отчёта (Фаза 2 визуализации)."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from omnicomm_report import svg_charts  # noqa: E402
from omnicomm_report.models import (  # noqa: E402
    FleetKPI, FleetReport, ReportPeriod, VehicleMetrics,
)


def _report(**kpi_kw) -> FleetReport:
    period = ReportPeriod(
        start=datetime(2026, 5, 1, tzinfo=timezone.utc),
        end=datetime(2026, 5, 31, tzinfo=timezone.utc),
    )
    kpi = FleetKPI(**kpi_kw)
    return FleetReport(period=period, client_name="Тест", vehicles=[], kpi=kpi)


def test_money_split_renders_svg():
    r = _report(total_fuel_cost=12_000_000, idle_fuel_cost=2_700_000,
                potential_savings=800_000, fuel_price_kzt=320)
    svg = svg_charts.money_split(r.kpi, r)
    assert svg.startswith("<svg") and svg.endswith("</svg>")
    assert "млн" in svg and "₸" in svg       # деньги в коротком формате
    assert "на простое" in svg


def test_money_split_empty_without_cost():
    assert svg_charts.money_split(_report().kpi, _report()) == ""


def test_idle_bullet_markers():
    r = _report(idle_hours_share=0.25, idle_fuel_cost=2_700_000)
    svg = svg_charts.idle_bullet(r.kpi, worst=[("ТС-1", 0.95, 10.0)], avg=0.38)
    assert "<svg" in svg
    assert "цель 5%" in svg                   # маркер цели
    assert "среднее 38%" in svg               # маркер среднего по паркам
    assert "ТС-1" in svg                      # худший ТС в подписи


def test_idle_bullet_empty_without_idle():
    assert svg_charts.idle_bullet(_report().kpi, worst=[]) == ""


def test_norm_rating_with_norms():
    r = _report(vehicles_with_norm=2, vehicles_over_norm=1,
                total_overrun_cost=560_000, total_economy_cost=120_000)
    r.vehicles = [
        VehicleMetrics("1", "КАМАЗ-1", overrun_cost_kzt=560_000),
        VehicleMetrics("2", "КАМАЗ-2", overrun_cost_kzt=-120_000),
    ]
    svg = svg_charts.norm_rating(r)
    assert "<svg" in svg
    assert "Сальдо по парку" in svg
    assert "КАМАЗ-1" in svg                   # топ перерасхода


def test_norm_rating_empty_without_norms():
    assert svg_charts.norm_rating(_report(vehicles_with_norm=0)) == ""


def test_money_short_format():
    # _money использует неразрывные пробелы (\xa0) — нормализуем для сравнения.
    def n(x):
        return svg_charts._money(x).replace("\xa0", " ")
    assert n(3_200_000) == "3,2 млн ₸"
    assert n(558_000) == "558 тыс ₸"
    assert n(900) == "900 ₸"
