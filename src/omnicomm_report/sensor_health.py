"""Sensor Health v1 — путь C (на доступном через REST).

Контекст: «Журнал»/сырьё по узлам и сенсор-уровень (адрес датчика, напряжение
бортсети) через REST API недоступны (закрыты правами; проверено на копии КАП).
Поэтому здесь — то, что реально отдаёт API:

1. **Терминальный «светофор»** по давности данных (`activity/vehicles` → `dateID`)
   + флаг `receive_data` из дерева ТС. ONLINE / STALE / OFFLINE.
2. **Наличие возможностей (capabilities)** по блокам `consolidatedReport`
   (GPS / топливо-ДУТ / двигатель-обороты / CAN / доп.входы) — что вообще
   передаёт ТС за период.
3. **Детекция «данные потухли»** — сравнение текущих возможностей с baseline
   (что ТС отдавал раньше): возможность была и пропала → подозрение на сбой
   датчика (грубо, на суточной гранулярности).
4. **GPS-health** из трека — есть ли валидные точки (спутники ≥ порога).

Точный сбой конкретного ДУТ по адресу и развязку по напряжению бортсети это
НЕ даёт — для них нужен «Журнал»/ретрансляция (пути A/B), см.
`docs/knowledge-base/10-sensor-health-detection.md`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Optional

from . import config


# --- Терминальный светофор ---------------------------------------------------

class TerminalStatus(str, Enum):
    ONLINE = "online"     # 🟢 данные свежие
    STALE = "stale"       # 🟡 данных нет дольше порога STALE
    OFFLINE = "offline"   # 🔴 данных нет дольше порога OFFLINE
    UNKNOWN = "unknown"   # нет записи активности по терминалу


@dataclass
class TerminalHealth:
    terminal_id: str
    status: TerminalStatus
    last_seen: Optional[int]        # epoch сек (None — неизвестно)
    age_seconds: Optional[int]      # сколько назад были данные
    name: Optional[str] = None
    receive_data: Optional[bool] = None


def classify_terminal(last_seen: Optional[int], now: int,
                      stale_after_min: Optional[int] = None,
                      offline_after_hours: Optional[int] = None) -> TerminalStatus:
    """Классифицировать терминал по давности последних данных."""
    if last_seen is None:
        return TerminalStatus.UNKNOWN
    stale_after = (stale_after_min if stale_after_min is not None
                   else config.TERMINAL_STALE_AFTER_MIN) * 60
    offline_after = (offline_after_hours if offline_after_hours is not None
                     else config.TERMINAL_OFFLINE_AFTER_HOURS) * 3600
    age = now - last_seen
    if age >= offline_after:
        return TerminalStatus.OFFLINE
    if age >= stale_after:
        return TerminalStatus.STALE
    return TerminalStatus.ONLINE


def _activity_last_seen(row: dict) -> tuple[Optional[str], Optional[int]]:
    """(terminal_id, last_seen_sec) из строки activity/vehicles.

    `dateID` приходит в миллисекундах epoch — переводим в секунды.
    """
    tid = row.get("id") or row.get("terminal_id") or row.get("vehicleId")
    raw = row.get("dateID") or row.get("date") or row.get("lastData")
    last_seen: Optional[int] = None
    if isinstance(raw, (int, float)):
        # > 10^12 — почти наверняка миллисекунды
        last_seen = int(raw / 1000) if raw > 1_000_000_000_000 else int(raw)
    return (str(tid) if tid is not None else None, last_seen)


def terminal_health(activity_rows: Iterable[dict], now: int,
                    vehicles: Optional[Iterable[dict]] = None,
                    **thresholds: Any) -> list[TerminalHealth]:
    """«Светофор» по всем терминалам из activity/vehicles.

    `vehicles` (опц., из дерева ТС) добавляет имя и `receive_data`. ТС без записи
    активности, но присутствующий в дереве, помечается UNKNOWN.
    """
    name_map: dict[str, dict] = {}
    for v in vehicles or []:
        tid = v.get("terminal_id") or v.get("id")
        if tid is not None:
            name_map[str(tid)] = v

    seen: dict[str, int] = {}
    for row in activity_rows or []:
        tid, last = _activity_last_seen(row)
        if tid is None:
            continue
        # держим самую свежую запись на терминал
        if last is not None and (tid not in seen or last > seen[tid]):
            seen[tid] = last
        seen.setdefault(tid, last)  # type: ignore[arg-type]

    out: list[TerminalHealth] = []
    ids = set(seen) | set(name_map)
    for tid in sorted(ids):
        last = seen.get(tid)
        info = name_map.get(tid, {})
        out.append(TerminalHealth(
            terminal_id=tid,
            status=classify_terminal(last, now,
                                     thresholds.get("stale_after_min"),
                                     thresholds.get("offline_after_hours")),
            last_seen=last,
            age_seconds=(now - last) if last is not None else None,
            name=info.get("name"),
            receive_data=info.get("receive_data"),
        ))
    return out


# --- Наличие возможностей (capabilities) по consolidatedReport ----------------

class Capability(str, Enum):
    GPS = "gps"         # координаты/пробег/скорость (mv)
    ENGINE = "engine"   # работа двигателя / обороты (mv)
    FUEL = "fuel"       # ДУТ — уровень топлива (fuel)
    CAN = "can"         # CAN-шина (can/canmt/ccan)
    AUX = "aux"         # универсальные входы / доп.оборудование (uniDataList)


@dataclass
class CapabilityPresence:
    terminal_id: str
    present: set[Capability] = field(default_factory=set)

    def has(self, cap: Capability) -> bool:
        return cap in self.present


def _unwrap(row: dict) -> dict:
    """Развернуть обёртку `{"consolidatedReport": {...}}` (как в data_loader)."""
    inner = row.get("consolidatedReport")
    return inner if isinstance(inner, dict) else row


def _any_not_none(block: Any, keys: Optional[tuple[str, ...]] = None) -> bool:
    """Есть ли в блоке хоть одно непустое значение (None = «нет данных»)."""
    if isinstance(block, dict):
        items = (block.get(k) for k in keys) if keys else block.values()
        return any(v is not None for v in items)
    if isinstance(block, list):
        return any(_any_not_none(el) for el in block)
    return block is not None


# Поля-уровни ДУТ — присутствие топлива судим по объёму, а не по расходу
# (расход бывает null и при исправном датчике).
_FUEL_VOLUME_KEYS = ("startVolume", "endVolume", "maxVolume", "minVolume")
_ENGINE_KEYS = ("worked", "normalRPM", "idlingRPM", "workedUnderLoadRPM")
_GPS_KEYS = ("mileage", "maxSpeed", "movement", "mileageAtPeriodEnd")


def capability_presence(row: dict, terminal_id: Optional[str] = None
                        ) -> CapabilityPresence:
    """Какие возможности ТС реально передаёт за период (по блокам отчёта)."""
    cr = _unwrap(row)
    tid = str(terminal_id if terminal_id is not None
              else cr.get("vehicleId") or cr.get("id") or "")
    present: set[Capability] = set()
    mv = cr.get("mv") or {}
    if _any_not_none(mv, _GPS_KEYS):
        present.add(Capability.GPS)
    if _any_not_none(mv, _ENGINE_KEYS):
        present.add(Capability.ENGINE)
    if _any_not_none(cr.get("fuel"), _FUEL_VOLUME_KEYS) or \
       _any_not_none(cr.get("fueladd"), _FUEL_VOLUME_KEYS):
        present.add(Capability.FUEL)
    if any(_any_not_none(cr.get(b)) for b in ("can", "canmt", "ccan")):
        present.add(Capability.CAN)
    if _any_not_none(cr.get("uniDataList")):
        present.add(Capability.AUX)
    return CapabilityPresence(terminal_id=tid, present=present)


def fleet_capabilities(rows: Iterable[dict]) -> dict[str, CapabilityPresence]:
    """Свод наличия возможностей по ТС: terminal_id → CapabilityPresence.

    Несколько строк (ТС × сутки) на один ТС объединяются объединением множеств —
    возможность считается «есть», если она была хоть в одни сутки периода.
    """
    out: dict[str, CapabilityPresence] = {}
    for row in rows or []:
        cp = capability_presence(row)
        if not cp.terminal_id:
            continue
        acc = out.setdefault(cp.terminal_id,
                             CapabilityPresence(terminal_id=cp.terminal_id))
        acc.present |= cp.present
    return out


# --- Детекция «данные потухли» (vs baseline) ---------------------------------

@dataclass
class SensorGap:
    terminal_id: str
    capability: Capability
    note: str = "возможность была в baseline и пропала — вероятный сбой датчика"


def detect_gaps(current: dict[str, CapabilityPresence],
                baseline: dict[str, CapabilityPresence]) -> list[SensorGap]:
    """Сравнить текущее наличие с baseline: что было и пропало.

    Возвращает по ТС список пропавших возможностей. Появление новых — НЕ сбой.
    ТС, которых нет в текущем своде (потух весь терминал), пропускаем — это
    уровень терминального светофора, а не сбой отдельного датчика.
    """
    gaps: list[SensorGap] = []
    for tid, base in baseline.items():
        cur = current.get(tid)
        if cur is None:
            continue
        for cap in sorted(base.present - cur.present, key=lambda c: c.value):
            gaps.append(SensorGap(terminal_id=tid, capability=cap))
    return gaps


# --- GPS-health из трека ------------------------------------------------------

@dataclass
class GpsHealth:
    terminal_id: str
    points: int
    valid_points: int          # с достаточным числом спутников
    ok: bool


def gps_health(terminal_id: str, track: Iterable[dict],
               min_satellites: int = 4) -> GpsHealth:
    """Здоровье GPS по треку: доля точек с валидным числом спутников."""
    pts = list(track or [])
    valid = sum(1 for p in pts
                if isinstance(p, dict)
                and (p.get("satellitesCount") or 0) >= min_satellites)
    return GpsHealth(terminal_id=str(terminal_id), points=len(pts),
                     valid_points=valid, ok=valid > 0)


# --- Сенсор-уровень из «Журнала» (путь A: POST /ls/api/v1/click/log) ---------
# «Журнал» доступен через REST и даёт по-датчиковые флаги наличия + напряжение
# бортсети → развязка «нет питания vs датчик умер». Звать ТОЧЕЧНО (1 ТС, окно).

# Минимальный набор для диагностики здоровья датчиков (фильтр по объёму).
JOURNAL_HEALTH_GROUPS = ["GENERAL", "NAVI", "LLS", "CAN", "OBD", "UNIVAL"]
JOURNAL_HEALTH_COLUMNS = [
    "EVENT_DATE", "U_BOARD", "U_BOARD_PRESENT",
    "LLS_ID", "LLS_CODE_PRESENT", "LLS_STATUS",
    "IS_EXTERNAL_SUPPLY_BROKEN", "IS_IGNITION_ON",
    "SATELLITES_NMB", "SATELLITES_NMB_PRESENT", "CAN_DT_PRESENT",
]

U_BOARD_SCALE = 10      # U_BOARD в децивольтах: 258 → 25.8 В
POWER_OK_VOLTS = 7.0    # питание считаем «живым», если бортсеть выше этого


@dataclass
class JournalHealth:
    terminal_id: str
    packets: int
    power_ok: bool                       # бортсеть выше порога хоть в одном пакете
    board_volts_max: Optional[float]     # макс. напряжение бортсети, В
    supply_broken: bool                  # был ли флаг обрыва внешнего питания
    dut_reporting: set[int] = field(default_factory=set)  # слоты ДУТ, отдавшие данные
    gps_ok: bool = False


def journal_health(terminal_id: str, packets: Iterable[dict]) -> JournalHealth:
    """Разобрать пакеты «Журнала» в здоровье узлов терминала.

    LLS_ID / LLS_CODE_PRESENT — массивы по слотам ДУТ (1..6); слот «отдаёт
    данные», если `LLS_CODE_PRESENT[i]=1` хоть в одном пакете окна.
    """
    pkts = [p for p in (packets or []) if isinstance(p, dict)]
    volts = [(p.get("U_BOARD") or 0) / U_BOARD_SCALE
             for p in pkts if p.get("U_BOARD_PRESENT")]
    board_max = max(volts) if volts else None
    reporting: set[int] = set()
    gps_ok = False
    supply_broken = False
    for p in pkts:
        if p.get("IS_EXTERNAL_SUPPLY_BROKEN"):
            supply_broken = True
        if (p.get("SATELLITES_NMB") or 0) >= 4:
            gps_ok = True
        ids = p.get("LLS_ID") or []
        pres = p.get("LLS_CODE_PRESENT") or []
        for i, sid in enumerate(ids):
            if i < len(pres) and pres[i]:
                reporting.add(sid)
    return JournalHealth(
        terminal_id=str(terminal_id), packets=len(pkts),
        power_ok=board_max is not None and board_max >= POWER_OK_VOLTS,
        board_volts_max=board_max, supply_broken=supply_broken,
        dut_reporting=reporting, gps_ok=gps_ok,
    )


def diagnose_dut_failure(jh: JournalHealth,
                         baseline_dut_ids: Iterable[int]) -> list[int]:
    """ДУТ-слоты, которые ДОЛЖНЫ отдавать данные (baseline), но молчат при живом
    питании → вероятный сбой ДУТ. Это и есть gate по напряжению бортсети:
    нет питания → НЕ сбой датчика (вернём пусто).

    `baseline_dut_ids` — слоты ДУТ, исторически передававшие данные на этом ТС
    (из конфигурации/прошлого «здорового» окна).
    """
    if not jh.power_ok:
        return []   # питания нет — молчание датчиков не их вина
    return sorted(set(baseline_dut_ids) - jh.dut_reporting)


# --- Сводка ------------------------------------------------------------------

@dataclass
class FleetSensorHealth:
    terminals: list[TerminalHealth] = field(default_factory=list)
    capabilities: dict[str, CapabilityPresence] = field(default_factory=dict)
    gaps: list[SensorGap] = field(default_factory=list)

    def offline(self) -> list[TerminalHealth]:
        return [t for t in self.terminals if t.status is TerminalStatus.OFFLINE]

    def stale(self) -> list[TerminalHealth]:
        return [t for t in self.terminals if t.status is TerminalStatus.STALE]


def assess(activity_rows: Iterable[dict], consolidated_rows: Iterable[dict],
           now: int, vehicles: Optional[Iterable[dict]] = None,
           baseline: Optional[dict[str, CapabilityPresence]] = None,
           **thresholds: Any) -> FleetSensorHealth:
    """Собрать Sensor Health v1: светофор + возможности + (опц.) пропажи vs baseline."""
    caps = fleet_capabilities(consolidated_rows)
    gaps = detect_gaps(caps, baseline) if baseline else []
    return FleetSensorHealth(
        terminals=terminal_health(activity_rows, now, vehicles, **thresholds),
        capabilities=caps,
        gaps=gaps,
    )
