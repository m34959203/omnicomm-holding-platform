"""Серверная изоляция данных по узлу оргструктуры (row-level, fail-closed).

Зритель с `org_id` видит ТОЛЬКО поддерево своего узла: снапшот обрезается до
этого поддерева ДО отдачи (дерево, KPI, все списки фильтруются по vehicle_org).
admin/КАП (`org_id is None`) видит всё. Неизвестный узел → пустой скоуп.
"""

from __future__ import annotations

from typing import Optional


def find_node(orgs: list, org_id: str) -> Optional[dict]:
    stack = list(orgs or [])
    while stack:
        n = stack.pop()
        if str(n.get("org_id")) == str(org_id):
            return n
        stack += n.get("children") or []
    return None


def subtree_ids(node: dict) -> set:
    ids, stack = set(), [node]
    while stack:
        n = stack.pop()
        ids.add(str(n.get("org_id")))
        stack += n.get("children") or []
    return ids


def allowed_terminals(snap: dict, org_id: str) -> Optional[set]:
    """Множество terminal_id в поддереве узла (для фильтра on-demand форм)."""
    node = find_node(snap.get("orgs") or [], org_id)
    if node is None:
        return set()
    ids = subtree_ids(node)
    vo = snap.get("vehicle_org") or {}
    return {t for t, o in vo.items() if str(o) in ids}


def scope_snapshot(snap: dict, org_id: str) -> dict:
    """Обрезать снапшот до поддерева org_id (новый dict; исходный не меняем)."""
    node = find_node(snap.get("orgs") or [], org_id)
    if node is None:
        # неизвестный узел → fail-closed: пусто
        return {**snap, "orgs": [], "vehicle_org": {}, "economics": None,
                "recommendations": [], "sensor_health": None, "maintenance": None,
                "tyres": None,
                "violations": None, "fuel": None, "fleet_table": None,
                "geozone_visits": None, "fleet": {"vehicles": 0, "with_data": 0}}
    ids = subtree_ids(node)
    vo_all = snap.get("vehicle_org") or {}
    def ins(tid) -> bool:
        return str(vo_all.get(tid)) in ids

    out = dict(snap)
    out["orgs"] = [node]
    out["vehicle_org"] = {t: o for t, o in vo_all.items() if str(o) in ids}
    # Экономика по поддереву узла (BUG-7): берём предрасчитанную на синке per-org.
    # Нет в снапшоте (старый снимок) → None (честный прочерк, не холдинг-числа).
    ebo = snap.get("economics_by_org") or {}
    out["economics"] = ebo.get(str(org_id))
    out["economics_by_org"] = {k: v for k, v in ebo.items() if k in ids}   # только своё поддерево
    out["fleet"] = {"vehicles": node.get("vehicle_count", 0),
                    "with_data": (node.get("kpi") or {}).get("vehicles_with_data", 0)}

    out["recommendations"] = [r for r in (snap.get("recommendations") or []) if ins(r.get("terminal_id"))]

    sh = snap.get("sensor_health")
    if sh:
        terms = [t for t in sh.get("terminals", []) if ins(t.get("terminal_id"))]
        miss = [m for m in sh.get("missing_capabilities", []) if ins(m.get("terminal_id"))]
        counts = {"online": 0, "stale": 0, "offline": 0, "unknown": 0}
        for t in terms:
            counts[t.get("status", "unknown")] = counts.get(t.get("status", "unknown"), 0) + 1
        power: dict = {}
        for m in miss:
            p = m.get("power")
            if p:
                power[p] = power.get(p, 0) + 1
        out["sensor_health"] = {**sh, "terminals": terms, "missing_capabilities": miss,
                                "counts": counts, "power": power}

    mt = snap.get("maintenance")
    if mt:
        items = [i for i in mt.get("items", []) if ins(i.get("terminal_id"))]
        counts = {}
        for i in items:
            counts[i["status"]] = counts.get(i["status"], 0) + 1
        out["maintenance"] = {**mt, "items": items, "counts": counts}

    ty = snap.get("tyres")
    if ty:
        items = [i for i in ty.get("items", []) if ins(i.get("terminal_id"))]
        counts = {}
        for i in items:
            counts[i["status"]] = counts.get(i["status"], 0) + 1
        out["tyres"] = {**ty, "items": items, "counts": counts,
                        "wear_kzt_total": round(sum(i.get("wear_kzt") or 0 for i in items), 0)}

    vi = snap.get("violations")
    if vi:
        rows = [r for r in vi.get("rows", []) if ins(r.get("vehicle_id"))]
        by: dict = {}
        for r in rows:
            by[r.get("type", "")] = by.get(r.get("type", ""), 0) + 1
        out["violations"] = {**vi, "rows": rows, "count": len(rows), "by_type": by}

    fu = snap.get("fuel")
    if fu:
        rows = [r for r in fu.get("rows", []) if ins(r.get("vehicle_id"))]
        out["fuel"] = {**fu, "rows": rows, "count": len(rows),
                       "totals": {"refuel_l": sum(r.get("refuel_l") or 0 for r in rows),
                                  "delivery_l": sum(r.get("delivery_l") or 0 for r in rows)}}

    ft = snap.get("fleet_table")
    if ft:
        rows = [r for r in ft.get("rows", []) if str(r.get("org_id")) in ids or ins(r.get("vehicle_id"))]
        out["fleet_table"] = {**ft, "rows": rows, "count": len(rows)}

    gv = snap.get("geozone_visits")
    if gv:
        rows = [r for r in gv.get("rows", []) if ins(r.get("vehicle_id"))]
        out["geozone_visits"] = {**gv, "rows": rows, "count": len(rows)}

    # geozones — физические зоны (полигоны), общие, не конфиденциальны по ДЗО → оставляем.
    return out
