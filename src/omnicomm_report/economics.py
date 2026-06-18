"""Экономический эффект: 4 корзины денег + потенциал + COI (cost of inaction).

Ядро стратегии «экономический эффект как продукт» (docs/STRATEGY.md §4.1):
каждая корзина переводит телеметрию в ₸ по прозрачной формуле и даёт две цифры —
«уже теряете» (existing, за период) и «потенциал» (если подтянуть худших до
медианы парка). COI — те же потери, нормированные в ₸/месяц: аргумент
«сколько вы теряете каждый месяц без программы».

Инварианты: перерасход — только при заданных нормах; оценочные корзины
(износ, эко-вождение) помечаются is_estimate и считаются по консервативным
отраслевым коэффициентам из config (источники — в комментариях config).
Без цены топлива (fuel_price_kzt=0) денежные корзины не считаются.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from statistics import median

from omnicomm_report import config
from omnicomm_report.models import FleetKPI, FleetReport, VehicleMetrics

log = logging.getLogger(__name__)


@dataclass
class Bucket:
    """Одна корзина денег."""

    key: str
    label: str
    existing_kzt: float = 0.0      # потери за период отчёта, ₸
    potential_kzt: float = 0.0     # достижимая экономия за период, ₸
    is_estimate: bool = False      # True → в отчёте помечается «≈ оценка»
    note: str = ""                 # формула/основание одним предложением


@dataclass
class Economics:
    """Результат build_economics — вход для слайда и HTML-блока."""

    period_days: float = 0.0
    buckets: list[Bucket] = field(default_factory=list)
    total_existing_kzt: float = 0.0
    total_potential_kzt: float = 0.0
    coi_monthly_kzt: float = 0.0   # суммарные адресуемые потери, ₸/мес
    coi_annual_kzt: float = 0.0
    worst_vehicles: list[tuple[str, float]] = field(default_factory=list)
    # медианная доля холостого хода парка — базовая линия «потенциала»
    median_idle_share: float = 0.0


def _period_days(report: FleetReport) -> float:
    seconds = max(0, report.period.end_ts - report.period.start_ts)
    return max(1.0, seconds / 86400.0)


def _monthly(value_per_period: float, days: float) -> float:
    return value_per_period / days * 30.0


def _idle_fuel_rate_l_per_h(kpi: FleetKPI) -> float:
    """Средний расход на холостом ходу по факту парка, л/ч (не справочник)."""
    if kpi.total_idle_hours > 0 and kpi.fuel_idle_l > 0:
        return kpi.fuel_idle_l / kpi.total_idle_hours
    return 0.0


def _vehicle_idle_potential(
    vehicles: list[VehicleMetrics], med_share: float, rate_l_h: float,
    price: float,
) -> list[tuple[str, float]]:
    """Потенциал по ТС: довести холостой ход худших до медианы парка, ₸.

    Честная база сравнения — собственная медиана парка (peer-бенчмарк),
    а не внешние нормативы: одинаковые машины в одинаковых условиях.
    """
    out: list[tuple[str, float]] = []
    if rate_l_h <= 0 or price <= 0:
        return out
    for v in vehicles:
        share = v.idle_hours_share
        if share is None or v.engine_hours is None:
            continue
        if v.engine_hours < config.MIN_HOURS_FOR_IDLE_RANK:   # шум данных
            continue
        if share <= med_share:
            continue
        extra_h = (share - med_share) * v.engine_hours
        kzt = extra_h * rate_l_h * price
        if kzt > 0:
            out.append((v.name, kzt))
    out.sort(key=lambda t: t[1], reverse=True)
    return out


def build_economics(report: FleetReport) -> Economics:
    """Собрать 4 корзины денег по парку. Вызывается после analyze()."""
    kpi = report.kpi
    days = _period_days(report)
    eco = Economics(period_days=days)
    price = kpi.fuel_price_kzt or 0.0

    active = [v for v in report.vehicles if v.has_data]
    idle_shares = [v.idle_hours_share for v in active
                   if v.idle_hours_share is not None]
    med_share = median(idle_shares) if idle_shares else 0.0
    eco.median_idle_share = med_share
    rate_l_h = _idle_fuel_rate_l_per_h(kpi)

    # --- Корзина 1. Топливо: холостой ход -------------------------------------
    # existing — адресуемая часть простоя: непродуктивный (если есть датчики)
    # или IDLE_REDUCIBLE_SHARE от всего idle (практический минимум сокращения).
    if price > 0:
        if kpi.total_unproductive_fuel_cost > 0:
            idle_existing = kpi.total_unproductive_fuel_cost
            idle_est = False
            idle_note = ("Топливо непродуктивного простоя по датчикам/оценке "
                         "погрузки × цена ГСМ.")
        else:
            idle_existing = kpi.idle_fuel_cost * config.IDLE_REDUCIBLE_SHARE
            idle_est = True
            idle_note = (f"{config.IDLE_REDUCIBLE_SHARE:.0%} от стоимости топлива "
                         "без движения — практически сокращаемая часть.")
        worst = _vehicle_idle_potential(active, med_share, rate_l_h, price)
        idle_potential = sum(k for _, k in worst)
        eco.worst_vehicles = worst[:5]
        eco.buckets.append(Bucket(
            key="idle", label="Топливо: холостой ход",
            existing_kzt=idle_existing, potential_kzt=idle_potential,
            is_estimate=idle_est, note=idle_note,
        ))

    # --- Корзина 2. Топливо: перерасход к нормам ------------------------------
    # Только при заданных нормах (инвариант ТЗ §7): без норм корзины нет.
    if kpi.vehicles_with_norm > 0 and kpi.total_overrun_cost > 0:
        eco.buckets.append(Bucket(
            key="overrun", label="Топливо: перерасход к нормам",
            existing_kzt=kpi.total_overrun_cost,
            potential_kzt=kpi.total_overrun_cost,
            is_estimate=False,
            note=(f"Факт сверх утверждённых норм по {kpi.vehicles_over_norm} ТС "
                  "(коэффициенты сезона учтены)."),
        ))

    # --- Корзина 3. Износ и ТО (скрытая стоимость простоя) --------------------
    # Конвенция severe-duty (Cummins): 1 ч холостого хода ≈ IDLE_WEAR_KM_PER_HOUR
    # км эквивалентного износа → ускоренное ТО. Оценка, помечается «≈».
    wear_rate = getattr(config, "MAINT_COST_PER_KM_KZT", 0.0)
    if kpi.total_idle_hours > 0 and wear_rate > 0:
        equiv_km = kpi.total_idle_hours * config.IDLE_WEAR_KM_PER_HOUR
        wear_kzt = equiv_km * wear_rate
        eco.buckets.append(Bucket(
            key="wear", label="Износ и ТО (скрытая цена простоя)",
            existing_kzt=wear_kzt,
            potential_kzt=wear_kzt * config.IDLE_REDUCIBLE_SHARE,
            is_estimate=True,
            note=(f"1 ч холостого хода ≈ {config.IDLE_WEAR_KM_PER_HOUR:.0f} км "
                  f"износа × {wear_rate:.0f} ₸/км на ТО (отраслевая оценка)."),
        ))

    # --- Корзина 4. Вождение и режим (эко-потенциал) --------------------------
    # Отраслевой консервативный эффект эко-вождения ECO_DRIVING_SAVE_SHARE
    # от топлива в движении. Только потенциал, existing не утверждаем.
    eco_share = getattr(config, "ECO_DRIVING_SAVE_SHARE", 0.0)
    if price > 0 and eco_share > 0:
        moving_fuel_cost = max(0.0, kpi.total_fuel_cost - kpi.idle_fuel_cost)
        if moving_fuel_cost > 0:
            eco.buckets.append(Bucket(
                key="driving", label="Вождение и режим (эко-потенциал)",
                existing_kzt=0.0,
                potential_kzt=moving_fuel_cost * eco_share,
                is_estimate=True,
                note=(f"{eco_share:.0%} от топлива в движении — консервативный "
                      "отраслевой эффект программ эко-вождения."),
            ))

    eco.total_existing_kzt = sum(b.existing_kzt for b in eco.buckets)
    eco.total_potential_kzt = sum(b.potential_kzt for b in eco.buckets)
    eco.coi_monthly_kzt = _monthly(eco.total_existing_kzt, days)
    eco.coi_annual_kzt = eco.coi_monthly_kzt * 12.0
    return eco
