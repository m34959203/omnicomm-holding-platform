"""API рабочих столов и шаблонов (Фаза 2): CRUD + row-level + compose.

Идентичность — из cookie-сессии (auth_session.viewer): principal {user_id, org_id, role}.
Row-level fail-closed: видно своё ИЛИ org_id в поддереве зрителя; чужой объект → 404.
"""

from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from . import auth_session, cache, layouts_store as st, scoping

router = APIRouter()

LAYOUT_MAX_BYTES = 64 * 1024
MAX_WIDGETS = 40
COMPOSE_MAX_SECTIONS = 12

# Снапшот-секции, доступные compose/виджетам (единый реестр).
SECTIONS = {
    "dashboard": lambda s: {"orgs": s.get("orgs"), "economics": s.get("economics"),
                            "economics_by_org": s.get("economics_by_org"), "fleet": s.get("fleet"),
                            "period": s.get("period")},
    "economics": lambda s: s.get("economics"),
    "sensor_health": lambda s: s.get("sensor_health"),
    "maintenance": lambda s: s.get("maintenance"),
    "recommendations": lambda s: s.get("recommendations"),
    "violations": lambda s: s.get("violations"),
    "fuel": lambda s: s.get("fuel"),
    "geozones": lambda s: s.get("geozones"),
    "geozone_visits": lambda s: s.get("geozone_visits"),
    "fleet_table": lambda s: s.get("fleet_table"),
}
# speed_trend/violations-detail/fuel-detail — on-demand (не в снапшоте); compose их помечает section_missing.
ALLOWED_SECTIONS = set(SECTIONS) | {"speed_trend"}


# ---- Идентичность / RBAC ----
def principal(request: Request) -> dict:
    v = auth_session.viewer(request)
    if not v:
        raise HTTPException(401, "Требуется вход")
    return {"user_id": v["username"], "org_id": v.get("org_id"), "role": v.get("role")}


def _subtree(org_id: Optional[str]) -> Optional[set]:
    """Множество org_id поддерева (вкл. сам). None → admin (всё видно)."""
    if not org_id:
        return None
    snap = cache.latest_snapshot() or {}
    node = scoping.find_node(snap.get("orgs") or [], org_id)
    return scoping.subtree_ids(node) if node else {str(org_id)}


def _can_view(p: dict, owner: Optional[str], org_id: Optional[str]) -> bool:
    if p["org_id"] is None:                 # admin / КАП-холдинг
        return True
    if owner == p["user_id"]:
        return True
    sub = _subtree(p["org_id"]) or set()
    return org_id is not None and str(org_id) in sub


def migrate_layout(layout: dict) -> dict:
    layout = dict(layout or {})
    layout["schemaVersion"] = st.SCHEMA_VERSION
    return layout


def _validate_layout(layout: dict) -> None:
    widgets = (layout or {}).get("widgets") or []
    if len(widgets) > MAX_WIDGETS:
        raise HTTPException(400, f"Слишком много виджетов (>{MAX_WIDGETS})")
    if len(json.dumps(layout, ensure_ascii=False).encode()) > LAYOUT_MAX_BYTES:
        raise HTTPException(400, f"Раскладка больше {LAYOUT_MAX_BYTES} байт")


# ---- Модели ----
class LayoutBody(BaseModel):
    name: str
    layout: dict
    is_default: bool = False


class TemplateBody(BaseModel):
    name: str
    role: str = ""
    description: str = ""
    layout: dict


# ---- Layouts ----
@router.get("/api/layouts")
def list_layouts(p: dict = Depends(principal)) -> dict:
    items = [layout_view(x) for x in st.list_layouts() if _can_view(p, x["owner"], x["org_id"])]
    return {"layouts": items}


@router.get("/api/layouts/default")
def get_default(p: dict = Depends(principal)) -> dict:
    d = st.default_layout(p["user_id"])
    return {"layout": layout_view(d) if d else None}


@router.get("/api/layouts/{lid}")
def get_layout(lid: str, p: dict = Depends(principal)) -> dict:
    x = st.get_layout(lid)
    if not x or not _can_view(p, x["owner"], x["org_id"]):
        raise HTTPException(404, "Стол не найден")
    return {"layout": layout_view(x)}


