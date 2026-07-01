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
from datetime import datetime
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


_VIEW_DAYS = 30   # штатное окно дашборда (совпадает с config.VIEW_WINDOW_DAYS)


def _period_span_end(period_key: str) -> tuple[int, int]:
    """(end_epoch_day, span_days) из ключа `YYYY-MM-DD_YYYY-MM-DD`; (0,0) если не разобрать."""
    try:
        a, b = period_key.split("_")
        da = datetime.strptime(a, "%Y-%m-%d")
        db = datetime.strptime(b, "%Y-%m-%d")
        return int(db.timestamp() // 86400), max(1, (db - da).days)
    except (ValueError, AttributeError):
        return (0, 0)


def latest_snapshot(*, path: str = DEFAULT_PATH) -> Optional[dict]:
    """Снапшот для ДЕФОЛТА дашборда: самый свежий по КОНЦУ периода (самые новые данные),
    среди равных — длиной ближе к штатному окну (30 дн). НЕ «последний записанный по
    synced_at» — иначе короткие backfill-снимки (2-дн исторические окна) перехватывали
    бы дефолт и занижали число ТС/пустой fleet_table."""
    conn = _connect(path)
    try:
        keys = conn.execute("SELECT period_key, synced_at FROM snapshot").fetchall()
        if not keys:
            return None
        def score(r):
            end, span = _period_span_end(r["period_key"])
            return (end, -abs(span - _VIEW_DAYS), r["synced_at"])
        best = max(keys, key=score)["period_key"]
        row = conn.execute(
            "SELECT period_key, payload, synced_at, label FROM snapshot WHERE period_key=?",
            (best,)).fetchone()
    finally:
        conn.close()
    return _row_to_snapshot(row, row["period_key"]) if row else None


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
