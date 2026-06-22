"""SQLite-хранилище справочника организаций (star schema, holding §10.9).

JSON-реестр (`org.save_org_registry`) хорош для прототипа, но на масштабе холдинга
(23 ДЗО → под-ДЗО → ~1427 ТС, обновление 8×/сутки) нужна индексируемая БД. Здесь —
**SQLite** (stdlib, ноль инфраструктуры; один файл на dev/сервере/в тестах). Схема —
звезда: `dim_org` (иерархия) + `vehicle_org` (привязка ТС). Факты (`fact_fuel`,
`fact_events`) добавятся сюда же по мере надобности.

Postgres подключится той же формой запросов через DSN — единственное место, знающее
о бэкенде, это `_connect()`. Доступ к реестру идёт через `org.save/load_org_registry`,
которые диспетчат на этот модуль по расширению пути (`.db`/`.sqlite`).
"""

from __future__ import annotations

import os
import sqlite3
from typing import Optional

from .org import Org, OrgLevel, OrgRegistry, OrgTree, OrgType

SCHEMA = """
CREATE TABLE IF NOT EXISTS dim_org (
    org_id    TEXT PRIMARY KEY,
    name      TEXT NOT NULL,
    parent_id TEXT,
    level     TEXT NOT NULL,
    type      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dim_org_parent ON dim_org(parent_id);

CREATE TABLE IF NOT EXISTS vehicle_org (
    vehicle_id TEXT PRIMARY KEY,
    org_id     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_vehicle_org_org ON vehicle_org(org_id);

CREATE TABLE IF NOT EXISTS sensor_baseline (
    terminal_id  TEXT PRIMARY KEY,
    capabilities TEXT NOT NULL,   -- CSV значений Capability (gps,engine,fuel,can,aux)
    dut_slots    TEXT NOT NULL,   -- CSV слотов ДУТ (1..6)
    updated_at   INTEGER          -- epoch сек снимка baseline
);

CREATE TABLE IF NOT EXISTS to_plan (
    terminal_id     TEXT PRIMARY KEY,
    interval_mh     REAL,
    interval_km     REAL,
    remind_before_mh REAL,
    remind_before_km REAL
);

CREATE TABLE IF NOT EXISTS to_state (
    terminal_id TEXT PRIMARY KEY,
    t0          INTEGER,          -- начало текущего цикла наработки
    last_to_at  INTEGER           -- когда подтверждено последнее ТО
);
"""