@router.post("/api/layouts")
def create_layout(body: LayoutBody, p: dict = Depends(principal)) -> dict:
    _validate_layout(body.layout)
    x = st.upsert_layout(lid=st.new_id(), owner=p["user_id"], org_id=p["org_id"],
                         name=body.name, layout=migrate_layout(body.layout), is_default=body.is_default)
    return {"layout": layout_view(x)}


@router.put("/api/layouts/{lid}")
def update_layout(lid: str, body: LayoutBody, p: dict = Depends(principal)) -> dict:
    cur = st.get_layout(lid)
    if not cur or not _can_view(p, cur["owner"], cur["org_id"]):
        raise HTTPException(404, "Стол не найден")
    if cur["owner"] != p["user_id"] and p["org_id"] is not None:
        raise HTTPException(403, "Нет прав на изменение")
    _validate_layout(body.layout)
    x = st.upsert_layout(lid=lid, owner=cur["owner"], org_id=cur["org_id"],
                         name=body.name, layout=migrate_layout(body.layout), is_default=body.is_default)
    return {"layout": layout_view(x)}


@router.delete("/api/layouts/{lid}")
def remove_layout(lid: str, p: dict = Depends(principal)) -> dict:
    cur = st.get_layout(lid)
    if not cur or not _can_view(p, cur["owner"], cur["org_id"]):
        raise HTTPException(404, "Стол не найден")
    if cur["owner"] != p["user_id"] and p["org_id"] is not None:
        raise HTTPException(403, "Нет прав на удаление")
    st.delete_layout(lid)
    return {"ok": True}


# ---- Templates ----
@router.get("/api/templates")
def list_templates(p: dict = Depends(principal)) -> dict:
    items = [tpl_view(x) for x in st.list_templates()
             if x["is_system"] or _can_view(p, x["owner"], x["org_id"])]
    return {"templates": items}


@router.get("/api/templates/{tid}")
def get_template(tid: str, p: dict = Depends(principal)) -> dict:
    x = st.get_template(tid)
    if not x or (not x["is_system"] and not _can_view(p, x["owner"], x["org_id"])):
        raise HTTPException(404, "Шаблон не найден")
    return {"template": tpl_view(x)}


@router.post("/api/templates")
def create_template(body: TemplateBody, p: dict = Depends(principal)) -> dict:
    _validate_layout(body.layout)
    x = st.upsert_template(tid=st.new_id(), owner=p["user_id"], org_id=p["org_id"], name=body.name,
                           role=body.role, description=body.description, layout=migrate_layout(body.layout))
    return {"template": tpl_view(x)}


@router.delete("/api/templates/{tid}")
def remove_template(tid: str, p: dict = Depends(principal)) -> dict:
    x = st.get_template(tid)
    if not x or (not x["is_system"] and not _can_view(p, x["owner"], x["org_id"])):
        raise HTTPException(404, "Шаблон не найден")
    if x["is_system"]:
        raise HTTPException(403, "Системный шаблон нельзя удалить")
    if x["owner"] != p["user_id"] and p["org_id"] is not None:
        raise HTTPException(403, "Нет прав")
    st.delete_template(tid)
    return {"ok": True}


@router.post("/api/templates/{tid}/apply")
def apply_template(tid: str, p: dict = Depends(principal)) -> dict:
    x = st.get_template(tid)
    if not x or (not x["is_system"] and not _can_view(p, x["owner"], x["org_id"])):
        raise HTTPException(404, "Шаблон не найден")
    # Новый стол наследует org юзера (НЕ автора шаблона) — данные по его поддереву.
    layout = migrate_layout(x["layout"])
    for w in layout.get("widgets") or []:        # уникальные id виджетам (в шаблоне их нет)
        w["id"] = "w" + st.new_id()[:10]
    lay = st.upsert_layout(lid=st.new_id(), owner=p["user_id"], org_id=p["org_id"],
                           name=x["name"], layout=layout)
    return {"layout": layout_view(lay)}


