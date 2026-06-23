"""Снапшот-секции «Качество данных» (Sensor Health, R7) и «Контроль ТО» (R6).

Тонкий слой между движками (`sensor_health`, `maintenance`) и снапшотом кэша:
строит JSON-готовые секции и для live-пути (сырые строки Omnicomm), и для demo
(синтез из `VehicleMetrics`, чтобы фичи показывались без сети).

Граница честности (R7.4, ТЗ §11): сенсор-уровень (адрес узла/напряжение) через
REST недоступен → Sensor Health здесь терминального уровня + наличие блоков.
Контроль ТО считает наработку В ПРЕДЕЛАХ периода снапшота (T0=начало периода);
накопление между синками и цикл подтверждения — следующий шаг (store-backed).
"""

from __future__ import annotations

from typing import Iterable, Optional

from omnicomm_report import config, maintenance, sensor_health
from omnicomm_report.sensor_health import Capability, TerminalStatus

# Человекочитаемые подписи возможностей для фронта.
_CAP_LABEL = {
    Capability.GPS: "GPS",
    Capability.ENGINE: "Двигатель/обороты",
    Capability.FUEL: "Топливо (ДУТ)",
    Capability.CAN: "CAN-шина",
    Capability.AUX: "Доп. входы",
}

# Возможности, отсутствие которых критично для KPI (топливо/обороты/GPS).
_KPI_CRITICAL = (Capability.FUEL, Capability.ENGINE, Capability.GPS)


def _is_stationary(v) -> bool:
    """Стационарная/спецтехника: моточасы есть, пробег почти нулевой."""
    eh = getattr(v, "engine_hours", None) or 0
    km = getattr(v, "mileage_km", None) or 0
    if eh <= 0:
        return False
    return (km / eh) < config.STATIONARY_KM_PER_HOUR


# --- Sensor Health (R7.1, R7.2) ----------------------------------------------

def _terminal_dict(th) -> dict:
    return {
        "terminal_id": th.terminal_id,
        "name": th.name,
        "status": th.status.value if isinstance(th.status, TerminalStatus) else th.status,
        "last_seen": th.last_seen,
        "age_seconds": th.age_seconds,
        "receive_data": th.receive_data,
    }


def _annotate_power(missing: list, fetch_state) -> dict:
    """Уровень 1.5: для подозрительных (пропал блок) тянем напряжение из /state и
    разводим «сбой датчика (питание есть)» vs «обесточен/низкое питание».

    `fetch_state(tid) -> dict` — инъекция (в проде = client.get_vehicle_state).
    Пробуем не весь парк, а до SENSOR_VOLTAGE_PROBE_MAX подозрительных (rate-limit).
    Возвращает сводку по статусам питания.
    """
    summary = {s.value: 0 for s in sensor_health.PowerStatus}
    if fetch_state is None:
        return summary
    for m in missing[:config.SENSOR_VOLTAGE_PROBE_MAX]:
        try:
            st = fetch_state(m["terminal_id"]) or {}
        except Exception:  # noqa: BLE001 — проба не валит снапшот
            continue
        v = st.get("voltage")
        status = sensor_health.classify_power(v)
        m["voltage"] = v
        m["power"] = status.value
        m["power_verdict"] = sensor_health.power_verdict(status)
        summary[status.value] += 1
    return summary


def build_sensor_health(activity_rows: Iterable[dict], records: Iterable[dict],
                        tree_vehicles: Iterable[dict], now: int,
                        fetch_state=None) -> dict:
    """Светофор терминалов (R7.1) + пропавшие возможности (R7.2) + питание (ур.1.5)."""
    terminals = sensor_health.terminal_health(activity_rows, now, vehicles=tree_vehicles)
    caps = sensor_health.fleet_capabilities(records)

    name_map = {str(v.get("terminal_id") or v.get("id")): v.get("name")
                for v in (tree_vehicles or [])
                if (v.get("terminal_id") or v.get("id"))}

    counts = {s.value: 0 for s in TerminalStatus}
    for th in terminals:
        key = th.status.value if isinstance(th.status, TerminalStatus) else th.status
        counts[key] = counts.get(key, 0) + 1

    # ТС, у которых пропал критичный для KPI блок (есть терминал, но нет топлива/
    # оборотов/GPS за период) → их KPI недостоверны, помечаем.
    missing = []
    for tid, cp in caps.items():
        absent = [c for c in _KPI_CRITICAL if not cp.has(c)]
        if absent:
            missing.append({
                "terminal_id": tid,
                "name": name_map.get(tid),
                "missing": [_CAP_LABEL[c] for c in absent],
            })
    missing.sort(key=lambda m: (-len(m["missing"]), m["terminal_id"]))

    # Уровень 1.5 — питание (gate «сбой ДУТ vs обесточен») для подозрительных.
    power = _annotate_power(missing, fetch_state)

    return {
        "terminals": [_terminal_dict(t) for t in terminals],
        "counts": counts,
        "missing_capabilities": missing,
        "power": power,                       # сводка статусов питания подозрительных
        "level": "terminal+power" if fetch_state else "terminal",
    }


