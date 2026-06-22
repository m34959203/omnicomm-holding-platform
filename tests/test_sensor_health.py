"""Тесты Sensor Health v1 (путь C)."""

from omnicomm_report import sensor_health as sh
from omnicomm_report.sensor_health import Capability, TerminalStatus

NOW = 1_782_000_000  # фикс. «сейчас» (epoch сек)


# --- классификация терминала -------------------------------------------------

def test_classify_online_stale_offline_unknown():
    assert sh.classify_terminal(NOW - 60, NOW) is TerminalStatus.ONLINE
    # > 60 мин → STALE
    assert sh.classify_terminal(NOW - 2 * 3600, NOW) is TerminalStatus.STALE
    # > 24 ч → OFFLINE
    assert sh.classify_terminal(NOW - 48 * 3600, NOW) is TerminalStatus.OFFLINE
    assert sh.classify_terminal(None, NOW) is TerminalStatus.UNKNOWN


def test_classify_custom_thresholds():
    # порог STALE 5 мин: данные 10 мин назад → STALE
    assert sh.classify_terminal(NOW - 600, NOW, stale_after_min=5) is TerminalStatus.STALE


def test_terminal_health_converts_ms_and_picks_status():
    rows = [
        {"id": 111, "dateID": (NOW - 30) * 1000},        # свежий → ONLINE
        {"id": 222, "dateID": (NOW - 3 * 3600) * 1000},  # 3ч → STALE
        {"id": 333, "dateID": (NOW - 50 * 3600) * 1000}, # 50ч → OFFLINE
    ]
    health = {t.terminal_id: t for t in sh.terminal_health(rows, NOW)}
    assert health["111"].status is TerminalStatus.ONLINE
    assert health["222"].status is TerminalStatus.STALE
    assert health["333"].status is TerminalStatus.OFFLINE
    # секунды восстановлены из мс
    assert health["111"].last_seen == NOW - 30


def test_terminal_health_unknown_when_in_tree_but_no_activity():
    vehicles = [{"terminal_id": 999, "name": "Камаз", "receive_data": True}]
    health = {t.terminal_id: t for t in sh.terminal_health([], NOW, vehicles)}
    assert health["999"].status is TerminalStatus.UNKNOWN
    assert health["999"].name == "Камаз"
    assert health["999"].receive_data is True


# --- наличие возможностей ----------------------------------------------------

def _row(**blocks):
    return {"consolidatedReport": {"vehicleId": 42, **blocks}}


def test_capability_fuel_by_volume_not_consumption():
    # расход null, но уровень есть → ДУТ работает
    row = _row(fuel={"startVolume": 1169, "endVolume": 1180,
                     "fuelConsumption": None})
    cp = sh.capability_presence(row)
    assert cp.has(Capability.FUEL)


def test_capability_fuel_absent_when_all_null():
    row = _row(fuel={"startVolume": None, "endVolume": None,
                     "maxVolume": None, "minVolume": None})
    assert not sh.capability_presence(row).has(Capability.FUEL)


def test_capability_can_aux_engine_gps():
    row = _row(
        mv={"mileage": 0.4, "worked": 198, "normalRPM": 168},
        can={"distance": None, "fuelUsed": None},      # null → нет CAN
        uniDataList=[{"uniName": None, "univInputOnTime": None}],  # null → нет AUX
    )
    cp = sh.capability_presence(row)
    assert cp.has(Capability.GPS)
    assert cp.has(Capability.ENGINE)
    assert not cp.has(Capability.CAN)
    assert not cp.has(Capability.AUX)

    row2 = _row(
        mv={"mileage": 1.0, "worked": 10},
        ccan={"spn245": 12.3},                          # есть CAN
        uniDataList=[{"uniName": "Гидравлика", "univInputOnTime": 3600}],
    )
    cp2 = sh.capability_presence(row2)
    assert cp2.has(Capability.CAN)
    assert cp2.has(Capability.AUX)


def test_fleet_capabilities_unions_over_days():
    # один ТС, двое суток: в первые есть топливо, во вторые — CAN
    rows = [
        {"consolidatedReport": {"vehicleId": 7, "fuel": {"startVolume": 100}}},
        {"consolidatedReport": {"vehicleId": 7, "ccan": {"spn245": 1}}},
    ]
    caps = sh.fleet_capabilities(rows)
    assert caps["7"].has(Capability.FUEL)
    assert caps["7"].has(Capability.CAN)


# --- детекция пропаж ---------------------------------------------------------

def test_detect_gaps_flags_disappeared_capability():
    baseline = {"7": sh.CapabilityPresence("7", {Capability.GPS, Capability.FUEL})}
    current = {"7": sh.CapabilityPresence("7", {Capability.GPS})}  # топливо пропало
    gaps = sh.detect_gaps(current, baseline)
    assert len(gaps) == 1
    assert gaps[0].terminal_id == "7"
    assert gaps[0].capability is Capability.FUEL


def test_detect_gaps_ignores_new_capabilities_and_dead_terminals():
    baseline = {
        "7": sh.CapabilityPresence("7", {Capability.GPS}),
        "8": sh.CapabilityPresence("8", {Capability.FUEL}),  # потух весь — нет в current
    }
    current = {"7": sh.CapabilityPresence("7", {Capability.GPS, Capability.CAN})}
    gaps = sh.detect_gaps(current, baseline)
    assert gaps == []  # новая CAN — не сбой; ТС 8 целиком офлайн — не сенсор-сбой


# --- GPS-health --------------------------------------------------------------

def test_gps_health_counts_valid_points():
    track = [
        {"satellitesCount": 6}, {"satellitesCount": 3},   # 3 < 4 — невалидна
        {"satellitesCount": 4},
    ]
    h = sh.gps_health("5", track)
    assert h.points == 3 and h.valid_points == 2 and h.ok is True
    assert sh.gps_health("5", []).ok is False


# --- сводка ------------------------------------------------------------------

def test_assess_combines_traffic_lights_caps_and_gaps():
    activity = [{"id": 7, "dateID": (NOW - 30) * 1000}]
    consolidated = [{"consolidatedReport": {"vehicleId": 7,
                                            "mv": {"mileage": 1.0}}}]  # только GPS
    baseline = {"7": sh.CapabilityPresence("7", {Capability.GPS, Capability.FUEL})}
    report = sh.assess(activity, consolidated, NOW, baseline=baseline)
    assert report.terminals[0].status is TerminalStatus.ONLINE
    assert report.capabilities["7"].has(Capability.GPS)
    # топливо было в baseline, в текущем нет → пропажа
    assert any(g.capability is Capability.FUEL for g in report.gaps)
