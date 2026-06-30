"""Тесты Фазы 2: row-level (fail-closed), валидация секций, лимиты, миграции."""

import pytest
from fastapi.testclient import TestClient

from api import layouts, layouts_store as st, cache
from api.main import app

A = {"user_id": "a", "org_id": "A", "role": "manager"}
B = {"user_id": "b", "org_id": "B", "role": "manager"}
ADMIN = {"user_id": "adm", "org_id": None, "role": "admin"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    orig = st._conn
    db = str(tmp_path / "l.db")
    monkeypatch.setattr(st, "_conn", lambda path=None: orig(db))   # все вызовы → tmp
    layouts.seed_system_templates()                                # системные шаблоны в tmp
    c = TestClient(app)
    yield c
    app.dependency_overrides.pop(layouts.principal, None)


def _as(p):
    app.dependency_overrides[layouts.principal] = lambda: p


def test_rowlevel_fail_closed(client):
    _as(A)
    lid = client.post("/api/layouts", json={"name": "A-стол", "layout": {"widgets": []}}).json()["layout"]["id"]
    assert client.get(f"/api/layouts/{lid}").status_code == 200      # владелец видит
    _as(B)
    assert client.get(f"/api/layouts/{lid}").status_code == 404      # чужой ДЗО → 404
    assert all(l["id"] != lid for l in client.get("/api/layouts").json()["layouts"])  # и в списке нет
    _as(ADMIN)
    assert client.get(f"/api/layouts/{lid}").status_code == 200      # admin видит всё


def test_apply_inherits_user_org(client):
    _as(A)
    # системные шаблоны засеяны при старте app
    tpls = client.get("/api/templates").json()["templates"]
    sysid = next(t["id"] for t in tpls if t["is_system"])
    lay = client.post(f"/api/templates/{sysid}/apply").json()["layout"]
    assert lay["org_id"] == "A" and lay["owner"] == "a"             # стол с орг ЮЗЕРА


def test_limits_widgets(client):
    _as(A)
    big = {"widgets": [{"type": "kpiTile", "w": 2, "h": 1} for _ in range(41)]}
    assert client.post("/api/layouts", json={"name": "big", "layout": big}).status_code == 400


def test_compose_validation(client, monkeypatch):
    monkeypatch.setattr(cache, "latest_snapshot", lambda: {
        "_meta": {"period_key": "pk"}, "vehicle_org": {},
        "economics": {"coi_annual_kzt": 1}, "maintenance": None, "orgs": []})
    _as(ADMIN)
    r = client.post("/api/dashboard/compose", json={"sections": ["economics", "maintenance", "bogus", "speed_trend"]}).json()
    assert r["sections"]["economics"] == {"coi_annual_kzt": 1}                 # есть
    assert r["sections"]["maintenance"]["reason"] == "section_missing"          # None в снапшоте
    assert r["sections"]["bogus"]["reason"] == "section_not_allowed"            # не в реестре
    assert r["sections"]["speed_trend"]["reason"] == "section_missing"          # on-demand


def test_migrate_sets_version(client):
    assert layouts.migrate_layout({"widgets": []})["schemaVersion"] == st.SCHEMA_VERSION


def test_sharing_readonly(client, monkeypatch):
    # дерево: A → C (C в поддереве A)
    monkeypatch.setattr(cache, "latest_snapshot", lambda: {"orgs": [{"org_id": "A", "children": [{"org_id": "C", "children": []}]}]})
    _as({"user_id": "pa", "org_id": "A", "role": "manager"})
    sh = client.post("/api/layouts", json={"name": "sh", "layout": {"widgets": []}, "shared": True}).json()["layout"]["id"]
    pr = client.post("/api/layouts", json={"name": "pr", "layout": {"widgets": []}}).json()["layout"]["id"]
    _as({"user_id": "pc", "org_id": "C", "role": "manager"})
    assert client.get(f"/api/layouts/{sh}").status_code == 200        # shared виден в поддереве
    assert client.get(f"/api/layouts/{pr}").status_code == 404        # приватный — нет
    assert client.put(f"/api/layouts/{sh}", json={"name": "x", "layout": {"widgets": []}}).status_code == 403  # только чтение


def test_schedule_crud(client):
    _as(A)
    sid = client.post("/api/schedules", json={"email": "x@kap.kz", "frequency": "daily", "hour": 6}).json()["schedule"]["id"]
    assert any(s["id"] == sid for s in client.get("/api/schedules").json()["schedules"])
    assert client.post("/api/schedules", json={"email": "bad", "frequency": "daily"}).status_code == 400
    _as(B)   # чужое расписание не видно/не удалить
    assert all(s["id"] != sid for s in client.get("/api/schedules").json()["schedules"])
    assert client.delete(f"/api/schedules/{sid}").status_code == 404


def test_system_template_no_delete(client):
    _as(ADMIN)
    sysid = next(t["id"] for t in client.get("/api/templates").json()["templates"] if t["is_system"])
    assert client.delete(f"/api/templates/{sysid}").status_code == 403         # системный нельзя
