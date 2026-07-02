"""Сборка секции «Учёт шин по пробегу» в снапшот (родственно `api/health.py` ТО).

Пробег комплекта копится с даты установки из ГОДОВОГО архива `raw_store`
(в отличие от ТО, что считает за окно снапшота). План/стоимость/цикл — из
персистентного стора `tyre_store`; нет строки → дефолт по классу ТС «от нуля».
"""

from __future__ import annotations

from typing import Iterable, Optional

from omnicomm_report import config, tyres

from . import raw_store, tyre_store

# Тяжёлая техника (самосвалы/спецтехника) — ресурс шин ниже, комплект дороже.
_HEAVY_HINTS = (
    "самосвал", "карьер", "белаз", "howo", "shacman", "камаз", "краз",
    "урал", "автокран", "кран", "бульдозер", "погрузчик", "экскаватор",
    "тягач", "миксер", "автобетон", "трал",
)


def _is_stationary(v) -> bool:
    eh = getattr(v, "engine_hours", None) or 0
    km = getattr(v, "mileage_km", None) or 0
    if eh <= 0:
        return False
    return (km / eh) < config.STATIONARY_KM_PER_HOUR


def _is_heavy(v) -> bool:
    name = (getattr(v, "name", "") or "").lower()
    return any(h in name for h in _HEAVY_HINTS)


def _defaults_for(v) -> tuple[float, float, float]:
    """(resource_km, cost_kzt, remind_before_km) по классу ТС."""
    if _is_heavy(v):
        return (config.TYRE_RESOURCE_KM_HEAVY, config.TYRE_SET_COST_KZT_HEAVY,
                config.TYRE_REMIND_BEFORE_KM)
    return (config.TYRE_RESOURCE_KM_DEFAULT, config.TYRE_SET_COST_KZT_DEFAULT,
            config.TYRE_REMIND_BEFORE_KM)


def _status_dict(st: tyres.TyreStatus, name: Optional[str], plan: tyres.TyrePlan) -> dict:
    return {
        "terminal_id": st.terminal_id, "name": name, "status": st.status,
        "km_since": st.km_since, "km_left": st.km_left, "worn_share": st.worn_share,
        "wear_kzt": st.wear_kzt, "resource_km": st.resource_km,
        "cost_kzt": plan.cost_kzt, "installed_ts": st.installed_ts,
        "brand": plan.brand, "size": plan.size, "reason": st.reason,
    }


def _summarize(statuses, name_map, plans) -> dict:
    counts: dict[str, int] = {}
    wear_total = 0.0
    for st in statuses:
        counts[st.status] = counts.get(st.status, 0) + 1
        wear_total += st.wear_kzt or 0.0
    items = [_status_dict(s, name_map.get(s.terminal_id), plans[s.terminal_id])
             for s in statuses]
    return {
        "counts": counts, "items": items,
        "wear_kzt_total": round(wear_total, 0),
        "note": "пробег комплекта копится с даты установки из архива; замена "
                "подтверждается вручную и сбрасывает цикл",
    }


def build_tyres(vehicles, *, now_ts: int, raw_path: str = raw_store.DEFAULT_PATH,
                store_path: str = tyre_store.DEFAULT_PATH) -> dict:
    """Статусы комплектов шин парка: пробег с установки из архива + износ ₸."""
    store = tyre_store.get_all(store_path)
    total_km = raw_store.total_mileage_by_terminal(now_ts, raw_path)

    plans: dict[str, tyres.TyrePlan] = {}
    states: dict[str, tyres.TyreState] = {}
    km_since: dict[str, float] = {}
    for v in vehicles:
        if _is_stationary(v):
            continue  # стационарная/спецтехника без дорожного пробега — не считаем шины
        tid = str(v.vehicle_id)
        res, cost, remind = _defaults_for(v)
        plan, state = tyre_store.plan_state_for(
            store.get(tid), terminal_id=tid, resource_km=res, cost_kzt=cost,
            remind_before_km=remind)
        plans[tid] = plan
        states[tid] = state
        km_full = total_km.get(tid, 0.0)
        if state.installed_ts:
            km_full -= raw_store.mileage_before(tid, state.installed_ts, raw_path)
        km_since[tid] = max(0.0, km_full)

    statuses = tyres.fleet_status(plans, states, km_since)
    name_map = {str(v.vehicle_id): v.name for v in vehicles}
    return _summarize(statuses, name_map, plans)


def build_tyres_demo(vehicles) -> dict:
    """Демо: пробег комплекта = mileage_km × детерминированный фактор (светофор шин)."""
    plans, states, km_since = {}, {}, {}
    for v in vehicles:
        if _is_stationary(v):
            continue
        tid = str(v.vehicle_id)
        res, cost, remind = _defaults_for(v)
        plans[tid] = tyres.TyrePlan(terminal_id=tid, resource_km=res, cost_kzt=cost,
                                    remind_before_km=remind)
        states[tid] = tyres.TyreState(terminal_id=tid)
        factor = 1 + (abs(hash(tid)) % 100) / 3.0    # часть парка у ресурса/за ним
        km_since[tid] = (getattr(v, "mileage_km", 0) or 0) * factor
    statuses = tyres.fleet_status(plans, states, km_since)
    name_map = {str(v.vehicle_id): v.name for v in vehicles}
    return _summarize(statuses, name_map, plans)