@router.post("/api/layouts/{lid}/save-as-template")
def save_as_template(lid: str, body: TemplateBody, p: dict = Depends(principal)) -> dict:
    cur = st.get_layout(lid)
    if not cur or not _can_view(p, cur["owner"], cur["org_id"]):
        raise HTTPException(404, "Стол не найден")
    x = st.upsert_template(tid=st.new_id(), owner=p["user_id"], org_id=p["org_id"], name=body.name or cur["name"],
                           role=body.role, description=body.description, layout=migrate_layout(cur["layout"]))
    return {"template": tpl_view(x)}


# ---- Compose (батч секций) ----
class ComposeBody(BaseModel):
    period_key: Optional[str] = None
    sections: Optional[list[str]] = None
    layout_id: Optional[str] = None


@router.post("/api/dashboard/compose")
def compose(body: ComposeBody, request: Request, p: dict = Depends(principal)) -> dict:
    snap = cache.load_snapshot(body.period_key) if body.period_key else cache.latest_snapshot()
    if snap is None:
        raise HTTPException(404, "Нет снапшота")
    if p["org_id"]:
        snap = scoping.scope_snapshot(snap, p["org_id"])     # серверный скоуп по ДЗО

    secs = body.sections
    if not secs and body.layout_id:
        lay = st.get_layout(body.layout_id)
        if not lay or not _can_view(p, lay["owner"], lay["org_id"]):
            raise HTTPException(404, "Стол не найден")
        # секции = dataKey виджетов (фронт-реестр их не знает на сервере → берём типовые)
        secs = sorted({_TYPE_SECTION.get(w.get("type"), "dashboard") for w in (lay["layout"].get("widgets") or [])})
    secs = (secs or [])[:COMPOSE_MAX_SECTIONS]

    out: dict = {}
    for sec in secs:
        if sec not in ALLOWED_SECTIONS:
            out[sec] = {"available": False, "reason": "section_not_allowed"}
        elif sec not in SECTIONS:
            out[sec] = {"available": False, "reason": "section_missing"}   # on-demand (speed_trend)
        else:
            val = SECTIONS[sec](snap)
            out[sec] = val if val is not None else {"available": False, "reason": "section_missing"}
    return {"period_key": (snap.get("_meta") or {}).get("period_key"),
            "sections": out, "vehicle_org": snap.get("vehicle_org", {}), "meta": snap.get("_meta")}


@router.get("/api/sections/catalog")
def sections_catalog(p: dict = Depends(principal)) -> dict:
    return {"sections": sorted(ALLOWED_SECTIONS)}


# type→section для compose по layout_id (зеркало dataKey из фронт-реестра)
_TYPE_SECTION = {
    "kpiTile": "dashboard", "dzoBars": "dashboard", "parkDonut": "dashboard", "matrix": "dashboard",
    "economics": "economics", "sensorHealth": "sensor_health", "maintenance": "maintenance",
    "recommendations": "recommendations", "violations": "violations", "fuel": "fuel", "speedTrend": "speed_trend",
}


# ---- Системные шаблоны (код = источник правды, upsert при старте) ----
def _w(type_, w, h, settings=None):
    d = {"type": type_, "w": w, "h": h}
    if settings:
        d["settings"] = settings
    return d