def _connect(path: str) -> sqlite3.Connection:
    """Единственное место, знающее о бэкенде. Для Postgres — заменить здесь на DSN."""
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    conn = _connect(path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def save_org_registry(registry: OrgRegistry, path: str) -> str:
    """Перезаписать реестр в SQLite (полная замена — реестр пересобирается из дерева)."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    conn = _connect(path)
    try:
        conn.executescript(SCHEMA)
        conn.execute("DELETE FROM dim_org")
        conn.execute("DELETE FROM vehicle_org")
        conn.executemany(
            "INSERT INTO dim_org(org_id, name, parent_id, level, type) VALUES (?,?,?,?,?)",
            [(o.org_id, o.name, o.parent_id, o.level.value, o.type.value)
             for o in registry.tree.all_orgs()],
        )
        conn.executemany(
            "INSERT INTO vehicle_org(vehicle_id, org_id) VALUES (?,?)",
            [(str(vid), str(oid)) for vid, oid in registry.vehicle_org.items()],
        )
        conn.commit()
    finally:
        conn.close()
    return path


def load_org_registry(path: str) -> Optional[OrgRegistry]:
    """Прочитать реестр из SQLite. None — нет файла или нет таблиц реестра."""
    if not os.path.exists(path):
        return None
    conn = _connect(path)
    try:
        try:
            org_rows = conn.execute(
                "SELECT org_id, name, parent_id, level, type FROM dim_org").fetchall()
            veh_rows = conn.execute(
                "SELECT vehicle_id, org_id FROM vehicle_org").fetchall()
        except sqlite3.OperationalError:
            return None        # БД есть, но это не наш реестр
    finally:
        conn.close()
    tree = OrgTree(
        Org(org_id=r[0], name=r[1], parent_id=r[2],
            level=OrgLevel(r[3]), type=OrgType(r[4]))
        for r in org_rows
    )
    vehicle_org = {str(r[0]): str(r[1]) for r in veh_rows}
    return OrgRegistry(tree=tree, vehicle_org=vehicle_org)


# --- Baseline здоровья датчиков (Sensor Health) ------------------------------

def _csv(values) -> str:
    return ",".join(str(v) for v in sorted(values))


def save_sensor_baseline(baselines: dict, path: str) -> str:
    """UPSERT baseline здоровья по ТС (накапливается, не полная замена).

    `baselines`: {terminal_id -> sensor_health.SensorBaseline}. Возможности/слоты
    сериализуются в CSV. Повторный снимок по ТС перезаписывает прежний.
    """
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    conn = _connect(path)
    try:
        conn.executescript(SCHEMA)
        conn.executemany(
            "INSERT INTO sensor_baseline(terminal_id, capabilities, dut_slots, "
            "updated_at) VALUES (?,?,?,?) "
            "ON CONFLICT(terminal_id) DO UPDATE SET "
            "capabilities=excluded.capabilities, dut_slots=excluded.dut_slots, "
            "updated_at=excluded.updated_at",
            [(str(b.terminal_id), _csv(c.value for c in b.capabilities),
              _csv(b.dut_slots), b.updated_at) for b in baselines.values()],
        )
        conn.commit()
    finally:
        conn.close()
    return path


def load_sensor_baseline(path: str) -> dict:
    """Прочитать baseline здоровья: {terminal_id -> SensorBaseline}. {} — нет данных."""
    if not os.path.exists(path):
        return {}
    from .sensor_health import Capability, SensorBaseline
    conn = _connect(path)
    try:
        try:
            rows = conn.execute("SELECT terminal_id, capabilities, dut_slots, "
                                "updated_at FROM sensor_baseline").fetchall()
        except sqlite3.OperationalError:
            return {}
    finally:
        conn.close()
    out: dict = {}
    for tid, caps, slots, upd in rows:
        out[str(tid)] = SensorBaseline(
            terminal_id=str(tid),
            capabilities={Capability(c) for c in caps.split(",") if c},
            dut_slots={int(s) for s in slots.split(",") if s},
            updated_at=upd,
        )
    return out


# --- Контроль ТО (планы + состояния) -----------------------------------------

def save_maintenance(plans: dict, states: dict, path: str) -> str:
    """UPSERT планы и состояния ТО. plans/states: {tid -> MaintenancePlan/State}."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    conn = _connect(path)
    try:
        conn.executescript(SCHEMA)
        conn.executemany(
            "INSERT INTO to_plan(terminal_id, interval_mh, interval_km, "
            "remind_before_mh, remind_before_km) VALUES (?,?,?,?,?) "
            "ON CONFLICT(terminal_id) DO UPDATE SET interval_mh=excluded.interval_mh, "
            "interval_km=excluded.interval_km, remind_before_mh=excluded.remind_before_mh, "
            "remind_before_km=excluded.remind_before_km",
            [(str(p.terminal_id), p.interval_mh, p.interval_km,
              p.remind_before_mh, p.remind_before_km) for p in plans.values()],
        )
        conn.executemany(
            "INSERT INTO to_state(terminal_id, t0, last_to_at) VALUES (?,?,?) "
            "ON CONFLICT(terminal_id) DO UPDATE SET t0=excluded.t0, "
            "last_to_at=excluded.last_to_at",
            [(str(s.terminal_id), s.t0, s.last_to_at) for s in states.values()],
        )
        conn.commit()
    finally:
        conn.close()
    return path


def load_maintenance(path: str) -> tuple:
    """Прочитать планы и состояния ТО: (plans, states). ({},{}) — нет данных."""
    if not os.path.exists(path):
        return {}, {}
    from .maintenance import MaintenancePlan, MaintenanceState
    conn = _connect(path)
    try:
        try:
            prows = conn.execute("SELECT terminal_id, interval_mh, interval_km, "
                                 "remind_before_mh, remind_before_km FROM to_plan").fetchall()
            srows = conn.execute("SELECT terminal_id, t0, last_to_at FROM to_state").fetchall()
        except sqlite3.OperationalError:
            return {}, {}
    finally:
        conn.close()
    plans = {str(r[0]): MaintenancePlan(str(r[0]), r[1], r[2],
             r[3] if r[3] is not None else 20.0,
             r[4] if r[4] is not None else 500.0) for r in prows}
    states = {str(r[0]): MaintenanceState(str(r[0]), r[1], r[2]) for r in srows}
    return plans, states
