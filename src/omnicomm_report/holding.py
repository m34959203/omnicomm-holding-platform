"""Holding-слой: end-to-end оркестрация прогона по холдингу.

Связывает кирпичи в один прогон:

    дерево ТС Omnicomm → dim_org (реестр) → загрузка ТС → ингест org_id →
    роллапы KPI по иерархии → дашборды на каждое ДЗО (в пределах scope)

Параметризован входными данными (дерево + список ТС), поэтому `run()` тестируется
без сети. Для боевого/демо-аккаунта есть тонкая обёртка `fetch_fleet`/`run_from_client`,
повторяющая забор из `__main__` (дерево + `data_loader.load_from_api` + `validator`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from . import org as org_mod
from . import rollup as rollup_mod
from . import dashboard as dashboard_mod
from .models import ReportPeriod
from .org import OrgLevel, OrgRegistry


@dataclass
class HoldingRun:
    """Результат прогона по холдингу."""

    registry: OrgRegistry
    kpi_tree: list                       # list[rollup.OrgKPI] от корней
    rendered: dict[str, dict[str, str]]  # {org_id: {fmt: path}}
    assigned: int                        # сколько ТС привязано к организациям
    unassigned: list[str] = field(default_factory=list)  # vehicle_id без узла в дереве


# --- Реестр организаций -------------------------------------------------------

def build_registry(
    tree_nodes: list[dict],
    *,
    contractor_org_ids: Optional[list[str]] = None,
    root_id: str = "holding",
    root_name: str = "КАП",
    registry_path: Optional[str] = None,
) -> OrgRegistry:
    """Построить `OrgRegistry` из дерева ТС Omnicomm (+ пометить подрядчиков, +сохранить)."""
    tree, vehicle_org = org_mod.build_from_omnicomm_tree(
        tree_nodes, root_id=root_id, root_name=root_name)
    if contractor_org_ids:
        org_mod.apply_contractor_tags(tree, contractor_org_ids)
    registry = OrgRegistry(tree=tree, vehicle_org=vehicle_org)
    if registry_path:
        org_mod.save_org_registry(registry, registry_path)
    return registry


# --- Главный прогон -----------------------------------------------------------

def run(
    tree_nodes: list[dict],
    vehicles: list,
    period: ReportPeriod,
    *,
    registry: Optional[OrgRegistry] = None,
    contractor_org_ids: Optional[list[str]] = None,
    registry_path: Optional[str] = None,
    fuel_price_kzt: float = 0.0,
    out_dir: str = "output/holding",
    viewer_org_id: Optional[str] = None,
    all_access: bool = True,
    levels: Optional[tuple[OrgLevel, ...]] = None,
    render: bool = True,
    html: bool = True,
    pptx: bool = False,
    **report_kwargs,
) -> HoldingRun:
    """Прогнать холдинг: реестр → ингест → роллапы → дашборды по ДЗО.

    :param registry: готовый реестр (иначе строится из `tree_nodes`).
    :param all_access: True (admin/руководитель холдинга) — по всему КАП; иначе scope
                       пользователя `viewer_org_id`.
    :param levels: какие уровни рендерить (напр. `(OrgLevel.DZO,)`); None — все с ТС.
    :param render: False — только данные (реестр+ингест+роллапы), без отрисовки.
    """
    if registry is None:
        registry = build_registry(
            tree_nodes, contractor_org_ids=contractor_org_ids,
            registry_path=registry_path)
    tree, vehicle_org = registry.tree, registry.vehicle_org

    # Ингест: привязать org_id каждому ТС; собрать непривязанных (нет узла в дереве).
    assigned = org_mod.assign_org_ids(vehicles, vehicle_org)
    unassigned = [getattr(v, "vehicle_id", None) for v in vehicles
                  if not getattr(v, "org_id", None)]

    # Роллапы KPI по иерархии (для дашборда руководителя по уровням).
    kpi_tree = rollup_mod.build_org_kpi_tree(
        vehicles, tree, fuel_price_kzt=fuel_price_kzt, vehicle_org=vehicle_org)

    # Дашборды на ДЗО в пределах scope (конфиденциальность соблюдается внутри).
    rendered: dict[str, dict[str, str]] = {}
    if render:
        rendered = dashboard_mod.render_for_scope(
            viewer_org_id, vehicles, period, tree, out_dir,
            all_access=all_access, levels=levels, vehicle_org=vehicle_org,
            html=html, pptx=pptx, fuel_price_kzt=fuel_price_kzt, **report_kwargs)

    return HoldingRun(registry=registry, kpi_tree=kpi_tree, rendered=rendered,
                      assigned=assigned, unassigned=[u for u in unassigned if u])


# --- Забор из боевого/демо-аккаунта (account-dependent, без юнит-тестов сети) --

def fetch_fleet(client, period: ReportPeriod, *, vehicle_ids=None,
                with_track: bool = False) -> tuple[list[dict], list]:
    """Забрать (дерево ТС, список ТС) из Omnicomm. Повторяет забор `__main__`.

    Импорты внутри — чтобы holding-слой грузился без сетевых зависимостей в тестах.
    """
    from . import data_loader, validator
    tree_nodes = client.get_vehicle_tree()
    vehicles = data_loader.load_from_api(client, period, vehicle_ids,
                                         with_track=with_track)
    vehicles = validator.validate(vehicles)
    return tree_nodes, vehicles


def run_from_client(client, period: ReportPeriod, *, fuel_price_kzt: float = 0.0,
                    out_dir: str = "output/holding",
                    contractor_org_ids: Optional[list[str]] = None,
                    registry_path: Optional[str] = None,
                    **kwargs) -> HoldingRun:
    """Полный прогон от живого Omnicomm-клиента: забрать данные и прогнать `run`."""
    tree_nodes, vehicles = fetch_fleet(client, period)
    return run(tree_nodes, vehicles, period, fuel_price_kzt=fuel_price_kzt,
               out_dir=out_dir, contractor_org_ids=contractor_org_ids,
               registry_path=registry_path, all_access=True, **kwargs)
