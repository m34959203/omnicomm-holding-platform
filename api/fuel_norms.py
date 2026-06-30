"""Топливо «Работа группы по ТС» + нормы расхода (P2.2 / Omnicomm «Посменный»).

Per-vehicle за период из суточного консолидата (`raw_store.fact_daily`):
пробег · моточасы · факт л/100 · норма л/100 · отклонение · перерасход/экономия л ·
заправки · сливы. Норма берётся из Omnicomm (`fuel.normCons100`, задана у части ТС).

Вентиль доверия (как у ₸/км): факт л/100 считаем только для ТРАНСПОРТА с реальным
пробегом — у не-ТС (АТЗ/ёмкости/генераторы) и моточасной спецтехники «fuel/≈0 км»
даёт абсурд. Где норма/факт недостоверны → null («—» на фронте). ₸ считает фронт
по цене ГСМ. Посменный разрез не делаем: графика смен в данных нет.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from typing import Optional

from omnicomm_report import classify

from . import raw_store

_UTC = dt.timezone.utc
MIN_KM = 100.0     # ниже — пробег незначим, л/100 недостоверен
MAX_L100 = 250.0   # выше — АТЗ/ёмкости/моточасная техника (не реальный расход на 100 км)
CAP = 4000


def _parse_day(iso: Optional[str], fallback_ts: int) -> int:
    if not iso:
        return fallback_ts
    try:
        return int(dt.datetime.strptime(iso, "%Y-%m-%d").replace(tzinfo=_UTC).timestamp())
    except ValueError:
        return fallback_ts


def build_fuel_norms(
    *, from_iso: Optional[str] = None, to_iso: Optional[str] = None,
    raw_path: str = raw_store.DEFAULT_PATH,
) -> dict:
    cov = raw_store.coverage(raw_path)
    end_ts = _parse_day(to_iso, int(cov.get("date_max") or 0) or int(dt.datetime.now(_UTC).timestamp()))
    start_ts = _parse_day(from_iso, end_ts - 30 * 86400)
    if start_ts > end_ts:
        start_ts, end_ts = end_ts, start_ts

    daily = raw_store.load_daily(start_ts, end_ts, raw_path)
    agg: dict = defaultdict(lambda: {
        "name": None, "mil": 0.0, "fuel": 0.0, "worked_s": 0.0,
        "refuel": 0.0, "drain": 0.0, "delivery": 0.0, "norm": 0.0,
    })
    for r in daily:
        cr = r.get("consolidatedReport") if isinstance(r.get("consolidatedReport"), dict) else r
        tid = str(cr.get("vehicleId") or cr.get("id") or r.get("terminal_id") or "")
        if not tid:
            continue
        mv = cr.get("mv") or {}
        fu = cr.get("fuel") or {}
        a = agg[tid]
        if cr.get("vehicleName"):
            a["name"] = cr["vehicleName"]
        a["mil"] += float(mv.get("mileage") or 0)
        a["fuel"] += float(fu.get("fuelConsumption") or 0)
        a["worked_s"] += float(mv.get("worked") or 0)
        a["refuel"] += float(fu.get("refuelling") or 0)
        a["drain"] += float(fu.get("draining") or 0)
        a["delivery"] += float(fu.get("delivery") or 0)
        nc = fu.get("normCons100") or 0
        if nc and float(nc) > 0:
            a["norm"] = max(a["norm"], float(nc))   # норма константна — берём заданное значение

    rows: list[dict] = []
    with_norm = 0
    for tid, a in agg.items():
        name = a["name"] or tid
        transport = classify.is_transport(name)
        mil = a["mil"]
        # факт л/100 достоверен только для транспорта с реальным пробегом (вентиль доверия).
        # Верхний кап MAX_L100: значения выше — топливозаправщики/ёмкости (fuelConsumption =
        # выданное топливо) или моточасная техника, где л/100 бессмыслен → «—».
        rate_ok = transport and mil >= MIN_KM and a["fuel"] > 0
        fact = round(a["fuel"] / mil * 100, 1) if rate_ok else None
        if fact is not None and fact > MAX_L100:
            fact = None
        # норма Omnicomm — СПРАВОЧНО (неутверждённая); вердикт перерасхода НЕ выводим
        # (бизнес-инвариант: перерасход не утверждать без согласованных норм).
        norm = round(a["norm"], 1) if a["norm"] > 0 else None
        if norm is not None:
            with_norm += 1
        rows.append({
            "vehicleId": tid, "vehicle": name, "transport": transport,
            "mileage_km": round(mil), "moto_h": round(a["worked_s"] / 3600, 1),
            "fuel_l": round(a["fuel"]), "fact_l100": fact, "norm_l100": norm,
            "refuel_l": round(a["refuel"]), "drain_l": round(a["drain"]),
            "delivery_l": round(a["delivery"]),
        })

    # сортировка по пробегу: реальные операционные ТС вверх, АТЗ/ёмкости (низкий пробег) вниз
    rows.sort(key=lambda r: r["mileage_km"], reverse=True)
    total = len(rows)
    return {
        "rows": rows[:CAP], "total": total, "returned": min(total, CAP), "capped": total > CAP,
        "with_norm": with_norm,
        "from": dt.datetime.fromtimestamp(start_ts, _UTC).strftime("%Y-%m-%d"),
        "to": dt.datetime.fromtimestamp(end_ts, _UTC).strftime("%Y-%m-%d"),
        "shifts_available": False,   # графика смен нет → посменный разрез недоступен
        "source": "archive",
    }
