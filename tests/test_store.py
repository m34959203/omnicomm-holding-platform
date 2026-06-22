"""Тесты SQLite-хранилища реестра организаций и прозрачного диспетча."""

from __future__ import annotations

import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from omnicomm_report import holding, org, store  # noqa: E402
from omnicomm_report.org import OrgLevel, OrgType  # noqa: E402


SAMPLE_TREE = [
    {
        "id": "uran", "name": "Уранэнерго",
        "objects": [{"uuid": "v-uran-1"}],
        "children": [
            {"id": "tfo", "name": "ТФО", "objects": [{"uuid": "v-tfo-1"}, {"uuid": "v-tfo-2"}]},
            {"id": "shfo", "name": "ШФО", "objects": [{"uuid": "v-shfo-1"}],
             "children": [{"id": "contr-a", "name": "Подрядчик А",
                           "objects": [{"uuid": "v-contr-1"}]}]},
        ],
    },
    {"id": "umz", "name": "УМЗ", "objects": [{"uuid": "v-umz-1"}]},
]


def _registry():
    tree, vmap = org.build_from_omnicomm_tree(SAMPLE_TREE)
    org.apply_contractor_tags(tree, ["contr-a"])
    return org.OrgRegistry(tree=tree, vehicle_org=vmap)


def test_store_roundtrip(tmp_path):
    path = str(tmp_path / "reg.db")
    store.save_org_registry(_registry(), path)
    loaded = store.load_org_registry(path)
    assert loaded is not None
    assert len(loaded.tree) == len(_registry().tree)
    assert loaded.vehicle_org["v-tfo-1"] == "tfo"
    assert loaded.tree.get("contr-a").type == OrgType.CONTRACTOR
    assert loaded.tree.get("holding").level == OrgLevel.HOLDING
    # доступ по поддереву сохраняется
    assert loaded.tree.can_view("uran", "contr-a")
    assert not loaded.tree.can_view("uran", "umz")


def test_store_is_real_sqlite(tmp_path):
    path = str(tmp_path / "reg.db")
    store.save_org_registry(_registry(), path)
    conn = sqlite3.connect(path)
    try:
        n_org = conn.execute("SELECT COUNT(*) FROM dim_org").fetchone()[0]
        n_veh = conn.execute("SELECT COUNT(*) FROM vehicle_org").fetchone()[0]
    finally:
        conn.close()
    assert n_org == len(_registry().tree)
    assert n_veh == 6


def test_store_overwrite_replaces(tmp_path):
    path = str(tmp_path / "reg.db")
    store.save_org_registry(_registry(), path)
    # второй прогон с меньшим деревом — старые строки не должны остаться
    small_tree, small_vmap = org.build_from_omnicomm_tree(
        [{"id": "umz", "name": "УМЗ", "objects": [{"uuid": "v-umz-1"}]}])
    store.save_org_registry(org.OrgRegistry(tree=small_tree, vehicle_org=small_vmap), path)
    loaded = store.load_org_registry(path)
    assert not loaded.tree.exists("uran")
    assert "v-tfo-1" not in loaded.vehicle_org


def test_dispatch_by_extension(tmp_path):
    # .db путь → SQLite-бэкенд через org.save/load (прозрачно)
    db = str(tmp_path / "reg.db")
    org.save_org_registry(_registry(), db)
    assert os.path.exists(db)
    with open(db, "rb") as fh:
        assert fh.read(16).startswith(b"SQLite format 3")   # это реальная БД, не JSON
    loaded = org.load_org_registry(db)
    assert loaded is not None and loaded.vehicle_org["v-contr-1"] == "contr-a"


def test_dispatch_json_still_works(tmp_path):
    js = str(tmp_path / "reg.json")
    org.save_org_registry(_registry(), js)
    with open(js, "rb") as fh:
        assert fh.read(1) == b"{"                            # JSON, не БД
    assert org.load_org_registry(js).tree.can_view("uran", "tfo")


def test_load_missing_and_foreign_db(tmp_path):
    assert store.load_org_registry(str(tmp_path / "nope.db")) is None
    # чужая БД без наших таблиц → None, не падение
    foreign = str(tmp_path / "foreign.db")
    conn = sqlite3.connect(foreign)
    conn.execute("CREATE TABLE other(x)")
    conn.commit(); conn.close()
    assert store.load_org_registry(foreign) is None


