"""Тесты holding-слоя: справочник организаций и row-level доступ."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from omnicomm_report import org  # noqa: E402
from omnicomm_report.models import VehicleMetrics  # noqa: E402


# Дерево Omnicomm под структуру КАП: Уранэнерго → {ТФО, ШФО}; УМЗ → {УМЗ Курчатов}.
SAMPLE_TREE = [
    {
        "id": "uran", "name": "Уранэнерго",
        "objects": [{"uuid": "v-uran-1", "name": "А001"}],
        "children": [
            {"id": "tfo", "name": "ТФО",
             "objects": [{"uuid": "v-tfo-1"}, {"uuid": "v-tfo-2"}]},
            {"id": "shfo", "name": "ШФО",
             "objects": [{"uuid": "v-shfo-1"}],
             "children": [
                 {"id": "contr-a", "name": "Подрядчик А",
                  "objects": [{"uuid": "v-contr-1"}]},
             ]},
        ],
    },
    {
        "id": "umz", "name": "УМЗ",
        "objects": [{"uuid": "v-umz-1"}],
        "children": [
            {"id": "umz-kur", "name": "УМЗ Курчатов",
             "objects": [{"uuid": "v-kur-1"}]},
        ],
    },
]


def _build():
    return org.build_from_omnicomm_tree(SAMPLE_TREE)


def test_build_creates_synthetic_holding_root():
    tree, _ = _build()
    roots = tree.roots()
    assert len(roots) == 1
    assert roots[0].org_id == "holding"
    assert roots[0].level == org.OrgLevel.HOLDING


def test_levels_by_depth():
    tree, _ = _build()
    assert tree.get("uran").level == org.OrgLevel.DZO       # глубина 1
    assert tree.get("tfo").level == org.OrgLevel.SUB_DZO    # глубина 2
    assert tree.get("contr-a").level == org.OrgLevel.SUB_DZO  # глубже клампится


def test_vehicle_mapping():
    _, vmap = _build()
    assert vmap["v-tfo-1"] == "tfo"
    assert vmap["v-uran-1"] == "uran"
    assert vmap["v-kur-1"] == "umz-kur"
    assert vmap["v-contr-1"] == "contr-a"


def test_subtree_includes_descendants():
    tree, _ = _build()
    sub = tree.subtree_ids("uran")
    assert sub == {"uran", "tfo", "shfo", "contr-a"}


def test_dzo_sees_own_subdzo_and_contractor():
    tree, _ = _build()
    # Уранэнерго видит свои под-ДЗО и подрядчика…
    assert tree.can_view("uran", "tfo")
    assert tree.can_view("uran", "shfo")
    assert tree.can_view("uran", "contr-a")
    # …но НЕ видит чужое ДЗО и его потомков (изоляция соседей).
    assert not tree.can_view("uran", "umz")
    assert not tree.can_view("uran", "umz-kur")


def test_holding_root_sees_everything():
    tree, _ = _build()
    for oid in ("uran", "tfo", "shfo", "contr-a", "umz", "umz-kur"):
        assert tree.can_view("holding", oid)


def test_subdzo_sees_only_itself():
    tree, _ = _build()
    assert tree.subtree_ids("tfo") == {"tfo"}
    assert not tree.can_view("tfo", "shfo")        # сосед не виден
    assert not tree.can_view("tfo", "uran")        # родитель не виден снизу


def test_ancestors_chain():
    tree, _ = _build()
    chain = [o.org_id for o in tree.ancestors("contr-a")]
    assert chain == ["shfo", "uran", "holding"]


def test_contractor_tagging_keeps_visibility():
    tree, _ = _build()
    org.apply_contractor_tags(tree, ["contr-a"])
    c = tree.get("contr-a")
    assert c.type == org.OrgType.CONTRACTOR
    assert c.level == org.OrgLevel.CONTRACTOR
    # видимость не изменилась — подрядчик всё ещё в поддереве Уранэнерго
    assert tree.can_view("uran", "contr-a")


def test_filter_vehicles_for_viewer_isolation():
    tree, vmap = _build()
    vehicles = [
        VehicleMetrics(vehicle_id="v-tfo-1", name="А-ТФО"),
        VehicleMetrics(vehicle_id="v-contr-1", name="А-Подрядчик"),
        VehicleMetrics(vehicle_id="v-umz-1", name="А-УМЗ"),
        VehicleMetrics(vehicle_id="v-kur-1", name="А-Курчатов"),
    ]
    seen = org.filter_vehicles_for_viewer(vehicles, "uran", tree, vmap)
    names = {v.vehicle_id for v in seen}
    assert names == {"v-tfo-1", "v-contr-1"}        # только своё поддерево


def test_filter_uses_vehicle_org_id_field_first():
    tree, _ = _build()
    v = VehicleMetrics(vehicle_id="x", name="X", org_id="tfo")
    seen = org.filter_vehicles_for_viewer([v], "uran", tree, {})
    assert seen == [v]


def test_filter_fail_closed_for_unassigned():
    tree, _ = _build()
    v = VehicleMetrics(vehicle_id="orphan", name="без организации")
    assert org.filter_vehicles_for_viewer([v], "holding", tree, {}) == []


def test_registry_roundtrip(tmp_path):
    tree, vmap = _build()
    org.apply_contractor_tags(tree, ["contr-a"])
    path = str(tmp_path / "org_registry.json")
    org.save_org_registry(org.OrgRegistry(tree=tree, vehicle_org=vmap), path)
    loaded = org.load_org_registry(path)
    assert loaded is not None
    assert len(loaded.tree) == len(tree)
    assert loaded.vehicle_org["v-tfo-1"] == "tfo"
    assert loaded.tree.get("contr-a").type == org.OrgType.CONTRACTOR
    assert loaded.tree.can_view("uran", "contr-a")          # доступ сохранился
    assert not loaded.tree.can_view("uran", "umz")
