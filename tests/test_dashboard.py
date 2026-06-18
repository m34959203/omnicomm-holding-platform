"""Тесты дашборда на ДЗО, scope-доступа и привязки пользователей к узлу."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from omnicomm_report import auth, dashboard, org  # noqa: E402
from omnicomm_report.models import ReportPeriod, VehicleMetrics  # noqa: E402
from omnicomm_report.org import OrgLevel  # noqa: E402


SAMPLE_TREE = [
    {
        "id": "uran", "name": "Уранэнерго",
        "objects": [{"uuid": "v-uran-1"}],
        "children": [
            {"id": "tfo", "name": "ТФО",
             "objects": [{"uuid": "v-tfo-1"}, {"uuid": "v-tfo-2"}]},
            {"id": "shfo", "name": "ШФО", "objects": [{"uuid": "v-shfo-1"}]},
        ],
    },
    {"id": "umz", "name": "УМЗ", "objects": [{"uuid": "v-umz-1"}]},
]


def _vehicles():
    # Реалистичные показатели, чтобы analyze/charts отработали с данными.
    data = [
        ("v-uran-1", 1200, 240, 80, 92),
        ("v-tfo-1", 800, 160, 60, 88),
        ("v-tfo-2", 1500, 300, 90, 110),
        ("v-shfo-1", 600, 120, 50, 70),
        ("v-umz-1", 2000, 400, 120, 95),
    ]
    return [VehicleMetrics(vehicle_id=vid, name=vid, mileage_km=float(km),
                           fuel_l=float(fuel), engine_hours=float(eh),
                           max_speed_kmh=float(spd))
            for vid, km, fuel, eh, spd in data]


def _build():
    tree, vmap = org.build_from_omnicomm_tree(SAMPLE_TREE)
    return tree, vmap


def _period():
    return ReportPeriod(start=datetime(2026, 5, 1, tzinfo=timezone.utc),
                        end=datetime(2026, 5, 31, tzinfo=timezone.utc))


# --- срез ТС по организации ---------------------------------------------------

def test_vehicles_for_org_subtree():
    tree, vmap = _build()
    vs = dashboard.vehicles_for_org("uran", _vehicles(), tree, vmap)
    assert {v.vehicle_id for v in vs} == {"v-uran-1", "v-tfo-1", "v-tfo-2", "v-shfo-1"}
    assert {v.vehicle_id for v in dashboard.vehicles_for_org("tfo", _vehicles(), tree, vmap)} \
        == {"v-tfo-1", "v-tfo-2"}
    assert "v-umz-1" not in {v.vehicle_id
                             for v in dashboard.vehicles_for_org("uran", _vehicles(), tree, vmap)}


def test_build_org_report_scoped():
    tree, vmap = _build()
    rep = dashboard.build_org_report("uran", _vehicles(), _period(), tree,
                                     vehicle_org=vmap, fuel_price_kzt=320.0)
    assert rep.client_name == "Уранэнерго"        # имя организации, не «клиент»
    assert len(rep.vehicles) == 4                  # поддерево Уранэнерго
    assert rep.kpi.vehicles_total == 4


# --- доступ по scope ----------------------------------------------------------

def test_visible_scope_user_vs_admin():
    tree, _ = _build()
    # рядовой пользователь ДЗО видит только своё поддерево
    assert tree.visible_scope("uran") == {"uran", "tfo", "shfo"}
    assert "umz" not in tree.visible_scope("uran")
    # admin/руководитель холдинга — весь справочник
    assert tree.visible_scope(None, all_access=True) == set(tree.org_ids())
    # без узла и без all_access — пусто (fail-closed)
    assert tree.visible_scope(None) == set()


# --- привязка пользователей к узлу --------------------------------------------

def test_user_org_binding(tmp_path):
    p = str(tmp_path / "users.json")
    assert auth.create_user("uran_chief", "pw123", "manager", org_id="uran", path=p)
    assert auth.user_org("uran_chief", path=p) == "uran"
    # authenticate возвращает привязку
    info = auth.authenticate("uran_chief", "pw123", path=p)
    assert info == {"username": "uran_chief", "role": "manager", "org_id": "uran"}
    # неверный пароль — None
    assert auth.authenticate("uran_chief", "wrong", path=p) is None
    # verify обратносовместим (отдаёт роль)
    assert auth.verify("uran_chief", "pw123", path=p) == "manager"


def test_user_org_preserved_on_password_change(tmp_path):
    p = str(tmp_path / "users.json")
    auth.create_user("u", "old", "manager", org_id="tfo", path=p)
    auth.create_user("u", "new", "manager", path=p)        # смена пароля без org_id
    assert auth.user_org("u", path=p) == "tfo"             # привязка сохранилась
    assert auth.verify("u", "new", path=p) == "manager"


def test_list_users_includes_org(tmp_path):
    p = str(tmp_path / "users.json")
    auth.create_user("a", "x", "admin", path=p)
    auth.create_user("b", "y", "manager", org_id="umz", path=p)
    by = {u["username"]: u for u in auth.list_users(path=p)}
    assert by["a"]["org_id"] is None
    assert by["b"]["org_id"] == "umz"


# --- рендер: smoke + изоляция по scope ----------------------------------------

def test_render_org_report_html_smoke(tmp_path):
    tree, vmap = _build()
    rep = dashboard.build_org_report("uran", _vehicles(), _period(), tree,
                                     vehicle_org=vmap, fuel_price_kzt=320.0)
    out = dashboard.render_org_report(rep, str(tmp_path / "uran"))
    assert os.path.exists(out["html"])
    html = open(out["html"], encoding="utf-8").read()
    assert "Уранэнерго" in html                    # дашборд именно этого ДЗО
    # бизнес-инвариант сохраняется и в holding-дашборде
    for bad in ("слив", "воровств", "кража"):
        assert bad not in html.lower()


def test_render_for_scope_isolation(tmp_path):
    tree, vmap = _build()
    vehicles = _vehicles()
    # пользователь Уранэнерго рендерит дашборды только своего ДЗО-уровня
    res = dashboard.render_for_scope(
        "uran", vehicles, _period(), tree, str(tmp_path / "uran_scope"),
        levels=(OrgLevel.DZO,), vehicle_org=vmap, fuel_price_kzt=320.0)
    assert set(res.keys()) == {"uran"}             # чужое ДЗО недоступно
    assert "umz" not in res

    # admin рендерит по всем ДЗО холдинга
    res_admin = dashboard.render_for_scope(
        None, vehicles, _period(), tree, str(tmp_path / "admin_scope"),
        all_access=True, levels=(OrgLevel.DZO,), vehicle_org=vmap)
    assert set(res_admin.keys()) == {"uran", "umz"}
