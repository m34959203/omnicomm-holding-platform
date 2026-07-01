"""Тесты сборки снимка за произвольный диапазон из архива (Фаза A)."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api import sync, main as api_main  # noqa: E402


# --- _reconstruct_base: структура/имена ТС из готового снимка ---------------------
def _base_snapshot():
    return {
        "orgs": [{
            "org_id": "holding", "name": "КАП", "level": "holding", "children": [
                {"org_id": "8894", "name": "АО НАК Казатомпром", "level": "dzo", "children": [
                    {"org_id": "13766", "name": "ТОО Каратау", "level": "sub_dzo", "children": []},
                ]},
            ],
        }],
        "vehicle_org": {"111": "13766", "222": "8894"},
        "fleet_table": {"rows": [
            {"vehicle_id": "111", "vehicle": "HOWO 111"},
            {"vehicle_id": "222", "vehicle": "JAC 222"},
        ]},
        "geozones": [{"id": "z1"}],
        "sensor_health": {"terminals": []},
        "maintenance": {"items": []},
    }


def test_reconstruct_base_rebuilds_tree_and_names():
    tree, vehicle_org, name_map = sync._reconstruct_base(_base_snapshot())
    assert tree.get("13766").name == "ТОО Каратау"
    assert tree.get("13766").parent_id == "8894"
    assert tree.subtree_ids("8894") == {"8894", "13766"}   # структура восстановлена
    assert vehicle_org == {"111": "13766", "222": "8894"}
    assert name_map == {"111": "HOWO 111", "222": "JAC 222"}  # имена из fleet_table


# --- _ensure_range_snapshot: парсинг/границы ключа, single-flight -----------------
def test_ensure_range_rejects_bad_key(monkeypatch):
    calls = []
    monkeypatch.setattr(api_main.cache, "load_snapshot", lambda *a, **k: None)
    monkeypatch.setattr(api_main.sync, "build_range_snapshot",
                        lambda *a, **k: calls.append(a) or {"period_key": "x"})
    assert api_main._ensure_range_snapshot("не-ключ") is False
    assert api_main._ensure_range_snapshot("2026-13-40_2026-13-99") is False   # даты невалидны
    assert calls == []                                    # сборку не звали


def test_ensure_range_rejects_too_long(monkeypatch):
    calls = []
    monkeypatch.setattr(api_main.cache, "load_snapshot", lambda *a, **k: None)
    monkeypatch.setattr(api_main.sync, "build_range_snapshot",
                        lambda *a, **k: calls.append(a) or {"period_key": "x"})
    # диапазон > RANGE_MAX_DAYS (≈год) — отклонить (защита архива)
    assert api_main._ensure_range_snapshot("2023-01-01_2026-01-01") is False
    assert calls == []


def test_ensure_range_builds_valid(monkeypatch):
    calls = []
    monkeypatch.setattr(api_main.cache, "load_snapshot", lambda *a, **k: None)
    monkeypatch.setattr(api_main.sync, "build_range_snapshot",
                        lambda s, e, **k: calls.append((s, e)) or {"period_key": "k"})
    assert api_main._ensure_range_snapshot("2026-05-01_2026-06-10") is True
    assert len(calls) == 1
    s, e = calls[0]
    assert e > s and (e - s) / 86400 > 39                 # ~40 дней, конец дня включён


def test_ensure_range_uses_cache_when_present(monkeypatch):
    calls = []
    monkeypatch.setattr(api_main.cache, "load_snapshot", lambda *a, **k: {"cached": 1})
    monkeypatch.setattr(api_main.sync, "build_range_snapshot",
                        lambda *a, **k: calls.append(a) or {})
    assert api_main._ensure_range_snapshot("2026-05-01_2026-06-10") is True
    assert calls == []                                    # уже в кэше — не пересобираем
