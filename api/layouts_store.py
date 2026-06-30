"""SQLite-хранилище рабочих столов и шаблонов (Фаза 2).

Таблицы dashboard_layout / dashboard_template. RBAC применяется в роутере
(api/layouts.py) по дереву оргструктуры; здесь — только хранение/выборки.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from typing import Optional

DEFAULT_PATH = os.path.join("data", "layouts.db")
SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS dashboard_layout (
    id TEXT PRIMARY KEY, owner TEXT, org_id TEXT, name TEXT,
    layout_json TEXT NOT NULL, schema_version INTEGER DEFAULT 1,
    is_default INTEGER DEFAULT 0, shared INTEGER DEFAULT 0,
    created_at INTEGER, updated_at INTEGER
);
CREATE INDEX IF NOT EXISTS ix_layout_owner ON dashboard_layout(owner);
CREATE INDEX IF NOT EXISTS ix_layout_org ON dashboard_layout(org_id);
CREATE TABLE IF NOT EXISTS dashboard_template (
    id TEXT PRIMARY KEY, owner TEXT, org_id TEXT, name TEXT, role TEXT,
    description TEXT, layout_json TEXT NOT NULL, schema_version INTEGER DEFAULT 1,
    is_system INTEGER DEFAULT 0, created_at INTEGER, updated_at INTEGER
);
CREATE INDEX IF NOT EXISTS ix_tpl_org ON dashboard_template(org_id);
CREATE TABLE IF NOT EXISTS dashboard_schedule (
    id TEXT PRIMARY KEY, owner TEXT, org_id TEXT, layout_id TEXT, email TEXT NOT NULL,
    frequency TEXT DEFAULT 'daily', hour INTEGER DEFAULT 6, enabled INTEGER DEFAULT 1,
    last_sent INTEGER DEFAULT 0, created_at INTEGER
);
CREATE INDEX IF NOT EXISTS ix_sched_owner ON dashboard_schedule(owner);
"""


