"""Снапшот-кэш дашборда (SQLite): синк пишет, чтения читают мгновенно.

Корень «висит 5 минут»: каждый заход дёргал Omnicomm заново (40 батчей ×
throttle). Решение — синк ОДИН раз считает готовый снапшот (KPI-дерево +
экономика + рекомендации + геозоны) и кладёт сюда; все чтения фронта берут
готовый JSON из этой таблицы и не трогают Omnicomm.

Ключ снапшота — `period_key` (напр. `"2026-06-15_2026-06-22"`); upsert по нему,
поэтому повторный синк того же периода обновляет, а не плодит строки.
"""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any, Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshot (
    period_key TEXT PRIMARY KEY,
    label      TEXT NOT NULL DEFAULT '',
    synced_at  INTEGER NOT NULL,
    payload    TEXT NOT NULL
);
"""

DEFAULT_PATH = "data/cache/snapshots.db"


def _connect(path: str) -> sqlite3.Connection:
    import os
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute(_SCHEMA)
    return conn


def save_snapshot(payload: dict[str, Any], *, period_key: str, label: str = "",
                  path: str = DEFAULT_PATH, synced_at: Optional[int] = None) -> int:
    """Upsert снапшота по `period_key`. Возвращает `synced_at` (unix, сек)."""
    ts = int(synced_at if synced_at is not None else time.time())
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    conn = _connect(path)
    try:
        conn.execute(
            "INSERT INTO snapshot(period_key,label,synced_at,payload) "
            "VALUES(?,?,?,?) ON CONFLICT(period_key) DO UPDATE SET "
            "label=excluded.label, synced_at=excluded.synced_at, payload=excluded.payload",
            (period_key, label, ts, body))
        conn.commit()
    finally:
        conn.close()
    return ts


def load_snapshot(period_key: str, *, path: str = DEFAULT_PATH) -> Optional[dict]:
    """Снапшот по ключу периода (или None)."""
    conn = _connect(path)
    try:
        row = conn.execute(
            "SELECT payload, synced_at, label FROM snapshot WHERE period_key=?",
            (period_key,)).fetchone()
    finally:
        conn.close()
    return _row_to_snapshot(row, period_key)


def latest_snapshot(*, path: str = DEFAULT_PATH) -> Optional[dict]:
    """Самый свежий снапшот (по `synced_at`), или None — если кэш пуст."""
    conn = _connect(path)
    try:
        row = conn.execute(
            "SELECT period_key, payload, synced_at, label FROM snapshot "
            "ORDER BY synced_at DESC LIMIT 1").fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return _row_to_snapshot(row, row["period_key"])


def list_snapshots(*, path: str = DEFAULT_PATH) -> list[dict]:
    """Метаданные всех снапшотов (без payload) — для выбора периода во фронте."""
    conn = _connect(path)
    try:
        rows = conn.execute(
            "SELECT period_key, label, synced_at FROM snapshot "
            "ORDER BY synced_at DESC").fetchall()
    finally:
        conn.close()
    return [{"period_key": r["period_key"], "label": r["label"],
             "synced_at": r["synced_at"]} for r in rows]


def _row_to_snapshot(row: Optional[sqlite3.Row], period_key: str) -> Optional[dict]:
    if row is None:
        return None
    data = json.loads(row["payload"])
    data["_meta"] = {"period_key": period_key, "synced_at": row["synced_at"],
                     "label": row["label"]}
    return data
