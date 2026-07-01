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


def _is_group_slice(name: str) -> bool:
    """Узел-«срез» Omnicomm (сохранённое представление), а не реальная организация.

    В аккаунте КАП такие узлы названы в слэшах — напр. `/Безопасное вождение/` —
    и переспис­ывают уже существующие ДЗО (те же организации, но под НОВЫМИ
    org_id). Это фантомная папка-представление: её поддерево = ДУБЛИ каноничных
    узлов → в роллап холдинга попадает ДВОЙНОЙ счёт ТС. Такие узлы выкидываем из
    `dim_org`, а их ТС переносим на каноничных двойников по имени (см.
    `build_from_omnicomm_tree`), чтобы не потерять ТС, которые Omnicomm положил
    только в срез.
    """
    n = (name or "").strip()
    return len(n) >= 2 and n.startswith("/") and n.endswith("/")


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

    def org_ids(self) -> list[str]:
        return list(self._orgs.keys())

    def all_orgs(self) -> list[Org]:
        return list(self._orgs.values())

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

    def visible_scope(self, viewer_org_id: Optional[str], *,
                      all_access: bool = False) -> set[str]:
        """Множество org_id, доступных пользователю.

        `all_access=True` (роль admin / руководитель холдинга) → весь справочник;
        иначе — поддерево его узла. Без узла и без all_access — пусто (fail-closed).
        """
        if all_access:
            return set(self.org_ids())
        if not viewer_org_id:
            return set()
        return self.subtree_ids(viewer_org_id)

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

    Узлы-«срезы» Omnicomm (сохранённые представления, имя в слэшах — напр.
    `/Безопасное вождение/`) выкидываются: их поддерево — это ДУБЛИ уже
    существующих ДЗО под новыми org_id, из-за чего в роллап холдинга попадал
    двойной счёт ТС. ТС такого поддерева переносятся на каноничного двойника по
    имени, а реальный (не-срезовый) узел всегда перебивает срезовую привязку —
    так не теряется ни один ТС, который Omnicomm положил только в срез.
    """
    def level_for(depth: int) -> OrgLevel:
        if depth < len(_DEPTH_LEVELS):
            return _DEPTH_LEVELS[depth]
        return OrgLevel.SUB_DZO

    # 1-й проход: собрать все узлы дерева (без сборки dim_org) + пометить,
    # какие лежат в поддереве узла-среза.
    @dataclass
    class _Node:
        nid: str
        name: str
        parent_id: str
        depth: int
        vids: list[str]
        in_slice: bool  # сам узел или любой предок — срез

    collected: list[_Node] = []

    def walk(node: dict, parent_id: str, depth: int, under_slice: bool) -> None:
        nid = str(node.get("id") or node.get("uuid") or "").strip()
        if not nid:
            return
        name = str(node.get("name") or nid).strip()
        is_slice = under_slice or _is_group_slice(name)
        vids: list[str] = []
        for obj in node.get("objects") or []:
            if not isinstance(obj, dict):
                continue
            # Ключ ТС должен совпадать с identity в метриках: data_loader заполняет
            # VehicleMetrics.vehicle_id из vehicleId отчёта (= terminal_id), и name_map
            # тоже ключуется terminal_id→id→uuid. Тот же порядок здесь, иначе
            # assign_org_ids не найдёт ТС (баг: реестр по uuid, метрики по terminal_id).
            vid = str(obj.get("terminal_id") or obj.get("id") or obj.get("uuid") or "").strip()
            if vid:
                vids.append(vid)
        collected.append(_Node(nid, name, parent_id, depth, vids, is_slice))
        for child in node.get("children") or []:
            if isinstance(child, dict):
                walk(child, nid, depth + 1, is_slice)

    for root in nodes or []:
        if isinstance(root, dict):
            walk(root, root_id, 1, False)  # верхний узел аккаунта = ДЗО (глубина 1)

    # Каноничные (не-срезовые) узлы: dim_org строим только из них.
    orgs: list[Org] = [Org(org_id=root_id, name=root_name, parent_id=None,
                           level=OrgLevel.HOLDING, type=OrgType.OWN)]
    canonical_id_by_name: dict[str, str] = {}
    for n in collected:
        if n.in_slice:
            continue
        orgs.append(Org(org_id=n.nid, name=n.name, parent_id=n.parent_id,
                        level=level_for(n.depth), type=OrgType.OWN))
        canonical_id_by_name.setdefault(n.name, n.nid)

    # Привязка ТС. Сначала — узлы среза: их ТС вешаем на каноничного двойника по
    # имени (если есть). Затем — каноничные узлы: они перебивают срезовую
    # привязку. Так реальный узел всегда «выигрывает», а ТС, лежащий ТОЛЬКО в
    # срезе, сохраняется на двойнике.
    vehicle_org: dict[str, str] = {}
    for n in collected:
        if not n.in_slice:
            continue
        target = canonical_id_by_name.get(n.name)
        if not target:
            continue  # сам узел-срез без каноничного двойника — его прямые ТС
            #            почти всегда есть и под каноничным узлом (перекроются ниже)
        for vid in n.vids:
            vehicle_org[vid] = target
    for n in collected:
        if n.in_slice:
            continue
        for vid in n.vids:
            vehicle_org[vid] = n.nid

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


# --- Ингест: привязка ТС к организациям --------------------------------------

def assign_org_ids(
    vehicles: list,
    vehicle_org: dict[str, str],
    *,
    overwrite: bool = False,
) -> int:
    """Проставить `org_id` каждому ТС из маппинга реестра (ингест по организациям).

    `vehicle_org[vehicle_id] = org_id` (берётся из `OrgRegistry.vehicle_org`).
    Уже привязанные ТС не трогаем, если `overwrite=False`. Возвращает число
    проставленных привязок.
    """
    n = 0
    for v in vehicles:
        if getattr(v, "org_id", None) and not overwrite:
            continue
        oid = vehicle_org.get(getattr(v, "vehicle_id", None))
        if oid:
            v.org_id = oid
            n += 1
    return n


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

# Расширения → SQLite-бэкенд (`store.py`); иначе JSON. Диспетч прозрачен для
# вызывающих (CLI `--registry`, holding_app): меняешь путь — меняешь хранилище.
_SQLITE_EXT = (".db", ".sqlite", ".sqlite3")


@dataclass
class OrgRegistry:
    """Снимок справочника организаций + маппинга ТС→организация."""

    tree: OrgTree
    vehicle_org: dict[str, str] = field(default_factory=dict)


def save_org_registry(registry: OrgRegistry, path: str = DEFAULT_ORG_REGISTRY) -> str:
    if path.lower().endswith(_SQLITE_EXT):
        from . import store
        return store.save_org_registry(registry, path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    payload = {
        "orgs": registry.tree.to_list(),
        "vehicle_org": registry.vehicle_org,
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
    return path


def load_org_registry(path: str = DEFAULT_ORG_REGISTRY) -> Optional[OrgRegistry]:
    if path.lower().endswith(_SQLITE_EXT):
        from . import store
        return store.load_org_registry(path)
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
