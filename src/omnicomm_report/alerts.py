"""Авто-алерты руководителю по итогам отчёта (пороги в config).

Сигналы: перерасход по ТС выше порога ₸, высокая доля холостого хода,
много «тёмных» ТС (нет данных), сбои датчиков. Формулировки нейтральные.
Отправка — через `mailer` (SMTP из ENV), вызывается из CLI/scheduled.
"""

from __future__ import annotations

from . import config, vehicle_types
from .models import FleetReport, VehicleMetrics


def _is_stationary_equipment(v: VehicleMetrics) -> bool:
    """Неподвижная спецтехника (л/моточас): работа двигателя стоя — это норма."""
    if vehicle_types.profile(v.vehicle_type).primary_metric == "l_per_mh":
        return True
    return v.is_stationary


def _alert_idle_share(v: VehicleMetrics):
    """Доля простоя для сигнала или None, если ТС в сигнал не идёт.

    • неподвижную спецтехнику (погрузчик/экскаватор/трактор) пропускаем —
      её работа на месте не является простоем;
    • если есть разбивка погрузки (датчик/обороты) — берём НЕпродуктивный
      простой (вне работы надстройки), а не весь холостой ход;
    • иначе — общий холостой ход без движения.
    Возвращает (доля 0..1, productive_aware: bool) или None.
    """
    if _is_stationary_equipment(v):
        return None
    eng = v.engine_hours or 0.0
    if eng < config.MIN_HOURS_FOR_IDLE_RANK:   # символическая наработка = шум
        return None
    if v.loading_hours is not None and v.unproductive_idle_hours is not None:
        return min(1.0, v.unproductive_idle_hours / eng), True
    if v.idle_hours_share:
        return v.idle_hours_share, False
    return None


def build_alerts(report: FleetReport) -> list[str]:
    """Список алертов по порогам. Пусто — всё в норме."""
    kpi = report.kpi
    out: list[str] = []

    # Перерасход по конкретным ТС выше порога ₸.
    over = sorted(
        (v for v in report.vehicles
         if v.has_data and v.overrun_cost_kzt and v.overrun_cost_kzt >= config.ALERT_OVERRUN_COST_KZT),
        key=lambda v: v.overrun_cost_kzt, reverse=True,
    )
    for v in over:
        out.append(
            f"Перерасход: «{v.name}» +{_money(v.overrun_cost_kzt)} к норме за период "
            f"(+{v.overrun_l:.0f} л) — требует разбора."
        )

    # Высокая доля простоя по ТС (спецтехника исключена; при наличии разбивки —
    # непродуктивный простой вне погрузки, иначе общий холостой ход).
    idle_rows = []
    for v in report.vehicles:
        if not v.has_data:
            continue
        res = _alert_idle_share(v)
        if res and res[0] >= config.ALERT_IDLE_SHARE:
            idle_rows.append((v, res[0], res[1]))
    idle_rows.sort(key=lambda t: t[1], reverse=True)
    for v, share, productive_aware in idle_rows[:10]:
        if productive_aware:
            out.append(
                f"Непродуктивный простой: «{v.name}» {share * 100:.0f}% моточасов "
                f"вне погрузки — проверить режим."
            )
        else:
            out.append(
                f"Холостой ход: «{v.name}» {share * 100:.0f}% моточасов "
                f"двигатель работает стоя — проверить режим."
            )

    # Много «тёмных» ТС по парку.
    no_data = kpi.vehicles_total - kpi.vehicles_with_data
    if kpi.vehicles_total and no_data / kpi.vehicles_total >= config.ALERT_NODATA_SHARE:
        out.append(
            f"Контроль данных: {no_data} из {kpi.vehicles_total} ТС без данных за период "
            f"— проверить терминалы/датчики."
        )
    return out


def _money(value: float) -> str:
    return f"{value:,.0f} ₸".replace(",", " ")


def send_alerts(report: FleetReport, to: str) -> bool:
    """Отправить алерты на e-mail (если есть что и SMTP настроен)."""
    if not report.alerts:
        return False
    from . import mailer
    subject = f"⚠️ Автопарк «{report.client_name}»: {len(report.alerts)} сигналов за {report.period.human()}"
    body = "Автоматические сигналы по автопарку:\n\n" + "\n".join(
        f"• {a}" for a in report.alerts)
    return mailer.send_report(to, subject, body, attachments=[])
