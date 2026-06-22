"""Контроль планового ТО (docs/knowledge-base/11).

Наработка считается «от нуля» (T0 = подключение/последнее ТО) по моточасам и/или
пробегу из фида Omnicomm. Алерт заблаговременно; подтверждение «ТО пройдено»
сбрасывает цикл.

Идемпотентность (по аудиту): наработка = **SUM(факт) с момента T0**, а не
инкрементальный счётчик — повторные прогоны и пересчёты Omnicomm самокорректируются.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional


@dataclass
class MaintenancePlan:
    terminal_id: str
    interval_mh: Optional[float] = None      # интервал ТО по моточасам
    interval_km: Optional[float] = None      # интервал ТО по пробегу
    remind_before_mh: float = 20.0
    remind_before_km: float = 500.0


@dataclass
class MaintenanceState:
    terminal_id: str
    t0: Optional[int] = None                 # начало текущего цикла (epoch сек)
    last_to_at: Optional[int] = None         # когда подтверждено последнее ТО


@dataclass
class MaintenanceStatus:
    terminal_id: str
    status: str                              # ok | приближается | ожидается | просрочено
    mh_since: float
    km_since: float
    mh_left: Optional[float]
    km_left: Optional[float]
    reason: str


def compute_since(records: Iterable[dict], since_ts: Optional[int]) -> tuple[float, float]:
    """Суммарная наработка (моточасы, км) из суточных записей с `date >= since_ts`.

    `records`: [{date, worked_sec, mileage_km}]. SUM, не инкремент → идемпотентно.
    """
    mh = km = 0.0
    for r in records or []:
        if since_ts is not None and (r.get("date") or 0) < since_ts:
            continue
        mh += (r.get("worked_sec") or 0) / 3600.0
        km += r.get("mileage_km") or 0.0
    return round(mh, 1), round(km, 1)


def from_consolidated(rows: Iterable[dict]) -> dict[str, list[dict]]:
    """Суточные записи наработки по ТС из сводных строк: {terminal_id -> [{date,worked_sec,mileage_km}]}."""
    out: dict[str, list[dict]] = {}
    for row in rows or []:
        cr = row.get("consolidatedReport") if isinstance(row.get("consolidatedReport"), dict) else row
        tid = cr.get("vehicleId") or cr.get("id")
        if tid is None:
            continue
        mv = cr.get("mv") or {}
        out.setdefault(str(tid), []).append({
            "date": cr.get("date"),
            "worked_sec": mv.get("worked") or 0,
            "mileage_km": mv.get("mileage") or 0.0,
        })
    return out


def evaluate(plan: MaintenancePlan, mh_since: float, km_since: float) -> MaintenanceStatus:
    """Статус ТО по накопленной наработке. Берём более срочное из (моточасы, пробег)."""
    mh_left = (plan.interval_mh - mh_since) if plan.interval_mh else None
    km_left = (plan.interval_km - km_since) if plan.interval_km else None

    status, reason = "ok", "наработка в норме"
    # просрочено — наработка превысила интервал
    if (mh_left is not None and mh_left <= 0) or (km_left is not None and km_left <= 0):
        status = "просрочено"
        reason = "наработка превысила интервал ТО"
    # ожидается — почти достигнут (в пределах напоминания)
    elif (mh_left is not None and mh_left <= plan.remind_before_mh) or \
         (km_left is not None and km_left <= plan.remind_before_km):
        status = "ожидается"
        bits = []
        if mh_left is not None and mh_left <= plan.remind_before_mh:
            bits.append(f"осталось {round(mh_left, 1)} моточасов")
        if km_left is not None and km_left <= plan.remind_before_km:
            bits.append(f"осталось {round(km_left, 1)} км")
        reason = "приближается ТО: " + ", ".join(bits)
    return MaintenanceStatus(
        terminal_id=plan.terminal_id, status=status,
        mh_since=mh_since, km_since=km_since,
        mh_left=(round(mh_left, 1) if mh_left is not None else None),
        km_left=(round(km_left, 1) if km_left is not None else None),
        reason=reason,
    )


def confirm_to(state: MaintenanceState, at_ts: int) -> MaintenanceState:
    """Подтверждение «ТО пройдено» — новый цикл от даты подтверждения (сброс наработки)."""
    return MaintenanceState(terminal_id=state.terminal_id, t0=at_ts, last_to_at=at_ts)


def fleet_status(plans: dict, states: dict, records_by_terminal: dict) -> list[MaintenanceStatus]:
    """Статусы ТО по парку. `plans`/`states`: {tid -> MaintenancePlan/MaintenanceState}."""
    out = []
    for tid, plan in plans.items():
        st = states.get(tid)
        since = st.t0 if st else None
        mh, km = compute_since(records_by_terminal.get(tid, []), since)
        out.append(evaluate(plan, mh, km))
    rank = {"просрочено": 3, "ожидается": 2, "приближается": 1, "ok": 0}
    out.sort(key=lambda s: rank.get(s.status, 0), reverse=True)
    return out
