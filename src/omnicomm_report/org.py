"""Holding-слой: справочник организаций (`dim_org`) и row-level доступ.

Платформа обслуживает холдинг, а не одного клиента. Организации образуют
иерархию:

    Холдинг (КАП) → ДЗО (×23) → под-ДЗО → подрядная организация → … → ТС

Так как все данные приходят с ОДНОГО аккаунта Omnicomm, иерархию берём прямо
из дерева ТС Omnicomm (`GET /ls/api/v2/tree/vehicle`): каждый узел дерева
(`{id, name, objects[], children[]}`) — это организация, вложенность даёт
parent-child, а ТС из `objects[]` привязываются к своему узлу.

КОНТРОЛЬ ДОСТУПА (см. docs/holding-architecture.md §8) — конфиденциальность
между ДЗО:
  • каждый пользователь привязан к узлу `dim_org`;
  • видит свой узел + всё поддерево ниже (subtree);
  • поэтому ДЗО видит свои под-ДЗО и подрядчиков, но НЕ видит соседей;
  • руководитель холдинга привязан к корню → видит весь КАП.

Изоляция «соседи не видят друг друга» получается автоматически из subtree-логики
— одно правило на все типы подчинённых организаций.

Модуль — чистая доменная логика + лёгкая JSON-персистентность (как `clients.py`),
без зависимости от БД и от боевого аккаунта. Когда выберем хранилище (SQLite/
Postgres, §10.9), `load_org_registry`/`save_org_registry` меняются точечно.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Optional


class OrgLevel(str, Enum):
    """Уровень организации в иерархии холдинга."""

    HOLDING = "holding"        # корень — весь холдинг (КАП)
    DZO = "dzo"                # дочернее зависимое общество (1-й уровень)
    SUB_DZO = "sub_dzo"        # под-ДЗО (Уранэнерго → ТФО/ШФО; УМЗ → УМЗ Курчатов)
    CONTRACTOR = "contractor"  # подрядная организация
    UNKNOWN = "unknown"


class OrgType(str, Enum):
    """Тип владения: собственная организация холдинга или подрядчик."""

    OWN = "own"
    CONTRACTOR = "contractor"


@dataclass
class Org:
    """Узел справочника организаций `dim_org`."""

    org_id: str
    name: str
    parent_id: Optional[str] = None        # None → корень
    level: OrgLevel = OrgLevel.UNKNOWN
    type: OrgType = OrgType.OWN

    def to_dict(self) -> dict:
        return {
            "org_id": self.org_id,
            "name": self.name,
            "parent_id": self.parent_id,
            "level": self.level.value,
            "type": self.type.value,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Org":
        return cls(
            org_id=str(d["org_id"]),
            name=str(d.get("name") or d["org_id"]),
            parent_id=(str(d["parent_id"]) if d.get("parent_id") else None),
            level=OrgLevel(d.get("level", "unknown")),
            type=OrgType(d.get("type", "own")),
        )


# Глубина от корня → уровень. Глубже SUB_DZO не различаем по структуре —
# подрядчиков помечаем явно (apply_contractor_tags), их из дерева не вывести.
_DEPTH_LEVELS = [OrgLevel.HOLDING, OrgLevel.DZO, OrgLevel.SUB_DZO]


class OrgTree:
    """Иерархия организаций с операциями доступа по поддереву.

    Строится из списка `Org`. Все запросы доступа сводятся к «узел + поддерево».
    """

    def __init__(self, orgs: Iterable[Org]):
        self._orgs: dict[str, Org] = {}
        self._children: dict[str, list[str]] = {}
        for org in orgs:
            self.add(org)

    # --- построение -----------------------------------------------------------

    def add(self, org: Org) -> None:
        self._orgs[org.org_id] = org
        self._children.setdefault(org.org_id, [])
        if org.parent_id:
            self._children.setdefault(org.parent_id, [])
            if org.org_id not in self._children[org.parent_id]:
                self._children[org.parent_id].append(org.org_id)

    # --- навигация ------------------------------------------------------------

    def get(self, org_id: str) -> Optional[Org]:
        return self._orgs.get(org_id)

    def exists(self, org_id: str) -> bool:
        return org_id in self._orgs

    def children(self, org_id: str) -> list[Org]:
        return [self._orgs[c] for c in self._children.get(org_id, []) if c in self._orgs]

    def roots(self) -> list[Org]:
        return [o for o in self._orgs.values()
                if not o.parent_id or o.parent_id not in self._orgs]

    def ancestors(self, org_id: str) -> list[Org]:
        """Цепочка родителей от прямого родителя до корня (без самого узла)."""
        chain: list[Org] = []
        seen: set[str] = {org_id}
        cur = self._orgs.get(org_id)
        while cur and cur.parent_id and cur.parent_id not in seen:
            seen.add(cur.parent_id)
            parent = self._orgs.get(cur.parent_id)
            if not parent:
                break
            chain.append(parent)
            cur = parent
        return chain

    def subtree_ids(self, org_id: str) -> set[str]:
        """org_id + все потомки (BFS). Защита от циклов через `seen`."""
        if org_id not in self._orgs:
            return set()
        seen: set[str] = set()
        stack = [org_id]
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            stack.extend(self._children.get(cur, []))
        return seen

    # --- доступ (row-level) ---------------------------------------------------

    def visible_org_ids(self, viewer_org_id: str) -> set[str]:
        """Множество организаций, видимых пользователю узла viewer = его поддерево."""
        return self.subtree_ids(viewer_org_id)

    def can_view(self, viewer_org_id: str, target_org_id: str) -> bool:
        """Видит ли viewer организацию target: target в поддереве viewer."""
        return target_org_id in self.subtree_ids(viewer_org_id)

    # --- сериализация ---------------------------------------------------------

    def to_list(self) -> list[dict]:
        return [o.to_dict() for o in self._orgs.values()]

    def __len__(self) -> int:
        return len(self._orgs)


# --- Построение из дерева Omnicomm -------------------------------------------

def build_from_omnicomm_tree(
    nodes: list[dict],
    *,
    root_id: str = "holding",
    root_name: str = "КАП",
) -> tuple[OrgTree, dict[str, str]]:
    """Построить `OrgTree` + маппинг ТС→org_id из дерева ТС Omnicomm.

    Узел: `{id, name, objects:[ТС...], children:[узлы...]}`. Создаётся
    синтетический корень-холдинг (`root_id`), под него подвешиваются все
    верхнеуровневые узлы аккаунта — так у руководителя холдинга один корень,
    видящий всё. Уровень проставляется по глубине; подрядчиков пометить
    отдельно через `apply_contractor_tags` (из структуры их не вывести).

    Возвращает `(tree, vehicle_org)`, где `vehicle_org[vehicle_id] = org_id`.
    """
    orgs: list[Org] = [Org(org_id=root_id, name=root_name, parent_id=None,
                           level=OrgLevel.HOLDING, type=OrgType.OWN)]
    vehicle_org: dict[str, str] = {}

    def level_for(depth: int) -> OrgLevel:
        if depth < len(_DEPTH_LEVELS):
            return _DEPTH_LEVELS[depth]
        return OrgLevel.SUB_DZO

    def walk(node: dict, parent_id: str, depth: int) -> None:
        nid = str(node.get("id") or node.get("uuid") or "").strip()
        if not nid:
            return
        name = str(node.get("name") or nid).strip()
        orgs.append(Org(org_id=nid, name=name, parent_id=parent_id,
                        level=level_for(depth), type=OrgType.OWN))
        for obj in node.get("objects") or []:
            if not isinstance(obj, dict):
                continue
            vid = str(obj.get("uuid") or obj.get("id") or obj.get("terminal_id") or "").strip()
            if vid:
                vehicle_org[vid] = nid
        for child in node.get("children") or []:
            if isinstance(child, dict):
                walk(child, nid, depth + 1)

    for root in nodes or []:
        if isinstance(root, dict):
            walk(root, root_id, 1)  # верхний узел аккаунта = ДЗО (глубина 1)

    return OrgTree(orgs), vehicle_org


def apply_contractor_tags(tree: OrgTree, contractor_org_ids: Iterable[str]) -> None:
    """Пометить указанные узлы как подрядчиков (`type=CONTRACTOR`, `level=CONTRACTOR`).

    Подрядчики структурно не отличаются от под-ДЗО — их задаёт заказчик/оператор
    (см. §10.5). Видимость при этом не меняется: узел остаётся в поддереве своей
    ДЗО, значит ДЗО продолжает его видеть.
    """
    for oid in contractor_org_ids:
        org = tree.get(oid)
        if org:
            org.type = OrgType.CONTRACTOR
            org.level = OrgLevel.CONTRACTOR


# --- Применение доступа к ТС --------------------------------------------------

def filter_vehicles_for_viewer(
    vehicles: list,
    viewer_org_id: str,
    tree: OrgTree,
    vehicle_org: Optional[dict[str, str]] = None,
) -> list:
    """Оставить только ТС, видимые пользователю узла `viewer_org_id`.

    org_id ТС берётся из `vehicle.org_id`, иначе из `vehicle_org[vehicle_id]`.
    ТС без привязки к организации НЕ показываются (fail-closed — конфиденциальность
    важнее полноты: непривязанный ТС не утечёт чужому ДЗО).
    """
    visible = tree.visible_org_ids(viewer_org_id)
    vehicle_org = vehicle_org or {}
    out = []
    for v in vehicles:
        oid = getattr(v, "org_id", None) or vehicle_org.get(getattr(v, "vehicle_id", None))
        if oid and oid in visible:
            out.append(v)
    return out


# --- Персистентность (JSON, как clients.py) ----------------------------------

DEFAULT_ORG_REGISTRY = os.path.join("data", "org_registry.json")


@dataclass
class OrgRegistry:
    """Снимок справочника организаций + маппинга ТС→организация."""

    tree: OrgTree
    vehicle_org: dict[str, str] = field(default_factory=dict)


def save_org_registry(registry: OrgRegistry, path: str = DEFAULT_ORG_REGISTRY) -> str:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    payload = {
        "orgs": registry.tree.to_list(),
        "vehicle_org": registry.vehicle_org,
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
    return path


def load_org_registry(path: str = DEFAULT_ORG_REGISTRY) -> Optional[OrgRegistry]:
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    tree = OrgTree(Org.from_dict(d) for d in data.get("orgs", []))
    vehicle_org = {str(k): str(v) for k, v in (data.get("vehicle_org") or {}).items()}
    return OrgRegistry(tree=tree, vehicle_org=vehicle_org)
