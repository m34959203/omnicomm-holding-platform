"""Тесты норм расхода и расчёта перерасхода/экономии."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from omnicomm_report import norms  # noqa: E402
from omnicomm_report.models import VehicleMetrics  # noqa: E402


def test_save_load_roundtrip(tmp_path):
    data = {"КАМАЗ 01": {"engine": "КАМАЗ 740", "l_100km": 35, "l_mh": 4}}
    norms.save_norms("Горкомтранс", data, norms_dir=str(tmp_path))
    loaded = norms.load_norms("Горкомтранс", norms_dir=str(tmp_path))
    assert loaded["КАМАЗ 01"]["l_100km"] == 35
    assert norms.load_norms("Другой", norms_dir=str(tmp_path)) == {}


def test_overrun_combined():
    """Полная модель: пробег·l/100 + моточасы_стоя·l/мч."""
    v = VehicleMetrics("1", "М", mileage_km=100, fuel_l=60, work_no_move_hours=10)
    norms.apply_and_compute([v], {"М": {"l_100km": 30, "l_mh": 2}}, fuel_price_kzt=320)
    # expected = 30*1 + 2*10 = 50; факт 60 → перерасход 10 л
    assert v.overrun_basis == "combined"
    assert v.overrun_l == 10.0
    assert v.overrun_cost_kzt == 3200.0


def test_overrun_per_100km_only():
    v = VehicleMetrics("2", "Т", mileage_km=200, fuel_l=80)  # факт 40 л/100км
    norms.apply_and_compute([v], {"Т": {"l_100km": 30}})
    assert v.overrun_basis == "100km"
    assert v.overrun_l == 20.0          # (40-30)*200/100


def test_economy_per_mh_only():
    v = VehicleMetrics("3", "Э", fuel_l=40, engine_hours=10)  # факт 4 л/мч
    norms.apply_and_compute([v], {"Э": {"l_mh": 5}})
    assert v.overrun_basis == "mh"
    assert v.overrun_l == -10.0         # (4-5)*10 → экономия


def test_no_norm_no_overrun():
    v = VehicleMetrics("4", "Б", mileage_km=100, fuel_l=50)
    norms.apply_and_compute([v], {})    # норм нет
    assert v.overrun_l is None
    assert v.overrun_basis is None


def test_kpi_aggregates_overrun():
    from datetime import datetime, timezone

    from omnicomm_report import analytics
    from omnicomm_report.models import ReportPeriod
    vs = [
        VehicleMetrics("1", "A", mileage_km=200, fuel_l=80),   # +20 л перерасход
        VehicleMetrics("2", "B", fuel_l=40, engine_hours=10),  # −10 л экономия
    ]
    nrm = {"A": {"l_100km": 30}, "B": {"l_mh": 5}}
    rep = analytics.analyze(
        vs, ReportPeriod(start=datetime(2026, 5, 1, tzinfo=timezone.utc),
                         end=datetime(2026, 5, 31, tzinfo=timezone.utc)),
        "Тест", fuel_price_kzt=320, norms=nrm)
    assert rep.kpi.vehicles_with_norm == 2
    assert rep.kpi.vehicles_over_norm == 1
    assert rep.kpi.total_overrun_l == 20.0
    assert rep.kpi.total_economy_l == 10.0
    assert rep.kpi.total_overrun_cost == 6400.0
