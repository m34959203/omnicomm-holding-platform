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
import json
import os
from collections import defaultdict
from typing import Optional

from omnicomm_report import classify, geozones

from . import raw_store

_UTC = dt.timezone.utc
MIN_KM = 100.0     # ниже — пробег незначим, л/100 недостоверен
MAX_L100 = 130.0   # выше — АТЗ/ёмкости/моточасная техника (не реальный расход на 100 км)
MIN_MH = 20.0      # ниже — моточасов мало, л/мч недостоверен
MAX_LMH = 80.0     # выше — расход на моточас загрязнён (АТЗ/выдача)
OVER_NORM_MULT = 2.5   # перерасход считаем только если факт ≤ K×нормы (иначе данные ТС шумные)
CAP = 4000

# Дефолтные предварительные нормы по категории — фолбэк, если нет файла.
DEFAULT_CATEGORY_NORMS = {"light": 14.0, "bus": 30.0, "truck": 42.0}        # л/100 км (дорожная)
DEFAULT_CATEGORY_NORMS_MH = {"light": 4.0, "bus": 10.0, "truck": 18.0}      # л/мч (моточасная)
NORMS_FILE = "data/fuel_norms.json"
OMNI_NORM_MIN, OMNI_NORM_MAX = 5.0, 150.0     # коридор правдоподобности нормы л/100 из Omnicomm
OMNI_MH_MIN, OMNI_MH_MAX = 1.0, 60.0          # коридор правдоподобности нормы л/мч из Omnicomm


def load_norm_book() -> dict:
    """Справочник норм: файл data/fuel_norms.json поверх код-дефолтов (работает без файла)."""
    book = {"approved": False, "version": "default",
            "categories": dict(DEFAULT_CATEGORY_NORMS), "vehicles": {},
            "categories_mh": dict(DEFAULT_CATEGORY_NORMS_MH), "vehicles_mh": {}}
    try:
        if os.path.exists(NORMS_FILE):
            with open(NORMS_FILE, encoding="utf-8") as f:
                raw = json.load(f)
            book["approved"] = bool(raw.get("approved", False))
            book["version"] = raw.get("version", "file")
            book["categories"].update({k: float(v) for k, v in (raw.get("categories") or {}).items()})
            book["vehicles"] = {str(k): float(v) for k, v in (raw.get("vehicles") or {}).items()}
            book["categories_mh"].update({k: float(v) for k, v in (raw.get("categories_mh") or {}).items()})
            book["vehicles_mh"] = {str(k): float(v) for k, v in (raw.get("vehicles_mh") or {}).items()}
    except (OSError, ValueError, TypeError):
        pass
    return book


def _resolve_norm(book: dict, tid: str, name: str, omni: float) -> tuple[Optional[float], str]:
    """Норма л/100 для ТС: справочник(override) → Omnicomm(правдоподобн.) → категория."""
    if tid in book["vehicles"]:
        return book["vehicles"][tid], "справочник"
    if OMNI_NORM_MIN <= omni <= OMNI_NORM_MAX:
        return round(omni, 1), "omnicomm"
    cat = geozones.categorize_vehicle(name).value
    cn = book["categories"].get(cat)
    return (round(cn, 1), "категория") if cn else (None, "—")


def _resolve_norm_mh(book: dict, tid: str, name: str, omni: float) -> tuple[Optional[float], str]:
    """Норма л/мч для моточасной техники: справочник → Omnicomm → категория."""
    if tid in book["vehicles_mh"]:
        return book["vehicles_mh"][tid], "справочник"
    if OMNI_MH_MIN <= omni <= OMNI_MH_MAX:
        return round(omni, 1), "omnicomm"
    cat = geozones.categorize_vehicle(name).value
    cn = book["categories_mh"].get(cat)
    return (round(cn, 1), "категория") if cn else (None, "—")


def _parse_day(iso: Optional[str], fallback_ts: int) -> int:
    if not iso:
        return fallback_ts
    try:
        return int(dt.datetime.strptime(iso, "%Y-%m-%d").replace(tzinfo=_UTC).timestamp())
    except ValueError:
        return fallback_ts


