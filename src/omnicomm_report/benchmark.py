"""Обезличенный бенчмаркинг между клиентами (преимущество мультитенанта).

Берёт последние снапшоты KPI всех клиентов из истории (`history`), считает
средние по парку метрики и сравнивает текущего клиента. Имена других клиентов
не раскрываются — только агрегат «среднее по N паркам».
"""

from __future__ import annotations

import json
import os
from typing import Optional

from . import config
from .history import DEFAULT_HISTORY_DIR, _slug
from .models import FleetKPI

# Правдоподобный диапазон средневзвешенного расхода парка, л/100 км
# (для отсева несопоставимых снапшотов в бенчмарке). (Cowork-ревью)
PLAUSIBLE_FUEL_100_MIN = 5.0
PLAUSIBLE_FUEL_100_MAX = 150.0

# Метрики для сравнения: ключ → (подпись, «меньше=лучше»).
_METRICS = {
    "weighted_fuel_per_100km": ("Средний расход, л/100км", True),
    "idle_hours_share": ("Доля холостого хода", True),
    "fleet_loading_utilization": ("Доля полезной работы стоя", False),
}


def _latest_per_client(history_dir: str) -> dict[str, dict]:
    """Последний снапшот KPI каждого клиента: {slug: kpi_dict}."""
    if not os.path.isdir(history_dir):
        return {}
    best: dict[str, tuple[int, dict]] = {}
    for fn in os.listdir(history_dir):
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(history_dir, fn), encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        slug = fn.split("__")[0]
        end = int(data.get("period_end", 0))
        if slug not in best or end > best[slug][0]:
            best[slug] = (end, data.get("kpi", {}))
    return {s: kpi for s, (_, kpi) in best.items()}


def compute(client_name: str, kpi: FleetKPI,
            history_dir: str = DEFAULT_HISTORY_DIR) -> dict:
    """Сравнить клиента со средним по ДРУГИМ клиентам. {} если других нет."""
    snaps = _latest_per_client(history_dir)
    me = _slug(client_name)
    others = [k for s, k in snaps.items() if s != me]
    # «Среднее по паркам» имеет смысл лишь при достаточном числе ДРУГИХ реальных
    # клиентов: один-два чужих снапшота (или оставшиеся демо-прогоны) — это не
    # «среднее по отрасли», а шум, вводящий руководителя в заблуждение.
    if len(others) < config.MIN_BENCHMARK_PEERS:
        return {}
    result: dict[str, dict] = {"peers": len(others), "metrics": {}}
    for key, (label, less_better) in _METRICS.items():
        vals = [float(o.get(key, 0) or 0) for o in others if o.get(key)]
        # л/100 км несопоставим между парками с разным составом техники:
        # отсекаем неправдоподобные значения (парк из спецтехники даёт сотни
        # л/100 км), иначе сравнение «у вас 63.9, в среднем 415 — лучше»
        # вводит руководителя в заблуждение. (Cowork-ревью)
        if key == "weighted_fuel_per_100km":
            vals = [v for v in vals if PLAUSIBLE_FUEL_100_MIN <= v <= PLAUSIBLE_FUEL_100_MAX]
        if not vals:
            continue
        avg = sum(vals) / len(vals)
        mine = float(getattr(kpi, key, 0) or 0)
        better = (mine < avg) if less_better else (mine > avg)
        result["metrics"][key] = {
            "label": label, "mine": round(mine, 3),
            "peers_avg": round(avg, 3), "better": better,
        }
    return result


def latest_kpi(client_name: str, history_dir: str = DEFAULT_HISTORY_DIR) -> Optional[dict]:
    """Последний снапшот KPI конкретного клиента (для отладки)."""
    return _latest_per_client(history_dir).get(_slug(client_name))
