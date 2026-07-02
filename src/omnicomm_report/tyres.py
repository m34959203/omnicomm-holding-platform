"""Учёт автошин по пробегу (docs/knowledge-base/11 — родственно Контролю ТО).

Механика — зеркало `maintenance.py`, но:
- ресурс комплекта в **км** (шина отхаживает ~50–80 тыс. км), не 15 тыс. как ТО;
- пробег комплекта копится **с даты установки** (`installed_ts`), а не за окно
  снапшота → сумма берётся из ГОДОВОГО архива `raw_store.fact_daily`;
- «замена комплекта» подтверждается пользователем → новый цикл от даты замены
  (сброс пробега), как `confirm_to`;
- **износ в ₸**: доля отхоженного ресурса × стоимость комплекта (фирменный
  «перевод в деньги» платформы); досрочная замена = потери.

Гранулярность MVP — **комплект на ТС** (позиции/оси и ротация — фаза 2).
Идемпотентность: пробег = SUM(факт mileage) с `installed_ts`, не инкремент.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional


@dataclass
class TyrePlan:
    """Норматив комплекта шин на ТС."""
    terminal_id: str
    resource_km: float                       # ресурс комплекта, км
    cost_kzt: float = 0.0                     # стоимость комплекта, ₸
    remind_before_km: float = 3000.0          # заблаговременный алерт, км
    brand: Optional[str] = None               # опц. метаданные комплекта
    size: Optional[str] = None


@dataclass
class TyreState:
    """Текущий цикл комплекта: установлен когда."""
    terminal_id: str
    installed_ts: Optional[int] = None        # начало текущего цикла (epoch сек)
    last_change_at: Optional[int] = None      # когда подтверждена последняя замена


@dataclass
class TyreStatus:
    terminal_id: str
    status: str                               # ok | приближается | пора менять | просрочено
    km_since: float                           # отхожено комплектом с установки
    km_left: Optional[float]                  # до ресурса (может быть отрицательным)
    worn_share: float                         # доля отхоженного ресурса 0..1+
    wear_kzt: float                            # износ в ₸ (доля × стоимость, кап по стоимости)
    resource_km: float
    installed_ts: Optional[int]
    reason: str


def confirm_change(state: TyreState, at_ts: int) -> TyreState:
    """Подтверждение «шины заменены» — новый цикл от даты замены (сброс пробега)."""
    return TyreState(terminal_id=state.terminal_id, installed_ts=at_ts, last_change_at=at_ts)


def evaluate(plan: TyrePlan, km_since: float) -> TyreStatus:
    """Статус комплекта по отхоженному пробегу + износ в ₸."""
    resource = plan.resource_km or 0.0
    km_left = (resource - km_since) if resource > 0 else None
    worn_share = (km_since / resource) if resource > 0 else 0.0
    # износ ₸ — доля ресурса × стоимость, но не больше стоимости комплекта
    wear_kzt = round(min(worn_share, 1.0) * (plan.cost_kzt or 0.0), 0)

    status, reason = "ok", "ресурс шин в норме"
    if km_left is not None and km_left <= 0:
        status = "просрочено"
        reason = f"перепробег {round(-km_left)} км сверх ресурса — замена просрочена"
    elif km_left is not None and km_left <= plan.remind_before_km:
        status = "пора менять"
        reason = f"осталось {round(km_left)} км до ресурса"
    elif worn_share >= 0.8:
        status = "приближается"
        reason = f"отхожено {round(worn_share * 100)}% ресурса"
    return TyreStatus(
        terminal_id=plan.terminal_id, status=status,
        km_since=round(km_since, 1),
        km_left=(round(km_left, 1) if km_left is not None else None),
        worn_share=round(worn_share, 3), wear_kzt=wear_kzt,
        resource_km=resource, installed_ts=None, reason=reason,
    )


def fleet_status(
    plans: dict, states: dict, km_since_by_terminal: dict
) -> list[TyreStatus]:
    """Статусы комплектов по парку.

    `plans`/`states`: {tid -> TyrePlan/TyreState}; `km_since_by_terminal`: {tid -> км}
    (уже посчитанный пробег с `installed_ts`, из архива — см. `api/tyres.py`).
    """
    out: list[TyreStatus] = []
    for tid, plan in plans.items():
        km = km_since_by_terminal.get(tid, 0.0)
        st = evaluate(plan, km)
        state = states.get(tid)
        if state is not None:
            st.installed_ts = state.installed_ts
        out.append(st)
    rank = {"просрочено": 3, "пора менять": 2, "приближается": 1, "ok": 0}
    out.sort(key=lambda s: (rank.get(s.status, 0), s.wear_kzt), reverse=True)
    return out
