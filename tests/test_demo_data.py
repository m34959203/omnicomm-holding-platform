"""Тесты синтетических демо-данных холдинга (demo_data)."""
from datetime import datetime, time, timezone, date, timedelta

from omnicomm_report import demo_data, dashboard, org as org_mod
from omnicomm_report.models import ReportPeriod


def _period(days=7):
    d_to = date(2026, 6, 18)
    d_from = d_to - timedelta(days=days - 1)
    return ReportPeriod(
        start=datetime.combine(d_from, time.min, tzinfo=timezone.utc),
        end=datetime.combine(d_to, time.max, tzinfo=timezone.utc))


def test_registry_hierarchy_and_assignment():
    reg = demo_data.build_demo_registry()
    tree = reg.tree
    assert tree.get("holding") is not None
    # дерево содержит ДЗО, под-ДЗО и подрядчика
    assert {"volkov", "appak", "uranenergo", "umz"} <= set(tree.org_ids())
    assert tree.get("tfo").parent_id == "uranenergo"
    assert tree.get("burservice").parent_id == "volkov"
    # каждая привязка ТС указывает на существующий узел
    assert reg.vehicle_org
    for vid, oid in reg.vehicle_org.items():
        assert tree.exists(oid)


def test_fleet_deterministic():
    p = _period()
    a = demo_data.demo_fleet(p)
    b = demo_data.demo_fleet(p)
    assert [v.vehicle_id for v in a] == [v.vehicle_id for v in b]
    assert [v.fuel_l for v in a] == [v.fuel_l for v in b]


def test_all_vehicles_assigned_and_dark_present():
    reg = demo_data.build_demo_registry()
    veh = demo_data.demo_fleet(_period())
    org_mod.assign_org_ids(veh, reg.vehicle_org)
    # все ТС попадают в поддерево холдинга
    in_holding = dashboard.vehicles_for_org("holding", veh, reg.tree, reg.vehicle_org)
    assert len(in_holding) == len(veh) == len(reg.vehicle_org)
    # есть «тёмные» и есть классы mobile/stationary
    assert any(not v.has_data for v in veh)
    assert any(v.is_stationary for v in veh if v.has_data)
    assert any(not v.is_stationary for v in veh if v.has_data)


def test_subtree_rollup_and_nonzero_kpi():
    reg = demo_data.build_demo_registry()
    tree = reg.tree
    p = _period()
    veh = demo_data.demo_fleet(p)
    org_mod.assign_org_ids(veh, reg.vehicle_org)

    rep_h = dashboard.build_org_report("holding", veh, p, tree,
                                       vehicle_org=reg.vehicle_org, fuel_price_kzt=320.0)
    assert rep_h.kpi.vehicles_total == len(veh)
    assert rep_h.kpi.total_fuel_l > 0
    assert rep_h.kpi.total_fuel_cost > 0
    assert rep_h.alerts, "лента сигналов не должна быть пустой на демо"

    # Волковгеология = свои ТС + поддерево подрядчика БурСервис
    n_volkov = len(dashboard.vehicles_for_org("volkov", veh, tree, reg.vehicle_org))
    n_burservice = len(dashboard.vehicles_for_org("burservice", veh, tree, reg.vehicle_org))
    rep_v = dashboard.build_org_report("volkov", veh, p, tree,
                                       vehicle_org=reg.vehicle_org, fuel_price_kzt=320.0)
    assert rep_v.kpi.vehicles_total == n_volkov
    assert n_burservice > 0 and n_volkov > n_burservice
