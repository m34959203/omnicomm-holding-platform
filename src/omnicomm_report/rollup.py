"""Роллапы KPI по иерархии организаций (holding-слой).

Для каждого узла `dim_org` считаем `FleetKPI` по **всем ТС его поддерева**:
ДЗО агрегирует свои под-ДЗО (которых может быть несколько) и подрядчиков,
корень-холдинг — весь КАП. Срез на любое ДЗО получается выбором его узла.

ВАЖНО: KPI считается **из полного списка ТС поддерева**, а не суммированием
детских KPI. Взвешенные средние (л/100км, л/моточас), классификации (мобильные/
спецтехника) и «лидеры» нельзя корректно сложить из агрегатов — поэтому на каждом
узле переиспользуем `analytics.compute_kpi` на собранном списке ТС. Это медленнее,
но единственно верно (крупные ТС не теряются в усреднении).

Объём (≈1400 ТС × ~30 узлов) для прямого пересчёта незначителен.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .analytics import compute_kpi
from .models import FleetKPI
from .org import Org, OrgTree


@dataclass
class OrgKPI:
    """KPI одного узла иерархии + ссылки на дочерние узлы (дерево результатов)."""

    org: Org
    kpi: FleetKPI
    vehicle_count: int                 # ТС в поддереве (всего привязанных)
    direct_vehicle_count: int          # ТС, привязанных прямо к этому узлу
    children: list["OrgKPI"] = field(default_factory=list)


def _direct_groups(vehicles: list, vehicle_org: dict[str, str]) -> dict[str, list]:
    """Сгруппировать ТС по их прямому org_id (из `v.org_id` или маппинга)."""
    groups: dict[str, list] = {}
    for v in vehicles:
        oid = getattr(v, "org_id", None) or vehicle_org.get(getattr(v, "vehicle_id", None))
        if oid:
            groups.setdefault(oid, []).append(v)
    return groups


def _subtree_vehicles(org_id: str, tree: OrgTree, direct: dict[str, list]) -> list:
    """Все ТС поддерева узла (объединение прямых ТС всех потомков + самого узла)."""
    out: list = []
    for oid in tree.subtree_ids(org_id):
        out.extend(direct.get(oid, []))
    return out


def rollup_kpi(
    vehicles: list,
    tree: OrgTree,
    *,
    fuel_price_kzt: float = 0.0,
    vehicle_org: Optional[dict[str, str]] = None,
) -> dict[str, FleetKPI]:
    """KPI на каждый узел иерархии: `{org_id: FleetKPI}` по ТС поддерева узла."""
    direct = _direct_groups(vehicles, vehicle_org or {})
    return {
        org_id: compute_kpi(_subtree_vehicles(org_id, tree, direct), fuel_price_kzt)
        for org_id in tree.org_ids()
    }


def build_org_kpi_tree(
    vehicles: list,
    tree: OrgTree,
    *,
    fuel_price_kzt: float = 0.0,
    vehicle_org: Optional[dict[str, str]] = None,
) -> list[OrgKPI]:
    """Дерево `OrgKPI` от корней — готово к отрисовке дашборда/отчёта по уровням.

    Каждый узел несёт свой роллап-KPI, число ТС поддерева и прямых ТС, и детей.
    """
    direct = _direct_groups(vehicles, vehicle_org or {})

    def build(org_id: str) -> OrgKPI:
        subtree_ids = tree.subtree_ids(org_id)
        vcount = sum(len(direct.get(oid, [])) for oid in subtree_ids)
        kpi = compute_kpi(_subtree_vehicles(org_id, tree, direct), fuel_price_kzt)
        return OrgKPI(
            org=tree.get(org_id),
            kpi=kpi,
            vehicle_count=vcount,
            direct_vehicle_count=len(direct.get(org_id, [])),
            children=[build(c.org_id) for c in tree.children(org_id)],
        )

    return [build(r.org_id) for r in tree.roots()]
