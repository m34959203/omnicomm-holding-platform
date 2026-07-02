"""Персистентный стор комплектов шин — план (ресурс/стоимость) + цикл (установка).

Отдельная SQLite `data/cache/tyres.db` (как `raw_store`/`layouts_store`): переживает
рестарт, не в снапшоте. Хранит на ТС: ресурс комплекта, стоимость, дату установки
текущего цикла и метаданные (бренд/размер) + журнал замен.

Дефолт (нет строки) — план по классу из `config`, установка «от нуля» (T0 = начало
архива). Подтверждение замены (`replace`) пишет новый `installed_ts` → сброс пробега.
"""

from __future__ import annotations

import os
import sqlite3
from typing import Optional

from omnicomm_report.tyres import TyrePlan, TyreState

DEFAULT_PATH = "data/cache/tyres.db"

_DDL = """
CREATE TABLE IF NOT EXISTS tyre_set (
    terminal_id      TEXT PRIMARY KEY,
    resource_km      REAL,
    cost_kzt         REAL,
    remind_before_km REAL,
    installed_ts     INTEGER,
    brand            TEXT,
    size             TEXT,
    updated_at       INTEGER
);
CREATE TABLE IF NOT EXISTS tyre_change (
    terminal_id  TEXT NOT NULL,
    changed_ts   INTEGER NOT NULL,
    km_at_change REAL,
    note         TEXT,
    PRIMARY KEY (terminal_id, changed_ts)
);
"""


def _connect(path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_DDL)
    return conn


def get_all(path: str = DEFAULT_PATH) -> dict[str, dict]:
    """{terminal_id -> строка стора} для всех ТС с заведённым комплектом."""
    if not os.path.exists(path):
        return {}
    with _connect(path) as conn:
        rows = conn.execute("SELECT * FROM tyre_set").fetchall()
    return {str(r["terminal_id"]): dict(r) for r in rows}


def set_plan(
    terminal_id: str, *, resource_km: Optional[float] = None,
    cost_kzt: Optional[float] = None, remind_before_km: Optional[float] = None,
    installed_ts: Optional[int] = None, brand: Optional[str] = None,
    size: Optional[str] = None, updated_at: int = 0, path: str = DEFAULT_PATH,
) -> None:
    """Upsert плана/цикла комплекта (частичный — не затирает незаданные поля)."""
    tid = str(terminal_id)
    with _connect(path) as conn:
        cur = conn.execute("SELECT * FROM tyre_set WHERE terminal_id=?", (tid,)).fetchone()
        old = dict(cur) if cur else {}
        row = {
            "resource_km": resource_km if resource_km is not None else old.get("resource_km"),
            "cost_kzt": cost_kzt if cost_kzt is not None else old.get("cost_kzt"),
            "remind_before_km": remind_before_km if remind_before_km is not None
                else old.get("remind_before_km"),
            "installed_ts": installed_ts if installed_ts is not None else old.get("installed_ts"),
            "brand": brand if brand is not None else old.get("brand"),
            "size": size if size is not None else old.get("size"),
            "updated_at": updated_at,
        }
        conn.execute(
            "INSERT INTO tyre_set (terminal_id,resource_km,cost_kzt,remind_before_km,"
            "installed_ts,brand,size,updated_at) VALUES (?,?,?,?,?,?,?,?) "
            "ON CONFLICT(terminal_id) DO UPDATE SET resource_km=excluded.resource_km,"
            "cost_kzt=excluded.cost_kzt,remind_before_km=excluded.remind_before_km,"
            "installed_ts=excluded.installed_ts,brand=excluded.brand,size=excluded.size,"
            "updated_at=excluded.updated_at",
            (tid, row["resource_km"], row["cost_kzt"], row["remind_before_km"],
             row["installed_ts"], row["brand"], row["size"], row["updated_at"]))
        conn.commit()


def replace(terminal_id: str, changed_ts: int, *, km_at_change: Optional[float] = None,
            note: Optional[str] = None, path: str = DEFAULT_PATH) -> None:
    """Подтвердить замену комплекта: новый цикл от `changed_ts` + запись в журнал."""
    tid = str(terminal_id)
    with _connect(path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO tyre_change (terminal_id,changed_ts,km_at_change,note)"
            " VALUES (?,?,?,?)", (tid, int(changed_ts), km_at_change, note))
        # цикл начинается заново: installed_ts = дата замены
        cur = conn.execute("SELECT terminal_id FROM tyre_set WHERE terminal_id=?", (tid,)).fetchone()
        if cur:
            conn.execute("UPDATE tyre_set SET installed_ts=?,updated_at=? WHERE terminal_id=?",
                         (int(changed_ts), int(changed_ts), tid))
        else:
            conn.execute("INSERT INTO tyre_set (terminal_id,installed_ts,updated_at)"
                         " VALUES (?,?,?)", (tid, int(changed_ts), int(changed_ts)))
        conn.commit()


def history(terminal_id: str, path: str = DEFAULT_PATH) -> list[dict]:
    """Журнал замен по ТС (свежие сверху)."""
    if not os.path.exists(path):
        return []
    with _connect(path) as conn:
        rows = conn.execute(
            "SELECT * FROM tyre_change WHERE terminal_id=? ORDER BY changed_ts DESC",
            (str(terminal_id),)).fetchall()
    return [dict(r) for r in rows]


def plan_state_for(row: Optional[dict], *, terminal_id: str, resource_km: float,
                   cost_kzt: float, remind_before_km: float) -> tuple[TyrePlan, TyreState]:
    """Построить (TyrePlan, TyreState) из строки стора + дефолтов класса ТС."""
    row = row or {}
    plan = TyrePlan(
        terminal_id=str(terminal_id),
        resource_km=row.get("resource_km") or resource_km,
        cost_kzt=row.get("cost_kzt") if row.get("cost_kzt") is not None else cost_kzt,
        remind_before_km=row.get("remind_before_km") or remind_before_km,
        brand=row.get("brand"), size=row.get("size"),
    )
    state = TyreState(terminal_id=str(terminal_id), installed_ts=row.get("installed_ts"))
    return plan, state
