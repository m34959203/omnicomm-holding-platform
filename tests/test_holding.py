"""Тесты end-to-end оркестратора холдинга (без сети)."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from omnicomm_report import holding  # noqa: E402
from omnicomm_report.models import ReportPeriod, VehicleMetrics  # noqa: E402
from omnicomm_report.org import OrgLevel, OrgType  # noqa: E402


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
    {"id": "umz", "name": "УМЗ", "objects": [{"uuid": "v-umz-1"}]},
]


def _vehicles(extra_orphan=False):
    data = [
        ("v-uran-1", 1200, 240, 80, 92),
        ("v-tfo-1", 800, 160, 60, 88),
        ("v-tfo-2", 1500, 300, 90, 110),
        ("v-shfo-1", 600, 120, 50, 70),
        ("v-contr-1", 500, 100, 40, 65),
        ("v-umz-1", 2000, 400, 120, 95),
    ]
    vs = [VehicleMetrics(vehicle_id=vid, name=vid, mileage_km=float(km),
                         fuel_l=float(f), engine_hours=float(eh),
                         max_speed_kmh=float(s))
          for vid, km, f, eh, s in data]
    if extra_orphan:
        # ТС, которого нет в дереве аккаунта — должен попасть в unassigned.
        vs.append(VehicleMetrics(vehicle_id="v-ghost", name="вне дерева",
                                 mileage_km=10, fuel_l=5))
    return vs


def _period():
    return ReportPeriod(start=datetime(2026, 5, 1, tzinfo=timezone.utc),
                        end=datetime(2026, 5, 31, tzinfo=timezone.utc))


def test_build_registry_persists_and_tags(tmp_path):
    path = str(tmp_path / "reg.json")
    reg = holding.build_registry(SAMPLE_TREE, contractor_org_ids=["contr-a"],
                                 registry_path=path)
    assert os.path.exists(path)
    assert reg.vehicle_org["v-tfo-1"] == "tfo"
    assert reg.tree.get("contr-a").type == OrgType.CONTRACTOR
    assert reg.tree.get("holding").level == OrgLevel.HOLDING


def test_run_data_only_no_render():
    res = holding.run(SAMPLE_TREE, _vehicles(), _period(),
                      fuel_price_kzt=320.0, render=False)
    # ингест
    assert res.assigned == 6
    assert res.unassigned == []
    # роллапы: корень-холдинг агрегирует весь парк
    root = res.kpi_tree[0]
    assert root.org.org_id == "holding"
    assert root.vehicle_count == 6
    # Уранэнерго = свои + оба под-ДЗО + подрядчик
    uran = {c.org.org_id: c for c in root.children}["uran"]
    assert uran.vehicle_count == 5
    assert uran.kpi.total_fuel_l == 240 + 160 + 300 + 120 + 100


def test_run_reports_unassigned():
    res = holding.run(SAMPLE_TREE, _vehicles(extra_orphan=True), _period(),
                      render=False)
    assert res.unassigned == ["v-ghost"]
    assert res.assigned == 6                      # призрак не привязан


def test_run_renders_per_dzo_admin(tmp_path):
    res = holding.run(SAMPLE_TREE, _vehicles(), _period(),
                      fuel_price_kzt=320.0, out_dir=str(tmp_path / "out"),
                      all_access=True, levels=(OrgLevel.DZO,))
    # admin рендерит дашборд на каждое ДЗО холдинга
    assert set(res.rendered.keys()) == {"uran", "umz"}
    for paths in res.rendered.values():
        assert os.path.exists(paths["html"])


def test_run_scope_isolation_for_dzo_user(tmp_path):
    # Пользователь Уранэнерго: рендерится только его ДЗО, УМЗ недоступно.
    res = holding.run(SAMPLE_TREE, _vehicles(), _period(),
                      out_dir=str(tmp_path / "out"),
                      viewer_org_id="uran", all_access=False,
                      levels=(OrgLevel.DZO,))
    assert set(res.rendered.keys()) == {"uran"}
    assert "umz" not in res.rendered


def test_run_with_prebuilt_registry():
    reg = holding.build_registry(SAMPLE_TREE)
    res = holding.run(SAMPLE_TREE, _vehicles(), _period(),
                      registry=reg, render=False)
    assert res.registry is reg
    assert res.assigned == 6
