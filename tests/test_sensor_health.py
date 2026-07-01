"""Тесты Sensor Health v1 (путь C)."""

from omnicomm_report import sensor_health as sh
from omnicomm_report.sensor_health import Capability, TerminalStatus

NOW = 1_782_000_000  # фикс. «сейчас» (epoch сек)


# --- классификация терминала -------------------------------------------------

def test_classify_online_stale_offline_unknown():
    assert sh.classify_terminal(NOW - 60, NOW) is TerminalStatus.ONLINE
    # > 30 мин → STALE
    assert sh.classify_terminal(NOW - 2 * 3600, NOW) is TerminalStatus.STALE
    # > 24 ч → OFFLINE
    assert sh.classify_terminal(NOW - 48 * 3600, NOW) is TerminalStatus.OFFLINE
    assert sh.classify_terminal(None, NOW) is TerminalStatus.UNKNOWN


def test_classify_data_quality_bands():
    # Шкала качества данных: 🟢 ≤30мин · 🟠 30мин–24ч · 🔴 >24ч · ⚪ нет данных
    assert sh.classify_terminal(NOW - 25 * 60, NOW) is TerminalStatus.ONLINE     # 25 мин → зелёный
    assert sh.classify_terminal(NOW - 35 * 60, NOW) is TerminalStatus.STALE      # 35 мин → оранжевый
    assert sh.classify_terminal(NOW - 23 * 3600, NOW) is TerminalStatus.STALE    # 23 ч → оранжевый
    assert sh.classify_terminal(NOW - 25 * 3600, NOW) is TerminalStatus.OFFLINE  # 25 ч → красный
    assert sh.classify_terminal(None, NOW) is TerminalStatus.UNKNOWN             # нет данных → серый


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

# --- сенсор-уровень из «Журнала» --------------------------------------------

def _packet(**over):
    # форма реального пакета click/log (ДУТ как массивы по 6 слотам)
    p = {"EVENT_DATE": 1782140091, "U_BOARD": 258, "U_BOARD_PRESENT": 1,
         "LLS_ID": [1, 2, 3, 4, 5, 6],
         "LLS_CODE_PRESENT": [1, 0, 0, 0, 0, 0],
         "IS_EXTERNAL_SUPPLY_BROKEN": 0, "SATELLITES_NMB": 0}
    p.update(over)
    return p


def test_journal_health_parses_voltage_and_dut_slots():
    jh = sh.journal_health("5", [_packet(), _packet()])
    assert jh.power_ok is True
    assert jh.board_volts_max == 25.8           # 258 децивольт → 25.8 В
    assert jh.dut_reporting == {1}              # отдаёт только слот №1
    assert jh.supply_broken is False


def test_diagnose_dut_failure_with_power_gate():
    # baseline: слоты 1 и 2 должны отдавать; в окне отдаёт только 1, питание есть
    jh = sh.journal_health("5", [_packet()])
    assert sh.diagnose_dut_failure(jh, [1, 2]) == [2]  # №2 молчит = сбой


def test_diagnose_dut_failure_suppressed_when_no_power():
    # питание просело (бортсеть 0.5 В) → молчание датчиков НЕ их вина
    jh = sh.journal_health("5", [_packet(U_BOARD=5)])  # 0.5 В
    assert jh.power_ok is False
    assert sh.diagnose_dut_failure(jh, [1, 2]) == []


def test_journal_health_gps_and_supply_flags():
    jh = sh.journal_health("5", [
        _packet(SATELLITES_NMB=6, IS_EXTERNAL_SUPPLY_BROKEN=1)])
    assert jh.gps_ok is True
    assert jh.supply_broken is True


# --- оркестрация: триаж → точечный Журнал -----------------------------------

def test_select_suspects_only_alive_with_lost_capability():
    fleet = sh.FleetSensorHealth(
        terminals=[
            sh.TerminalHealth("7", TerminalStatus.ONLINE, NOW, 0),
            sh.TerminalHealth("8", TerminalStatus.OFFLINE, NOW - 99999, 99999),
            sh.TerminalHealth("9", TerminalStatus.ONLINE, NOW, 0),
        ],
        capabilities={
            "7": sh.CapabilityPresence("7", {Capability.GPS}),               # топливо пропало
            "8": sh.CapabilityPresence("8", {Capability.GPS}),               # тоже, но OFFLINE
            "9": sh.CapabilityPresence("9", {Capability.GPS, Capability.FUEL}),  # топливо есть
        },
    )
    baseline = {
        "7": sh.CapabilityPresence("7", {Capability.GPS, Capability.FUEL}),
        "8": sh.CapabilityPresence("8", {Capability.GPS, Capability.FUEL}),
        "9": sh.CapabilityPresence("9", {Capability.GPS, Capability.FUEL}),
    }
    # 7 — жив и потерял топливо → подозреваемый; 8 — офлайн (терминал, не датчик); 9 — норма
    assert sh.select_suspects(fleet, baseline, focus=Capability.FUEL) == ["7"]


def test_learn_dut_baseline():
    assert sh.learn_dut_baseline([_packet()]) == {1}  # отдаёт только слот №1


def test_investigate_drills_suspects_via_injected_fetch():
    fleet = sh.FleetSensorHealth(
        terminals=[sh.TerminalHealth("7", TerminalStatus.ONLINE, NOW, 0)],
        capabilities={"7": sh.CapabilityPresence("7", {Capability.GPS})},
    )
    baseline = {"7": sh.CapabilityPresence("7", {Capability.GPS, Capability.FUEL})}
    dut_baseline = {"7": {1, 2}}  # раньше отдавали слоты 1 и 2
    # в «Журнале» сейчас отдаёт только слот 1, питание есть → слот 2 = сбой
    diags = sh.investigate(fleet, baseline, dut_baseline,
                           journal_fetch=lambda tid: [_packet()])
    assert len(diags) == 1
    d = diags[0]
    assert d.terminal_id == "7"
    assert d.dut_failing == [2]
    assert "сбой ДУТ" in d.verdict


def test_diagnose_suspect_inconclusive_without_power():
    d = sh.diagnose_suspect("7", [_packet(U_BOARD=5)], [1, 2])  # 0.5 В
    assert d.inconclusive is True
    assert d.dut_failing == []


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
