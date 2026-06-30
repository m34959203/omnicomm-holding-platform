"""Помесячная повторяемость превышений (вкладка «Повторяемость / Тренд»).

Переносит страницы 3–4 Power BI «Мониторинг скоростного режима» в technokod:
матрица ТС × месяц по числу эпизодов превышения, с гибкими порогами
(длительность ≥ N сек, величина превышения от–до км/ч).

Источник — локальный архив визитов геозон (`raw_store.fact_visit`): эпизоды
детектируются тем же движком, что и живая форма «Нарушения»
(`speeding.detect_from_visits`, лимит из имени геозоны), но за ПРОИЗВОЛЬНЫЙ
многомесячный диапазон. Скоуп ДЗО и метрика (эпизоды/на ТС/доля) считаются
на фронте по `vehicle_org` + дереву — как у остальных вкладок.
"""

from __future__ import annotations

import datetime as dt
from typing import Optional

from omnicomm_report import speeding

from . import raw_store

_UTC = dt.timezone.utc


def _month(ts: int) -> str:
    return dt.datetime.fromtimestamp(int(ts), _UTC).strftime("%Y-%m")


def _parse_day(iso: Optional[str], fallback_ts: int) -> int:
    if not iso:
        return fallback_ts
    try:
        return int(dt.datetime.strptime(iso, "%Y-%m-%d").replace(tzinfo=_UTC).timestamp())
    except ValueError:
        return fallback_ts


def _month_span(start_ts: int, end_ts: int) -> list[str]:
    """Список месяцев YYYY-MM от start до end включительно (по календарю)."""
    a = dt.datetime.fromtimestamp(start_ts, _UTC).replace(day=1)
    b = dt.datetime.fromtimestamp(end_ts, _UTC)
    out: list[str] = []
    cur = a
    while cur <= b:
        out.append(cur.strftime("%Y-%m"))
        cur = (cur.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    return out


def build_speed_trend(
    *, from_iso: Optional[str] = None, to_iso: Optional[str] = None,
    min_duration_s: int = 0, min_excess: float = 0.0, max_excess: float = 999.0,
    raw_path: str = raw_store.DEFAULT_PATH,
) -> dict:
    cov = raw_store.coverage(raw_path)
    end_ts = _parse_day(to_iso, int(cov.get("date_max") or 0) or int(dt.datetime.now(_UTC).timestamp()))
    # дефолт «от» — 4 календарных месяца назад от конца окна.
    default_from = int((dt.datetime.fromtimestamp(end_ts, _UTC).replace(day=1)
                        - dt.timedelta(days=95)).replace(day=1).timestamp())
    start_ts = _parse_day(from_iso, default_from)
    if start_ts > end_ts:
        start_ts, end_ts = end_ts, start_ts

    visits = raw_store.load_visits(start_ts, end_ts, raw_path)
    names: dict[str, str] = {}
    for v in visits:
        tid = v.get("vehicleId") or v.get("id")
        if tid is not None and v.get("vehicleName"):
            names.setdefault(str(tid), v["vehicleName"])

    viol = speeding.detect_from_visits(visits, seed=None)

    months = _month_span(start_ts, end_ts)
    mset = set(months)
    rows: list[dict] = []
    total: dict[str, int] = {m: 0 for m in months}
    grand = 0

    for tid, episodes in viol.items():
        by_month: dict[str, int] = {}
        for e in episodes:
            if e.duration_s < min_duration_s:
                continue
            if not (min_excess <= e.excess <= max_excess):
                continue
            m = _month(e.start_ts)
            if m not in mset:
                continue
            by_month[m] = by_month.get(m, 0) + 1
        cnt = sum(by_month.values())
        if not cnt:
            continue
        for m, c in by_month.items():
            total[m] += c
        grand += cnt
        rows.append({
            "vehicleId": tid, "name": names.get(tid, tid),
            "byMonth": by_month, "all": cnt,
        })

    rows.sort(key=lambda r: r["all"], reverse=True)
    total["all"] = grand
    vals = [r["all"] for r in rows]
    cell_vals = sorted(c for r in rows for c in r["byMonth"].values())
    heat = {
        "min": cell_vals[0] if cell_vals else 0,
        "p50": cell_vals[len(cell_vals) // 2] if cell_vals else 0,
        "max": cell_vals[-1] if cell_vals else 0,
    }

    return {
        "months": months,
        "rows": rows,
        "total": total,
        "heat": heat,
        "vehicles": len(rows),
        "episodes": grand,
        "from": dt.datetime.fromtimestamp(start_ts, _UTC).strftime("%Y-%m-%d"),
        "to": dt.datetime.fromtimestamp(end_ts, _UTC).strftime("%Y-%m-%d"),
        "params": {"minDurationSec": min_duration_s, "minExcess": min_excess, "maxExcess": max_excess},
        "source": "archive",
        "max_all": vals[0] if vals else 0,
    }
