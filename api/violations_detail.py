"""Детальная таблица нарушений скорости (per-episode) — стр.2 Power BI.

Колонки: Дата/время · ТС · Локация (геозона) · Длительность, с · Средняя
скорость · Макс · Допустимая · Превышение · Штраф ₸. Сортировка по средней
скорости ↓ (как в Power BI).

Источник — архив визитов `raw_store.fact_visit` за период: те же лимит/дорога/
КоАП, что в живой форме «Нарушения», плюс `mv.averageSpeed` и `geoInfo.duration`,
которых нет в snapshot-форме. Считается on-demand (без пересборки снимка).
Скоуп ДЗО — на фронте по vehicle_org. Пороги — те же, что у «Повторяемости».
"""

from __future__ import annotations

import datetime as dt
from typing import Optional

from omnicomm_report import geozones as gz, speeding

from . import raw_store

_UTC = dt.timezone.utc
CAP = 6000   # максимум строк в ответе (после сортировки по ср. скорости)


def _parse_day(iso: Optional[str], fallback_ts: int) -> int:
    if not iso:
        return fallback_ts
    try:
        return int(dt.datetime.strptime(iso, "%Y-%m-%d").replace(tzinfo=_UTC).timestamp())
    except ValueError:
        return fallback_ts


def build_violations_detail(
    *, from_iso: Optional[str] = None, to_iso: Optional[str] = None,
    min_duration_s: int = 0, min_excess: float = 0.0, max_excess: float = 999.0,
    allowed: Optional[set] = None,   # None → все ТС; set → только эти terminal_id (скоуп ДЗО)
    raw_path: str = raw_store.DEFAULT_PATH,
) -> dict:
    cov = raw_store.coverage(raw_path)
    end_ts = _parse_day(to_iso, int(cov.get("date_max") or 0) or int(dt.datetime.now(_UTC).timestamp()))
    default_from = end_ts - 30 * 86400
    start_ts = _parse_day(from_iso, default_from)
    if start_ts > end_ts:
        start_ts, end_ts = end_ts, start_ts

    visits = raw_store.load_visits(start_ts, end_ts, raw_path)
    cat = gz.categorize_vehicle
    rows: list[dict] = []

    for v in visits:
        if not isinstance(v, dict):
            continue
        tid0 = str(v.get("vehicleId") or v.get("id") or "")
        if allowed is not None and tid0 not in allowed:
            continue
        name = v.get("geozoneName") or ""
        mv = v.get("mv") or {}
        mx = mv.get("maxSpeed")
        if not name or mx is None or mx <= 0:
            continue
        if (mv.get("mileage") or 0) <= 0:       # не двигался в зоне → выброс
            continue
        gl = gz.geozone_limit(name, cat(v.get("vehicleName", "")), None)
        if float(mx) <= gl.limit:
            continue
        excess = round(float(mx) - gl.limit, 1)
        if excess < min_excess or excess > max_excess:
            continue
        geo = v.get("geoInfo") or {}
        dur = int(geo.get("duration") or 0)
        if dur < min_duration_s:
            continue
        # mv.averageSpeed бывает пустым (~half) или мусорным (avg>max — невозможно физически)
        # → валидна только 0 < avg ≤ max, иначе «—» (вентиль доверия к данным).
        av = mv.get("averageSpeed")
        avg = (round(float(av), 1)
               if av is not None and 0 < float(av) <= float(mx) + 0.5 else None)
        article, fine = (speeding.koap_for(excess) if gl.public_road else (None, None))
        rows.append({
            "vehicleId": str(v.get("vehicleId") or v.get("id") or ""),
            "vehicle": v.get("vehicleName") or "",
            "geozone": name,
            "limit_kmh": gl.limit,
            "avg_speed_kmh": round(float(avg), 1) if avg is not None else None,
            "max_speed_kmh": round(float(mx), 1),
            "excess_kmh": excess,
            "duration_s": dur,
            "start_ts": int(geo.get("startDate") or 0),
            "public_road": gl.public_road,
            "severity": speeding.st_kap_severity(excess),
            "koap_article": article,
            "fine_kzt": fine,
        })

    total = len(rows)
    # Серверные агрегаты по ПОЛНОМУ списку (до среза) — чтобы KPI/тяжесть/зоны не
    # занижались усечением rows[:CAP] (BUG-1). Тяжесть — по величине превышения.
    severity = {"s6": 0, "s20": 0, "s40": 0}
    zmap: dict = {}
    vmap: dict = {}   # ТС → счётчики по корзинам тяжести (для дрилла клика по «Тяжести»)
    for r in rows:
        e = r["excess_kmh"]
        bucket = "s40" if e >= 40 else "s20" if e >= 20 else "s6"
        severity[bucket] += 1
        z = zmap.setdefault(r["geozone"], {"name": r["geozone"], "limit": r["limit_kmh"],
                                           "max": 0.0, "events": 0})
        z["events"] += 1
        z["max"] = max(z["max"], r["max_speed_kmh"])   # АБСОЛЮТНАЯ макс. скорость (BUG-4)
        vm = vmap.setdefault(r["vehicleId"], {
            "vehicleId": r["vehicleId"], "vehicle": r["vehicle"],
            "s6": 0, "s20": 0, "s40": 0, "total": 0, "max_excess": 0.0})
        vm[bucket] += 1
        vm["total"] += 1
        vm["max_excess"] = max(vm["max_excess"], e)
    zones = sorted(zmap.values(), key=lambda z: z["events"], reverse=True)[:12]
    # Список ТС по корзинам тяжести (точный, до среза rows) — для клика по «Тяжести».
    by_vehicle = sorted(vmap.values(), key=lambda v: (v["s40"], v["s20"], v["total"]), reverse=True)

    rows.sort(key=lambda r: (r["avg_speed_kmh"] if r["avg_speed_kmh"] is not None else r["max_speed_kmh"]), reverse=True)
    return {
        "rows": rows[:CAP],
        "total": total,
        "returned": min(total, CAP),
        "capped": total > CAP,
        "severity": severity,
        "by_vehicle": by_vehicle,
        "zones": zones,
        "from": dt.datetime.fromtimestamp(start_ts, _UTC).strftime("%Y-%m-%d"),
        "to": dt.datetime.fromtimestamp(end_ts, _UTC).strftime("%Y-%m-%d"),
        "params": {"minDurationSec": min_duration_s, "minExcess": min_excess, "maxExcess": max_excess},
        "source": "archive",
    }
