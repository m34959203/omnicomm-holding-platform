"""Отчётные формы паритета с Omnicomm Online (см. docs/knowledge-base/14).

Каждая форма строится из УЖЕ имеющихся данных (агрегаты `consolidatedReport` +
визиты `geozones_report` из `raw_store`), питает секцию снапшота и отдаётся мгновенно.
Формы, требующие внутрисуточной телеметрии/событий (Объём топлива, Журнал, События) —
заблокированы доступом REST на `projectkap` (kb-12/14), здесь не строятся.
"""

from __future__ import annotations

from typing import Any, Optional


def _num(x: Any) -> Optional[float]:
    try:
        return round(float(x), 2) if x is not None else None
    except (TypeError, ValueError):
        return None


def _cr(row: dict) -> dict:
    inner = row.get("consolidatedReport")
    return inner if isinstance(inner, dict) else row


def build_geozone_visits(visits: Any, name_map: Optional[dict] = None,
                         limit: int = 5000) -> dict:
    """Форма «Посещение геозон»: таблица визитов (ТС/геозона/вход/выход/время/пробег)
    + сводка по геозонам. Источник — `fact_visit` (`geozones_report`)."""
    name_map = name_map or {}
    rows: list[dict] = []
    for v in visits or []:
        tid = str(v.get("vehicleId") or v.get("id") or "")
        geo = v.get("geoInfo") or {}
        mv = v.get("mv") or {}
        start = int(geo.get("startDate") or 0)
        dur = int(geo.get("duration") or 0)
        rows.append({
            "vehicle_id": tid,
            "vehicle": name_map.get(tid) or tid,
            "geozone": v.get("geozoneName") or "",
            "enter_ts": start or None,
            "exit_ts": (start + dur) if start else None,
            "duration_s": dur,
            "max_speed_kmh": _num(mv.get("maxSpeed")),
            "mileage_km": _num(mv.get("mileage")),
            "speeding_km": _num(mv.get("mileageSpeeding")),
        })
    rows.sort(key=lambda r: r["enter_ts"] or 0, reverse=True)

    by_geo: dict[str, dict] = {}
    for r in rows:
        g = by_geo.setdefault(r["geozone"], {"geozone": r["geozone"], "visits": 0,
                                             "vehicles": set(), "total_s": 0})
        g["visits"] += 1
        g["vehicles"].add(r["vehicle_id"])
        g["total_s"] += r["duration_s"]
    summary = sorted(
        ({"geozone": g["geozone"], "visits": g["visits"],
          "vehicles": len(g["vehicles"]), "total_hours": round(g["total_s"] / 3600, 1)}
         for g in by_geo.values()),
        key=lambda x: -x["visits"])
    return {"count": len(rows), "rows": rows[:limit], "by_geozone": summary[:300]}


def build_violations(violations: Any, vehicles: Any = None,
                     name_map: Optional[dict] = None) -> dict:
    """Форма «Нарушения»: единая таблица нарушений по парку. Геозонные превышения
    (детально, со статьёй КоАП/ставкой СТ КАП) + агрегатный флаг превышения скорости
    для ТС без геозонной детализации. Источник — `speeding.detect_from_visits` + агрегат."""
    name_map = name_map or {}
    by_v = {str(v.vehicle_id): v for v in (vehicles or [])}
    rows: list[dict] = []
    for tid, vios in (violations or {}).items():
        for vio in vios or []:
            rows.append({
                "vehicle_id": str(tid),
                "vehicle": name_map.get(str(tid)) or str(tid),
                "type": "Превышение в геозоне",
                "geozone": getattr(vio, "geozone", None),
                "limit_kmh": getattr(vio, "limit", None),
                "max_speed_kmh": _num(getattr(vio, "max_speed", None)),
                "excess_kmh": _num(getattr(vio, "excess", None)),
                "start_ts": getattr(vio, "start_ts", None) or None,
                "severity": getattr(vio, "st_kap_severity", None),
                "koap_article": getattr(vio, "koap_article", None),
                "fine_kzt": getattr(vio, "fine_kzt", None),
            })
    seen = set(str(t) for t in (violations or {}))
    for tid, v in by_v.items():                     # агрегатный флаг для ТС без геозон-детализации
        if (getattr(v, "speeding_count", 0) or 0) > 0 and tid not in seen:
            rows.append({
                "vehicle_id": tid, "vehicle": v.name, "type": "Превышение скорости",
                "geozone": None, "limit_kmh": None,
                "max_speed_kmh": _num(getattr(v, "max_speed_kmh", None)),
                "excess_kmh": None, "start_ts": None,
                "detail": f"{v.speeding_count} эпизодов, {_num(v.speeding_mileage_km)} км",
                "severity": None, "koap_article": None, "fine_kzt": None,
            })
    rows.sort(key=lambda r: (r.get("fine_kzt") or 0, r.get("excess_kmh") or 0), reverse=True)
    by_type: dict[str, int] = {}
    for r in rows:
        by_type[r["type"]] = by_type.get(r["type"], 0) + 1
    return {"count": len(rows), "rows": rows[:5000], "by_type": by_type}


