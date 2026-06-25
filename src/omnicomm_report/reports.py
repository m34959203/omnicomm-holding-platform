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
