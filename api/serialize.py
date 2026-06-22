"""Сериализация объектов движков в JSON-словари для фронта.

Движки отдают dataclass'ы (FleetKPI, OrgKPI, Economics, Recommendation) —
`dataclasses.asdict` разворачивает их рекурсивно. Здесь — тонкие адаптеры,
которые задают форму контракта API (что именно видит Next.js).
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from omnicomm_report import geomap


def kpi_node(node: Any) -> dict:
    """`OrgKPI` → словарь узла дерева организаций с KPI и детьми (рекурсивно)."""
    return {
        "org_id": node.org.org_id,
        "name": node.org.name,
        "parent_id": getattr(node.org, "parent_id", None),
        "level": getattr(getattr(node.org, "level", None), "value",
                          getattr(node.org, "level", None)),
        "type": getattr(node.org, "type", None),
        "vehicle_count": node.vehicle_count,
        "direct_vehicle_count": node.direct_vehicle_count,
        "kpi": asdict(node.kpi),
        "children": [kpi_node(c) for c in node.children],
    }


def kpi_tree(nodes: list) -> list[dict]:
    return [kpi_node(n) for n in nodes]


def economics_dict(eco: Any) -> dict:
    """`Economics` → словарь (корзины денег, COI, худшие ТС)."""
    return asdict(eco)


def recommendation_dict(rec: Any) -> dict:
    """`Recommendation` (скоростной режим СТ КАП) → словарь + готовый текст."""
    d = asdict(rec)
    text = getattr(rec, "as_text", None)
    d["text"] = text() if callable(text) else ""
    return d


def geozone_features_json(raw_geozones: Any) -> list[dict]:
    """Геозоны → лёгкие фичи для карты (путь, цвет, тип, лимит)."""
    feats = geomap.geozone_features(raw_geozones)
    return [{
        "name": f.name, "kind": f.kind, "path": f.path,
        "color": list(f.color), "limit": f.limit, "width": f.width,
        "tooltip": f.tooltip,
    } for f in feats]