def test_holding_build_registry_to_sqlite(tmp_path):
    db = str(tmp_path / "reg.db")
    reg = holding.build_registry(SAMPLE_TREE, contractor_org_ids=["contr-a"],
                                 registry_path=db)
    assert os.path.exists(db)
    reloaded = org.load_org_registry(db)
    assert reloaded.vehicle_org == reg.vehicle_org
    assert reloaded.tree.get("contr-a").type == OrgType.CONTRACTOR


# --- Sensor Health baseline ---------------------------------------------------

def test_sensor_baseline_roundtrip(tmp_path):
    from omnicomm_report import sensor_health as sh
    from omnicomm_report.sensor_health import Capability
    db = str(tmp_path / "reg.db")
    caps = {
        "7": sh.CapabilityPresence("7", {Capability.GPS, Capability.FUEL}),
        "8": sh.CapabilityPresence("8", {Capability.GPS}),
    }
    baselines = sh.make_baselines(caps, dut_by_terminal={"7": {1, 2}}, now=1782000000)
    store.save_sensor_baseline(baselines, db)

    loaded = store.load_sensor_baseline(db)
    assert set(loaded) == {"7", "8"}
    assert loaded["7"].capabilities == {Capability.GPS, Capability.FUEL}
    assert loaded["7"].dut_slots == {1, 2}
    assert loaded["7"].updated_at == 1782000000
    assert loaded["8"].dut_slots == set()


def test_sensor_baseline_upsert_overwrites(tmp_path):
    from omnicomm_report import sensor_health as sh
    from omnicomm_report.sensor_health import Capability, SensorBaseline
    db = str(tmp_path / "reg.db")
    store.save_sensor_baseline(
        {"7": SensorBaseline("7", {Capability.FUEL}, {1}, 100)}, db)
    # повторный снимок по тому же ТС перезаписывает
    store.save_sensor_baseline(
        {"7": SensorBaseline("7", {Capability.GPS}, {1, 2}, 200)}, db)
    loaded = store.load_sensor_baseline(db)
    assert loaded["7"].capabilities == {Capability.GPS}
    assert loaded["7"].dut_slots == {1, 2}
    assert loaded["7"].updated_at == 200


def test_sensor_baseline_missing_file_returns_empty(tmp_path):
    assert store.load_sensor_baseline(str(tmp_path / "nope.db")) == {}


def test_baseline_adapters_feed_select_suspects(tmp_path):
    from omnicomm_report import sensor_health as sh
    from omnicomm_report.sensor_health import Capability, TerminalStatus
    db = str(tmp_path / "reg.db")
    caps = {"7": sh.CapabilityPresence("7", {Capability.GPS, Capability.FUEL})}
    store.save_sensor_baseline(sh.make_baselines(caps, {"7": {1}}), db)
    baselines = store.load_sensor_baseline(db)

    # текущий снимок: ТС жив, но топливо пропало → подозреваемый
    fleet = sh.FleetSensorHealth(
        terminals=[sh.TerminalHealth("7", TerminalStatus.ONLINE, 1, 0)],
        capabilities={"7": sh.CapabilityPresence("7", {Capability.GPS})},
    )
    cap_base = sh.to_capability_baseline(baselines)
    assert sh.select_suspects(fleet, cap_base, focus=Capability.FUEL) == ["7"]
    assert sh.to_dut_baseline(baselines) == {"7": {1}}


# --- Факты нарушений (идемпотентность) ---------------------------------------

def test_violations_upsert_idempotent(tmp_path):
    from omnicomm_report import store
    from omnicomm_report.speeding import Violation
    db = str(tmp_path / "reg.db")
    v = Violation(terminal_id="7", geozone="Трасса", limit=60, max_speed=85.0,
                  excess=25.0, duration_s=60, start_ts=3, points=3,
                  public_road=True, st_kap_severity="существенное",
                  koap_article="ст.592 ч.2")
    # два прогона по тем же суткам (same start_ts) → одна запись
    assert store.save_violations([v], db, loaded_at=100) == 1
    assert store.save_violations([v], db, loaded_at=200) == 1   # не дубль
    loaded = store.load_violations(db, terminal_id="7")
    assert len(loaded) == 1 and loaded[0].excess == 25.0 and loaded[0].public_road is True