SYSTEM_TEMPLATES = [
    {"id": "sys-exec-overview", "name": "Руководитель — обзор", "role": "Руководство",
     "description": "Деньги, превышения, связь и матрица по ДЗО.", "widgets": [
        _w("kpiTile", 3, 1, {"metric": "potential"}), _w("kpiTile", 3, 1, {"metric": "coi"}),
        _w("kpiTile", 3, 1, {"metric": "episodes"}), _w("kpiTile", 3, 1, {"metric": "sensor"}),
        _w("dzoBars", 5, 2, {"metric": "potential"}), _w("economics", 4, 2), _w("parkDonut", 3, 2),
        _w("matrix", 12, 3)]},
    {"id": "sys-money", "name": "Экономика и топливо", "role": "Финансы",
     "description": "Потенциал/COI, структура потерь, ₸/км, перерасход.", "widgets": [
        _w("kpiTile", 3, 1, {"metric": "potential"}), _w("kpiTile", 3, 1, {"metric": "fuelCost"}),
        _w("kpiTile", 3, 1, {"metric": "cpkm"}), _w("kpiTile", 3, 1, {"metric": "coi"}),
        _w("economics", 5, 2), _w("dzoBars", 4, 2, {"metric": "cpkm"}), _w("dzoBars", 3, 2, {"metric": "l100"}),
        _w("fuel", 12, 4)]},
    {"id": "sys-speed", "name": "Скоростной режим", "role": "БДД / СТ КАП",
     "description": "Превышения по ДЗО, повторяемость, детальная таблица.", "widgets": [
        _w("kpiTile", 3, 1, {"metric": "episodes"}), _w("dzoBars", 5, 2, {"metric": "episodes"}),
        _w("recommendations", 4, 2), _w("speedTrend", 12, 4), _w("violations", 12, 4)]},
    {"id": "sys-quality", "name": "Качество данных", "role": "Телематика",
     "description": "Связь терминалов и датчики по ДЗО.", "widgets": [
        _w("kpiTile", 3, 1, {"metric": "sensor"}), _w("sensorHealth", 5, 2),
        _w("dzoBars", 4, 2, {"metric": "episodes"}), _w("matrix", 12, 3)]},
    {"id": "sys-maintenance", "name": "Контроль ТО", "role": "Сервис / ремонт",
     "description": "Наработка, просроченные ТО по ДЗО.", "widgets": [
        _w("kpiTile", 3, 1, {"metric": "sensor"}), _w("maintenance", 6, 3), _w("dzoBars", 6, 3, {"metric": "overdue"})]},
    {"id": "sys-fuel-ops", "name": "Топливо — операционка", "role": "ГСМ",
     "description": "Расход/норма/перерасход по ТС и ₸/км.", "widgets": [
        _w("kpiTile", 3, 1, {"metric": "fuelCost"}), _w("dzoBars", 5, 2, {"metric": "cpkm"}),
        _w("dzoBars", 4, 2, {"metric": "l100"}), _w("fuel", 12, 5)]},
    {"id": "sys-compare", "name": "Сравнение подрядчиков", "role": "Закупки / контроль",
     "description": "Матрица ДЗО + бары для сравнения по деньгам, ₸/км и превышениям.", "widgets": [
        _w("kpiTile", 3, 1, {"metric": "cpkm"}), _w("kpiTile", 3, 1, {"metric": "episodes"}),
        _w("dzoBars", 6, 2, {"metric": "cpkm"}),
        _w("dzoBars", 6, 2, {"metric": "potential"}), _w("dzoBars", 6, 2, {"metric": "episodes"}),
        _w("matrix", 12, 4)]},
    {"id": "sys-dzo-card", "name": "Карточка ДЗО", "role": "ДЗО",
     "description": "Деньги, скорость, ТО, связь под одно ДЗО.", "widgets": [
        _w("kpiTile", 3, 1, {"metric": "potential"}), _w("kpiTile", 3, 1, {"metric": "episodes"}),
        _w("kpiTile", 3, 1, {"metric": "sensor"}), _w("kpiTile", 3, 1, {"metric": "veh"}),
        _w("economics", 4, 2), _w("sensorHealth", 4, 2), _w("maintenance", 4, 2),
        _w("recommendations", 6, 3), _w("violations", 6, 3)]},
]


def seed_system_templates() -> None:
    """Upsert 7 системных шаблонов по стабильным id (код — источник правды)."""
    for t in SYSTEM_TEMPLATES:
        layout = {"schemaVersion": st.SCHEMA_VERSION, "name": t["name"],
                  "widgets": [dict(w) for w in t["widgets"]], "columns": 12}
        st.upsert_template(tid=t["id"], owner=None, org_id=None, name=t["name"],
                           role=t["role"], description=t["description"], layout=layout, is_system=True)


def layout_view(x: dict) -> dict:
    return {"id": x["id"], "name": x["name"], "org_id": x["org_id"], "owner": x["owner"],
            "is_default": x["is_default"], "layout": migrate_layout(x["layout"]),
            "updated_at": x["updated_at"]}


def tpl_view(x: dict) -> dict:
    return {"id": x["id"], "name": x["name"], "role": x["role"], "description": x["description"],
            "is_system": x["is_system"], "org_id": x["org_id"], "layout": migrate_layout(x["layout"])}
