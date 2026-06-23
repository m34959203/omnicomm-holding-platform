"""Сырое хранилище суточных данных — основа инкрементального синка.

Храним суточные строки `consolidatedReport` (одна на ТС×сутки) и визиты геозон.
Это позволяет каждые 3ч довозить ТОЛЬКО свежие сутки (upsert: текущий день
перезаписывается, прошлые — стабильны), а снимок пересобирать из НАКОПЛЕННОГО
за нужное окно, НЕ перезабирая историю из Omnicomm.

Объём скромный: суточный агрегат ~1-2 КБ/ТС → ~1.5 ГБ/год на парк (см. SOLUTION).
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

DEFAULT_PATH = "data/cache/raw.db"

_DDL = """
CREATE TABLE IF NOT EXISTS fact_daily (
    terminal_id TEXT NOT NULL,
    date        INTEGER NOT NULL,
    payload     TEXT NOT NULL,
    PRIMARY KEY (terminal_id, date)
);
CREATE TABLE IF NOT EXISTS fact_visit (
    terminal_id TEXT NOT NULL,
    geozone     TEXT NOT NULL,
    start_date  INTEGER NOT NULL,
    payload     TEXT NOT NULL,
    PRIMARY KEY (terminal_id, geozone, start_date)
);
CREATE INDEX IF NOT EXISTS ix_daily_date ON fact_daily(date);
CREATE INDEX IF NOT EXISTS ix_visit_date ON fact_visit(start_date);
"""


def _connect(path: str) -> sqlite3.Connection:
    Path(os.path.dirname(path) or ".").mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(_DDL)
    return conn


def _cr(row: dict) -> dict:
    inner = row.get("consolidatedReport")
    return inner if isinstance(inner, dict) else row


def upsert_daily(records: Any, path: str = DEFAULT_PATH) -> int:
    """Сохранить суточные строки (upsert по ТС×сутки — текущий день перезаписывается)."""
    n = 0
    with _connect(path) as conn:
        for r in records or []:
            cr = _cr(r)
            tid, date = cr.get("vehicleId") or cr.get("id"), cr.get("date")
            if tid is None or date is None:
                continue
            conn.execute(
                "INSERT OR REPLACE INTO fact_daily(terminal_id,date,payload) VALUES(?,?,?)",
                (str(tid), int(date), json.dumps(r, ensure_ascii=False)))
            n += 1
        conn.commit()
    return n


def load_daily(start_ts: int, end_ts: int, path: str = DEFAULT_PATH) -> list[dict]:
    if not os.path.exists(path):
        return []
    with _connect(path) as conn:
        rows = conn.execute(
            "SELECT payload FROM fact_daily WHERE date>=? AND date<=?",
            (int(start_ts), int(end_ts))).fetchall()
    return [json.loads(r[0]) for r in rows]


def upsert_visits(visits: Any, path: str = DEFAULT_PATH) -> int:
    """Сохранить визиты геозон (upsert по ТС×геозона×начало визита)."""
    n = 0
    with _connect(path) as conn:
        for v in visits or []:
            tid = v.get("vehicleId") or v.get("id")
            sd = (v.get("geoInfo") or {}).get("startDate")
            if tid is None or sd is None:
                continue
            conn.execute(
                "INSERT OR REPLACE INTO fact_visit(terminal_id,geozone,start_date,payload) VALUES(?,?,?,?)",
                (str(tid), str(v.get("geozoneName") or ""), int(sd),
                 json.dumps(v, ensure_ascii=False)))
            n += 1
        conn.commit()
    return n


def load_visits(start_ts: int, end_ts: int, path: str = DEFAULT_PATH) -> list[dict]:
    if not os.path.exists(path):
        return []
    with _connect(path) as conn:
        rows = conn.execute(
            "SELECT payload FROM fact_visit WHERE start_date>=? AND start_date<=?",
            (int(start_ts), int(end_ts))).fetchall()
    return [json.loads(r[0]) for r in rows]


def coverage(path: str = DEFAULT_PATH) -> dict:
    """Диагностика покрытия: сколько суточных строк/визитов и за какой диапазон."""
    if not os.path.exists(path):
        return {"daily_rows": 0, "visit_rows": 0, "date_min": None, "date_max": None}
    with _connect(path) as conn:
        d = conn.execute("SELECT COUNT(*),MIN(date),MAX(date) FROM fact_daily").fetchone()
        v = conn.execute("SELECT COUNT(*) FROM fact_visit").fetchone()
    return {"daily_rows": d[0], "date_min": d[1], "date_max": d[2], "visit_rows": v[0]}


def prune_before(cutoff_ts: int, path: str = DEFAULT_PATH) -> int:
    """Удалить данные старше cutoff (ретеншн). Возвращает число удалённых суточных строк."""
    if not os.path.exists(path):
        return 0
    with _connect(path) as conn:
        n = conn.execute("DELETE FROM fact_daily WHERE date < ?", (int(cutoff_ts),)).rowcount
        conn.execute("DELETE FROM fact_visit WHERE start_date < ?", (int(cutoff_ts),))
        conn.commit()
    return n
