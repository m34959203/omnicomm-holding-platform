"""Тесты ингеста по организациям и роллапов KPI по иерархии."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from omnicomm_report import org, rollup  # noqa: E402
from omnicomm_report.models import VehicleMetrics  # noqa: E402


# Уранэнерго имеет ДВА под-ДЗО (ТФО, ШФО) — проверка «у ДЗО несколько подорганизаций».
SAMPLE_TREE = [
    {
        "id": "uran", "name": "Уранэнерго",
        "objects": [{"uuid": "v-uran-1"}],
        "children": [
            {"id": "tfo", "name": "ТФО",
             "objects": [{"uuid": "v-tfo-1"}, {"uuid": "v-tfo-2"}]},
            {"id": "shfo", "name": "ШФО",
             "objects": [{"uuid": "v-shfo-1"}],
             "children": [{"id": "contr-a", "name": "Подрядчик А",
                           "objects": [{"uuid": "v-contr-1"}]}]},
        ],
    },
    {
        "id": "umz", "name": "УМЗ",
        "objects": [{"uuid": "v-umz-1"}],
        "children": [{"id": "umz-kur", "name": "УМЗ Курчатов",
                      "objects": [{"uuid": "v-kur-1"}]}],
    },
]

# Топливо по каждому ТС — суммы легко проверяемы.
FUEL = {
    "v-uran-1": 10, "v-tfo-1": 20, "v-tfo-2": 30, "v-shfo-1": 40,
    "v-contr-1": 50, "v-umz-1": 60, "v-kur-1": 70,
}


def _vehicles():
    return [VehicleMetrics(vehicle_id=vid, name=vid, fuel_l=float(f),
                           mileage_km=100.0) for vid, f in FUEL.items()]


def _build():
    tree, vmap = org.build_from_omnicomm_tree(SAMPLE_TREE)
    return tree, vmap


def test_assign_org_ids():
    tree, vmap = _build()
    vehicles = _vehicles()
    n = org.assign_org_ids(vehicles, vmap)
    assert n == len(vehicles)
    by_id = {v.vehicle_id: v for v in vehicles}
    assert by_id["v-tfo-1"].org_id == "tfo"
    assert by_id["v-contr-1"].org_id == "contr-a"
    assert by_id["v-kur-1"].org_id == "umz-kur"


def test_assign_org_ids_no_overwrite():
    tree, vmap = _build()
    v = VehicleMetrics(vehicle_id="v-tfo-1", name="x", org_id="manual")
    org.assign_org_ids([v], vmap)            # overwrite=False по умолчанию
    assert v.org_id == "manual"
    org.assign_org_ids([v], vmap, overwrite=True)
    assert v.org_id == "tfo"


def test_rollup_sums_full_subtree():
    tree, vmap = _build()
    kpis = rollup.rollup_kpi(_vehicles(), tree, vehicle_org=vmap)
    # ТФО — только свои два ТС.
    assert kpis["tfo"].total_fuel_l == 50          # 20 + 30
    # ШФО — свой ТС + подрядчик в поддереве.
    assert kpis["shfo"].total_fuel_l == 90         # 40 + 50
    # Уранэнерго агрегирует ОБА под-ДЗО (ТФО+ШФО) + свой прямой ТС + подрядчика.
    assert kpis["uran"].total_fuel_l == 150        # 10 + 20 + 30 + 40 + 50
    # УМЗ — свой + Курчатов.
    assert kpis["umz"].total_fuel_l == 130         # 60 + 70
    # Холдинг — весь КАП.
    assert kpis["holding"].total_fuel_l == 280     # сумма всех семи


def test_rollup_vehicle_counts():
    tree, vmap = _build()
    kpis = rollup.rollup_kpi(_vehicles(), tree, vehicle_org=vmap)
    assert kpis["uran"].vehicles_total == 5        # поддерево Уранэнерго
    assert kpis["tfo"].vehicles_total == 2
    assert kpis["holding"].vehicles_total == 7


def test_org_kpi_tree_structure_and_counts():
    tree, vmap = _build()
    forest = rollup.build_org_kpi_tree(_vehicles(), tree, vehicle_org=vmap)
    assert len(forest) == 1                        # один корень-холдинг
    root = forest[0]
    assert root.org.org_id == "holding"
    assert root.vehicle_count == 7
    assert root.direct_vehicle_count == 0          # к холдингу напрямую ТС не привязаны

    by_id = {c.org.org_id: c for c in root.children}
    uran = by_id["uran"]
    # У Уранэнерго несколько подорганизаций — оба под-ДЗО как дети.
    child_ids = {c.org.org_id for c in uran.children}
    assert child_ids == {"tfo", "shfo"}
    assert uran.vehicle_count == 5
    assert uran.direct_vehicle_count == 1          # v-uran-1 напрямую
    assert uran.kpi.total_fuel_l == 150


def test_rollup_reads_vehicle_org_id_field():
    # Без маппинга, org_id уже проставлен на ТС (после assign_org_ids).
    tree, vmap = _build()
    vehicles = _vehicles()
    org.assign_org_ids(vehicles, vmap)
    kpis = rollup.rollup_kpi(vehicles, tree)       # vehicle_org не передаём
    assert kpis["uran"].total_fuel_l == 150