def build_fuel(vehicles: Any) -> dict:
    """Форма «Топливо» (объединяет Заправки/Сливы, Выдачу, Объём бака — kb-14):
    суточные значения из fuel-блока сводного. Заправки/выдача — confident; слив —
    измеренный Omnicomm объём (нейтрально «слив, л», без обвинительной квалификации,
    бизнес-инвариант о «возможных сливах» соблюдён — это факт-замер, не спекуляция)."""
    rows: list[dict] = []
    tot_refuel = tot_delivery = 0.0
    for v in vehicles or []:
        refuel = getattr(v, "refuel_l", None)
        drain = getattr(v, "drain_l", None)
        delivery = getattr(v, "delivery_l", None)
        vend = getattr(v, "vol_end_l", None)
        if not any(x for x in (refuel, drain, delivery, vend)):
            continue                                    # без топливных данных — пропуск
        tot_refuel += refuel or 0
        tot_delivery += delivery or 0
        rows.append({
            "vehicle_id": str(v.vehicle_id),
            "vehicle": v.name,
            "refuel_l": _num(refuel),
            "drain_l": _num(drain),
            "delivery_l": _num(delivery),
            "fuel_l": _num(getattr(v, "fuel_l", None)),
            "vol_start_l": _num(getattr(v, "vol_start_l", None)),
            "vol_end_l": _num(vend),
            "vol_min_l": _num(getattr(v, "vol_min_l", None)),
            "vol_max_l": _num(getattr(v, "vol_max_l", None)),
        })
    rows.sort(key=lambda r: (r["refuel_l"] or 0) + (r["delivery_l"] or 0), reverse=True)
    # «слив» (drain_l) оставлен в строках для прозрачности, но НЕ в итогах: поле Omnicomm
    # `draining` по факту ловит шум ДУТ (на парке слив > заправок — физически невозможно),
    # бизнес-инвариант запрещает выводить «сливы» как обвинение (помечаем «требует проверки» в UI).
    return {"count": len(rows), "rows": rows[:5000],
            "totals": {"refuel_l": round(tot_refuel, 1), "delivery_l": round(tot_delivery, 1)}}


def build_fleet_table(vehicles: Any, vehicle_org: Optional[dict] = None) -> dict:
    """Форма «Сводный / Работа группы» (посуточный итог по ТС): все метрики агрегата
    одной таблицей — пробег, топливо, моточасы, режимы, превышения. Источник — `VehicleMetrics`."""
    org = vehicle_org or {}
    rows: list[dict] = []
    for v in vehicles or []:
        tid = str(v.vehicle_id)
        rows.append({
            "vehicle_id": tid,
            "vehicle": v.name,
            "org_id": org.get(tid),
            "mileage_km": _num(getattr(v, "mileage_km", None)),
            "fuel_l": _num(getattr(v, "fuel_l", None)),
            "fuel_per_100km": _num(getattr(v, "fuel_per_100km", None)),
            "fuel_idle_l": _num(getattr(v, "fuel_idle_l", None)),
            "engine_hours": _num(getattr(v, "engine_hours", None)),
            "engine_idle_hours": _num(getattr(v, "engine_idle_hours", None)),
            "max_speed_kmh": _num(getattr(v, "max_speed_kmh", None)),
            "speeding_count": getattr(v, "speeding_count", None),
            "speeding_mileage_km": _num(getattr(v, "speeding_mileage_km", None)),
            "has_data": bool(getattr(v, "has_data", False)),
        })
    rows.sort(key=lambda r: r["mileage_km"] or 0, reverse=True)
    return {"count": len(rows), "rows": rows}
