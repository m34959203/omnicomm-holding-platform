"""Тесты аудита действий и редактируемых шаблонов типов техники."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from omnicomm_report import audit, vehicle_types  # noqa: E402


def test_audit_log_and_recent(tmp_path, monkeypatch):
    monkeypatch.setattr(audit, "AUDIT_DIR", str(tmp_path))
    monkeypatch.setattr(audit, "AUDIT_PATH", str(tmp_path / "a.jsonl"))
    audit.log("templates_saved", actor="platform", types=3)
    audit.log("report_generated", client="Горкомтранс", vehicles=70)
    rec = audit.recent(10)
    assert rec[0]["action"] == "report_generated"          # свежие сверху
    assert rec[1]["details"]["types"] == 3
    # фильтр по клиенту
    only = audit.recent(10, client="Горкомтранс")
    assert len(only) == 1 and only[0]["client"] == "Горкомтранс"


def test_audit_label():
    assert "ШАБЛОН" in audit.label("templates_saved").upper()
    assert audit.label("unknown_action") == "unknown_action"


def test_templates_default_and_override(tmp_path, monkeypatch):
    path = str(tmp_path / "vt.json")
    monkeypatch.setattr(vehicle_types, "TEMPLATES_PATH", path)
    # без файла — дефолты
    assert vehicle_types.profile("refuse_truck").label == "Мусоровоз"
    # переопределить мусоровоз + добавить новый тип
    vehicle_types.save_profiles({
        "refuse_truck": {"label": "Мусоровоз X", "primary_metric": "l_per_mh",
                         "stationary_work": True, "note": "тест"},
        "water_truck": {"label": "Водовоз", "primary_metric": "both",
                        "stationary_work": True, "note": "полив"},
    }, path=path)
    prof = vehicle_types.all_profiles()
    assert prof["refuse_truck"].label == "Мусоровоз X"           # override
    assert prof["refuse_truck"].primary_metric == "l_per_mh"
    assert prof["water_truck"].label == "Водовоз"               # новый тип
    # дефолтные нетронутые типы остаются
    assert prof["excavator"].label == "Экскаватор"


def test_templates_save_clean(tmp_path):
    path = str(tmp_path / "vt.json")
    vehicle_types.save_profiles({"  ": {"label": "пусто"},          # пустой ключ отсеять
                                 "x": {"label": "X"}}, path=path)
    import json
    data = json.load(open(path, encoding="utf-8"))
    assert "x" in data and len(data) == 1