def build_sensor_health_demo(vehicles, now: int) -> dict:
    """Демо-синтез светофора и пропавших блоков из VehicleMetrics (без сети)."""
    terminals, counts, missing = [], {s.value: 0 for s in TerminalStatus}, []
    for v in vehicles:
        tid = str(v.vehicle_id)
        h = abs(hash(tid))
        # детерминированное распределение: большинство online, часть stale/offline
        bucket = h % 10
        if not getattr(v, "has_data", True) or bucket == 0:
            status, age = TerminalStatus.OFFLINE, 36 * 3600
        elif bucket <= 2:
            status, age = TerminalStatus.STALE, 3 * 3600
        else:
            status, age = TerminalStatus.ONLINE, 600
        counts[status.value] += 1
        terminals.append({
            "terminal_id": tid, "name": v.name, "status": status.value,
            "last_seen": now - age, "age_seconds": age,
            "receive_data": status is not TerminalStatus.OFFLINE,
        })
        # часть ТС «потеряла» датчик топлива — с синтетическим напряжением (ур.1.5)
        if bucket in (1, 5):
            volt = 13.8 if bucket == 1 else 10.9   # норма vs просадка
            ps = sensor_health.classify_power(volt)
            missing.append({"terminal_id": tid, "name": v.name,
                            "missing": ["Топливо (ДУТ)"], "voltage": volt,
                            "power": ps.value, "power_verdict": sensor_health.power_verdict(ps)})
    missing.sort(key=lambda m: m["terminal_id"])
    power = {s.value: 0 for s in sensor_health.PowerStatus}
    for m in missing:
        if m.get("power"):
            power[m["power"]] += 1
    return {"terminals": terminals, "counts": counts,
            "missing_capabilities": missing, "power": power, "level": "terminal+power"}


# --- Контроль ТО (R6.1–R6.3) -------------------------------------------------

def _plan_for(v) -> maintenance.MaintenancePlan:
    """Дефолт-план ТО по классу ТС (пробег для подвижной, моточасы для спец.)."""
    tid = str(v.vehicle_id)
    if _is_stationary(v):
        return maintenance.MaintenancePlan(
            terminal_id=tid, interval_mh=config.MAINT_INTERVAL_MH_STATIONARY,
            remind_before_mh=config.MAINT_REMIND_BEFORE_MH)
    return maintenance.MaintenancePlan(
        terminal_id=tid, interval_km=config.MAINT_INTERVAL_KM_MOBILE,
        remind_before_km=config.MAINT_REMIND_BEFORE_KM)


def _status_dict(st, name: Optional[str]) -> dict:
    return {
        "terminal_id": st.terminal_id, "name": name, "status": st.status,
        "mh_since": st.mh_since, "km_since": st.km_since,
        "mh_left": st.mh_left, "km_left": st.km_left, "reason": st.reason,
    }


def _summarize_maintenance(statuses, name_map) -> dict:
    counts: dict[str, int] = {}
    for st in statuses:
        counts[st.status] = counts.get(st.status, 0) + 1
    # на верх — самые срочные
    order = {"просрочено": 0, "ожидается": 1, "ok": 2}
    statuses = sorted(statuses, key=lambda s: (order.get(s.status, 3),
                                               s.mh_left if s.mh_left is not None else s.km_left or 0))
    return {
        "counts": counts,
        "items": [_status_dict(s, name_map.get(s.terminal_id)) for s in statuses],
        "note": "наработка считается в пределах периода снапшота (T0); "
                "накопление между синками и подтверждение ТО — следующий шаг",
    }


def build_maintenance(records: Iterable[dict], vehicles) -> dict:
    """Статусы ТО парка из сводных строк + дефолт-планы по классу (R6.1–R6.3)."""
    records_by_terminal = maintenance.from_consolidated(records)
    plans = {str(v.vehicle_id): _plan_for(v) for v in vehicles}
    states: dict = {}  # T0=None → наработка за период (см. note)
    statuses = maintenance.fleet_status(plans, states, records_by_terminal)
    name_map = {str(v.vehicle_id): v.name for v in vehicles}
    return _summarize_maintenance(statuses, name_map)


def build_maintenance_demo(vehicles) -> dict:
    """Демо-синтез наработки: суточные записи из VehicleMetrics + дефолт-планы."""
    plans, records_by_terminal = {}, {}
    for v in vehicles:
        tid = str(v.vehicle_id)
        plans[tid] = _plan_for(v)
        # «накопленная» наработка: масштабируем период так, чтобы часть ТС была
        # на подходе/просрочке (детерминированно по hash) — показать светофор ТО.
        factor = 1 + (abs(hash(tid)) % 100) / 8.0  # 1.0 .. ~13.5
        records_by_terminal[tid] = [{
            "date": 0,
            "worked_sec": (getattr(v, "engine_hours", 0) or 0) * 3600 * factor,
            "mileage_km": (getattr(v, "mileage_km", 0) or 0) * factor,
        }]
    statuses = maintenance.fleet_status(plans, {}, records_by_terminal)
    name_map = {str(v.vehicle_id): v.name for v in vehicles}
    return _summarize_maintenance(statuses, name_map)
