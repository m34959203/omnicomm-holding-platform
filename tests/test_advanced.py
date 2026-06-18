"""Тесты доп. аналитики: что-если, скоринг, алерты, коэффициент норм, бенчмарк."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from omnicomm_report import analytics, benchmark, norms  # noqa: E402
from omnicomm_report.models import FleetKPI, ReportPeriod, VehicleMetrics  # noqa: E402


def _period():
    return ReportPeriod(start=datetime(2026, 5, 1, tzinfo=timezone.utc),
                        end=datetime(2026, 5, 31, tzinfo=timezone.utc))


def test_whatif_scenarios():
    kpi = FleetKPI(fuel_idle_l=1000, idle_fuel_cost=320000)
    wi = analytics.build_whatif(kpi)
    cuts = {round(s["cut"], 2): s for s in wi}
    assert cuts[0.30]["saved_l"] == 300.0
    assert cuts[0.30]["saved_kzt"] == 96000.0


def test_scorecard_ranks_worst_first():
    vs = [
        VehicleMetrics("1", "Чистый", mileage_km=100, fuel_l=30, engine_hours=5,
                       engine_idle_hours=0),
        VehicleMetrics("2", "Проблемный", mileage_km=100, fuel_l=80, engine_hours=10,
                       engine_idle_hours=8, speeding_count=40),
    ]
    cards = analytics.build_scorecard(vs)
    assert cards[0]["name"] == "Проблемный"
    assert cards[0]["score"] > cards[-1]["score"]


def test_alert_on_big_overrun():
    v = VehicleMetrics("1", "КАМАЗ", mileage_km=1000, fuel_l=800)
    norms.apply_and_compute([v], {"КАМАЗ": {"l_100km": 30}}, fuel_price_kzt=320)
    # факт 80 л/100км, норма 30 → перерасход (80-30)*1000/100=500 л = 160000 ₸
    rep = analytics.analyze([v], _period(), "Тест", fuel_price_kzt=320,
                            norms={"КАМАЗ": {"l_100km": 30}})
    assert any("Перерасход" in a for a in rep.alerts)


def test_winter_season_reduces_overrun():
    """Зима (+10% к норме) → ожидаемый расход выше → перерасход в ₸ меньше."""
    vs = lambda: [VehicleMetrics("1", "КАМАЗ", mileage_km=1000, fuel_l=400)]  # noqa: E731
    nrm = {"КАМАЗ": {"l_100km": 35}}
    summer = analytics.analyze(vs(), _period(), "Т", fuel_price_kzt=320,
                               norms=nrm, season="summer")
    winter = analytics.analyze(vs(), _period(), "Т", fuel_price_kzt=320,
                               norms=nrm, season="winter")
    assert winter.kpi.total_overrun_cost < summer.kpi.total_overrun_cost
    assert winter.season == "winter"


def test_norm_coefficient_scales_expected():
    """Коэффициент (зима/свалка) увеличивает норму → меньше перерасход."""
    v1 = VehicleMetrics("1", "A", mileage_km=100, fuel_l=44)
    norms.apply_and_compute([v1], {"A": {"l_100km": 40}})              # без коэф
    v2 = VehicleMetrics("2", "A", mileage_km=100, fuel_l=44)
    norms.apply_and_compute([v2], {"A": {"l_100km": 40, "coeff": 1.10}})  # +10%
    assert v1.overrun_l > v2.overrun_l                                  # норма выше → перерасход ниже


def test_money_loss_pareto():
    vs = [
        VehicleMetrics("1", "A", mileage_km=100, fuel_l=200, fuel_idle_l=100),  # потери idle
        VehicleMetrics("2", "B", mileage_km=100, fuel_l=50, fuel_idle_l=10),
    ]
    top = analytics.rank_money_loss(vs, 320, top_n=5)
    assert top[0]["name"] == "A"                    # больше потерь сверху
    assert 0 < top[0]["share"] <= 1
    assert analytics.rank_money_loss(vs, 0) == []   # без цены — пусто


def test_annualize():
    from datetime import datetime, timezone
    from omnicomm_report.models import ReportPeriod
    p = ReportPeriod(start=datetime(2026, 5, 1, tzinfo=timezone.utc),
                     end=datetime(2026, 5, 31, tzinfo=timezone.utc))  # ~30 дней
    assert analytics.annualize(1000, p) > 11000     # ×~12


def test_savings_estimate_flag_and_per_km():
    # нет датчиков → savings_is_estimate True, считается от всего idle
    vs = [VehicleMetrics("1", "КАМАЗ", mileage_km=1000, fuel_l=400, fuel_idle_l=100,
                         engine_hours=50)]
    kpi = analytics.compute_kpi(vs, fuel_price_kzt=320)
    assert kpi.savings_is_estimate is True
    assert kpi.fuel_cost_per_km > 0 and kpi.fuel_cost_per_mh > 0
    assert kpi.potential_savings == round(100 * 320 * 0.30, 0)   # от idle 100 л


def test_speed_cap_by_type():
    """Класс-зависимый порог: 168 км/ч у мусоровоза — глюк, у легкового — норм."""
    truck = VehicleMetrics("1", "Мусоровоз", max_speed_kmh=168, mileage_km=100, fuel_l=50)
    truck.vehicle_type = "refuse_truck"
    car = VehicleMetrics("2", "Легковой", max_speed_kmh=168, mileage_km=100, fuel_l=50)
    car.vehicle_type = "car"
    analytics._sanitize_speed_by_type([truck, car])
    assert truck.max_speed_kmh is None              # отсечён (cap 110)
    assert any("скорост" in a.message.lower() for a in truck.anomalies)
    assert car.max_speed_kmh == 168                 # для легкового допустимо


def test_mobile_fuel_per_100km_excludes_stationary():
    """Титульный л/100км — только по мобильным; спецтехника не завышает."""
    vs = [
        VehicleMetrics("1", "Грузовик", mileage_km=1000, fuel_l=300),   # 30 л/100км
        VehicleMetrics("2", "Экскаватор", mileage_km=2, fuel_l=400, engine_hours=50),  # стац.
    ]
    kpi = analytics.compute_kpi(vs)
    assert kpi.mobile_fuel_per_100km == 30.0        # только грузовик
    assert kpi.weighted_fuel_per_100km > 30.0       # общий завышен экскаватором


def test_benchmark_anonymized(tmp_path):
    from omnicomm_report import history
    d = str(tmp_path)
    # два «других» клиента в истории
    for name, f100, idle in [("Клиент A", 30.0, 0.4), ("Клиент B", 40.0, 0.6)]:
        rep = analytics.analyze([VehicleMetrics("1", "x", mileage_km=100, fuel_l=35)],
                                _period(), name)
        rep.kpi.weighted_fuel_per_100km = f100
        rep.kpi.idle_hours_share = idle
        history.save_snapshot(rep, history_dir=d)
    cur = FleetKPI(weighted_fuel_per_100km=25.0, idle_hours_share=0.3)
    b = benchmark.compute("Горкомтранс", cur, history_dir=d)
    assert b["peers"] == 2
    # 25 < среднее(35) → лучше по расходу
    assert b["metrics"]["weighted_fuel_per_100km"]["better"] is True