def _conn(path: str = DEFAULT_PATH) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    c.executescript(_SCHEMA)
    try:                       # миграция старой БД: добавить колонку shared
        c.execute("ALTER TABLE dashboard_layout ADD COLUMN shared INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    return c


def _now() -> int:
    return int(time.time())


def new_id() -> str:
    return uuid.uuid4().hex[:16]


def _row_layout(r: sqlite3.Row) -> dict:
    keys = r.keys()
    return {"id": r["id"], "owner": r["owner"], "org_id": r["org_id"], "name": r["name"],
            "layout": json.loads(r["layout_json"]), "schema_version": r["schema_version"],
            "is_default": bool(r["is_default"]), "shared": bool(r["shared"]) if "shared" in keys else False,
            "created_at": r["created_at"], "updated_at": r["updated_at"]}


def _row_tpl(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "owner": r["owner"], "org_id": r["org_id"], "name": r["name"],
            "role": r["role"], "description": r["description"], "layout": json.loads(r["layout_json"]),
            "schema_version": r["schema_version"], "is_system": bool(r["is_system"]),
            "created_at": r["created_at"], "updated_at": r["updated_at"]}


# ---- Layouts ----
def list_layouts(path: str = DEFAULT_PATH) -> list[dict]:
    with _conn(path) as c:
        return [_row_layout(r) for r in c.execute("SELECT * FROM dashboard_layout ORDER BY updated_at DESC")]


def get_layout(lid: str, path: str = DEFAULT_PATH) -> Optional[dict]:
    with _conn(path) as c:
        r = c.execute("SELECT * FROM dashboard_layout WHERE id=?", (lid,)).fetchone()
        return _row_layout(r) if r else None


def upsert_layout(*, lid: str, owner: str, org_id: Optional[str], name: str,
                  layout: dict, is_default: bool = False, shared: bool = False,
                  path: str = DEFAULT_PATH) -> dict:
    now = _now()
    with _conn(path) as c:
        exists = c.execute("SELECT created_at FROM dashboard_layout WHERE id=?", (lid,)).fetchone()
        created = exists["created_at"] if exists else now
        if is_default:   # один дефолт на владельца
            c.execute("UPDATE dashboard_layout SET is_default=0 WHERE owner=?", (owner,))
        c.execute("""INSERT INTO dashboard_layout(id,owner,org_id,name,layout_json,schema_version,is_default,shared,created_at,updated_at)
                     VALUES(?,?,?,?,?,?,?,?,?,?)
                     ON CONFLICT(id) DO UPDATE SET name=excluded.name, org_id=excluded.org_id,
                       layout_json=excluded.layout_json, is_default=excluded.is_default,
                       shared=excluded.shared, updated_at=excluded.updated_at""",
                  (lid, owner, org_id, name, json.dumps(layout, ensure_ascii=False),
                   SCHEMA_VERSION, 1 if is_default else 0, 1 if shared else 0, created, now))
    return get_layout(lid, path)


def delete_layout(lid: str, path: str = DEFAULT_PATH) -> None:
    with _conn(path) as c:
        c.execute("DELETE FROM dashboard_layout WHERE id=?", (lid,))


def default_layout(owner: str, path: str = DEFAULT_PATH) -> Optional[dict]:
    with _conn(path) as c:
        r = c.execute("SELECT * FROM dashboard_layout WHERE owner=? AND is_default=1 LIMIT 1", (owner,)).fetchone()
        if not r:
            r = c.execute("SELECT * FROM dashboard_layout WHERE owner=? ORDER BY updated_at DESC LIMIT 1", (owner,)).fetchone()
        return _row_layout(r) if r else None


# ---- Templates ----
def list_templates(path: str = DEFAULT_PATH) -> list[dict]:
    with _conn(path) as c:
        return [_row_tpl(r) for r in c.execute("SELECT * FROM dashboard_template ORDER BY is_system DESC, updated_at DESC")]


def get_template(tid: str, path: str = DEFAULT_PATH) -> Optional[dict]:
    with _conn(path) as c:
        r = c.execute("SELECT * FROM dashboard_template WHERE id=?", (tid,)).fetchone()
        return _row_tpl(r) if r else None


def upsert_template(*, tid: str, owner: Optional[str], org_id: Optional[str], name: str,
                    role: str, description: str, layout: dict, is_system: bool = False,
                    path: str = DEFAULT_PATH) -> dict:
    now = _now()
    with _conn(path) as c:
        exists = c.execute("SELECT created_at FROM dashboard_template WHERE id=?", (tid,)).fetchone()
        created = exists["created_at"] if exists else now
        c.execute("""INSERT INTO dashboard_template(id,owner,org_id,name,role,description,layout_json,schema_version,is_system,created_at,updated_at)
                     VALUES(?,?,?,?,?,?,?,?,?,?,?)
                     ON CONFLICT(id) DO UPDATE SET name=excluded.name, role=excluded.role,
                       description=excluded.description, org_id=excluded.org_id,
                       layout_json=excluded.layout_json, is_system=excluded.is_system, updated_at=excluded.updated_at""",
                  (tid, owner, org_id, name, role, description, json.dumps(layout, ensure_ascii=False),
                   SCHEMA_VERSION, 1 if is_system else 0, created, now))
    return get_template(tid, path)


def delete_template(tid: str, path: str = DEFAULT_PATH) -> None:
    with _conn(path) as c:
        c.execute("DELETE FROM dashboard_template WHERE id=?", (tid,))


# ---- Schedules (Excel на почту) ----
def _row_sched(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "owner": r["owner"], "org_id": r["org_id"], "layout_id": r["layout_id"],
            "email": r["email"], "frequency": r["frequency"], "hour": r["hour"],
            "enabled": bool(r["enabled"]), "last_sent": r["last_sent"], "created_at": r["created_at"]}


def list_schedules(owner: Optional[str] = None, path: str = DEFAULT_PATH) -> list[dict]:
    with _conn(path) as c:
        if owner is None:
            rows = c.execute("SELECT * FROM dashboard_schedule ORDER BY created_at DESC")
        else:
            rows = c.execute("SELECT * FROM dashboard_schedule WHERE owner=? ORDER BY created_at DESC", (owner,))
        return [_row_sched(r) for r in rows]


def get_schedule(sid: str, path: str = DEFAULT_PATH) -> Optional[dict]:
    with _conn(path) as c:
        r = c.execute("SELECT * FROM dashboard_schedule WHERE id=?", (sid,)).fetchone()
        return _row_sched(r) if r else None


def create_schedule(*, owner: str, org_id: Optional[str], email: str, frequency: str = "daily",
                    hour: int = 6, layout_id: Optional[str] = None, path: str = DEFAULT_PATH) -> dict:
    sid = new_id()
    with _conn(path) as c:
        c.execute("""INSERT INTO dashboard_schedule(id,owner,org_id,layout_id,email,frequency,hour,enabled,last_sent,created_at)
                     VALUES(?,?,?,?,?,?,?,1,0,?)""",
                  (sid, owner, org_id, layout_id, email, frequency, int(hour), _now()))
    return get_schedule(sid, path)


def delete_schedule(sid: str, path: str = DEFAULT_PATH) -> None:
    with _conn(path) as c:
        c.execute("DELETE FROM dashboard_schedule WHERE id=?", (sid,))


def mark_sent(sid: str, ts: int, path: str = DEFAULT_PATH) -> None:
    with _conn(path) as c:
        c.execute("UPDATE dashboard_schedule SET last_sent=? WHERE id=?", (int(ts), sid))