def build_fuel_norms(
    *, from_iso: Optional[str] = None, to_iso: Optional[str] = None,
    allowed: Optional[set] = None,   # None → все ТС; set → только эти terminal_id (скоуп ДЗО)
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
        "refuel": 0.0, "drain": 0.0, "delivery": 0.0, "norm": 0.0, "norm_mh": 0.0,
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
        nmh = fu.get("normConsumptionMH") or 0
        if nmh and float(nmh) > 0:
            a["norm_mh"] = max(a["norm_mh"], float(nmh))

    book = load_norm_book()
    rows: list[dict] = []
    with_norm = 0
    over_l_total = 0.0
    econ_l_total = 0.0
    for tid, a in agg.items():
        if allowed is not None and tid not in allowed:
            continue
        name = a["name"] or tid
        transport = classify.is_transport(name)
        mil = a["mil"]
        # факт л/100 достоверен только для транспорта с реальным пробегом (вентиль доверия).
        # Верхний кап MAX_L100: значения выше — топливозаправщики/ёмкости (fuelConsumption =
        # выданное топливо) или моточасная техника, где л/100 бессмыслен → «—».
        moto_h = a["worked_s"] / 3600
        # --- дорожная норма (л/100) ---
        rate_ok = transport and mil >= MIN_KM and a["fuel"] > 0
        fact = round(a["fuel"] / mil * 100, 1) if rate_ok else None
        if fact is not None and fact > MAX_L100:
            fact = None
        norm, norm_src = _resolve_norm(book, tid, name, a["norm"])
        # --- моточасная норма (л/мч) для спецтехники ---
        mh_ok = transport and moto_h >= MIN_MH and a["fuel"] > 0
        fact_mh = round(a["fuel"] / moto_h, 1) if mh_ok else None
        if fact_mh is not None and fact_mh > MAX_LMH:
            fact_mh = None
        norm_mh, norm_mh_src = _resolve_norm_mh(book, tid, name, a["norm_mh"])
        if norm is not None or norm_mh is not None:
            with_norm += 1

        # перерасход(+)/экономия(−) в ЛИТРАХ. Дорожный режим в приоритете (если факт л/100
        # достоверен), иначе моточасный — для спецтехники без значимого пробега.
        over_l, mode = None, None
        if fact is not None and norm and fact <= OVER_NORM_MULT * norm:
            over_l = round((fact - norm) * mil / 100, 1); mode = "km"
        elif fact_mh is not None and norm_mh and fact_mh <= OVER_NORM_MULT * norm_mh:
            over_l = round((fact_mh - norm_mh) * moto_h, 1); mode = "mh"
        if over_l is not None:
            if over_l > 0:
                over_l_total += over_l
            else:
                econ_l_total += -over_l
        rows.append({
            "vehicleId": tid, "vehicle": name, "transport": transport,
            "mileage_km": round(mil), "moto_h": round(moto_h, 1),
            "fuel_l": round(a["fuel"]),
            "fact_l100": fact, "norm_l100": norm,
            "fact_lmh": fact_mh, "norm_lmh": norm_mh,
            "mode": mode, "norm_src": norm_src if mode != "mh" else norm_mh_src,
            "over_l": over_l,
            "refuel_l": round(a["refuel"]), "drain_l": round(a["drain"]),
            "delivery_l": round(a["delivery"]),
        })

    # сортировка по перерасходу (по убыв.), затем по пробегу
    rows.sort(key=lambda r: (r["over_l"] if r["over_l"] is not None else -1e18, r["mileage_km"]), reverse=True)
    total = len(rows)
    return {
        "rows": rows[:CAP], "total": total, "returned": min(total, CAP), "capped": total > CAP,
        "with_norm": with_norm,
        "over_l_total": round(over_l_total), "economy_l_total": round(econ_l_total),
        "norms_approved": book["approved"], "norms_version": book["version"],
        "from": dt.datetime.fromtimestamp(start_ts, _UTC).strftime("%Y-%m-%d"),
        "to": dt.datetime.fromtimestamp(end_ts, _UTC).strftime("%Y-%m-%d"),
        "shifts_available": False,   # графика смен нет → посменный разрез недоступен
        "source": "archive",
    }
