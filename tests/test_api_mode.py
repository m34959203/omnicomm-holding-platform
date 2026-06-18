"""Тест режима А (Omnicomm API) на мок-клиенте — без сети.

Фиксирует контракт стыка data_loader ↔ api_client под РЕАЛЬНУЮ схему
consolidatedReport: POST возвращает items[] = [{consolidatedReport:{vehicleId,
mv{...}, fuel{...}}}], по строке на ТС × сутки; имена берём из дерева ТС.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from omnicomm_report import analytics, data_loader, validator  # noqa: E402
from omnicomm_report.models import ReportPeriod  # noqa: E402


def _cr(vehicle_id, mileage, fuel, worked, idle, max_speed, speeding=0, fuel_idle=0):
    """Одна суточная строка consolidatedReport."""
    return {"consolidatedReport": {
        "vehicleId": vehicle_id, "date": 1780099200,
        "mv": {"mileage": mileage, "maxSpeed": max_speed, "mileageSpeeding": speeding,
               "worked": worked, "workedNoMovement": idle},
        "fuel": {"fuelConsumption": fuel, "fuelConsumptionWOMovement": fuel_idle},
    }}


class MockClient:
    """Мок Omnicomm-клиента: дерево ТС + сводный отчёт (2 суточные строки у ТС-1)."""

    def __init__(self):
        self.asked = None

    def list_vehicles(self):
        return [
            {"terminal_id": 1, "uuid": "uuid-1", "name": "А777АА 01", "terminal_type": "FAS"},
            {"terminal_id": 2, "uuid": "uuid-2", "name": "В888ВВ 02", "terminal_type": "FTC"},
        ]

    def get_consolidated_report(self, vehicle_ids, period):
        assert isinstance(vehicle_ids, list)
        assert hasattr(period, "start_ts") and hasattr(period, "end_ts")
        self.asked = list(vehicle_ids)
        return {"items": [
            _cr(1, 3000, 2400, 7200, 3600, 95, speeding=100, fuel_idle=300),
            _cr(1, 2000, 1600, 3600, 1800, 80, speeding=50, fuel_idle=200),  # тот же ТС, 2-е сутки
            _cr(2, 3000, 2500, 5400, 900, 88),
        ]}


def _period() -> ReportPeriod:
    return ReportPeriod(
        start=datetime(2026, 5, 1, tzinfo=timezone.utc),
        end=datetime(2026, 5, 31, tzinfo=timezone.utc),
    )


def test_api_mode_aggregates_days():
    """Суточные строки сворачиваются: пробег/расход — сумма, скорость — максимум."""
    vehicles = data_loader.load_from_api(MockClient(), _period(), ["1", "2"])
    assert len(vehicles) == 2
    v = {x.name: x for x in vehicles}
    k = v["А777АА 01"]
    assert k.mileage_km == 5000.0          # 3000 + 2000
    # топливо в API — децилитры → литры (÷10): (2400+1600)/10 = 400
    assert k.fuel_l == 400.0
    assert k.fuel_idle_l == 50.0          # (300 + 200)/10
    assert k.engine_hours == 3.0          # (7200 + 3600) / 3600
    assert k.engine_idle_hours == 1.5     # (3600 + 1800) / 3600
    assert k.max_speed_kmh == 95.0        # max(95, 80)
    assert k.speeding_mileage_km == 150.0  # 100 + 50
    assert v["В888ВВ 02"].mileage_km == 3000.0


def test_api_mode_resolves_names_from_tree():
    """Имя ТС берётся из дерева по terminal_id, а не из числового vehicleId."""
    vehicles = data_loader.load_from_api(MockClient(), _period(), ["1", "2"])
    names = {x.name for x in vehicles}
    assert names == {"А777АА 01", "В888ВВ 02"}


def test_api_mode_feeds_analytics():
    vehicles = validator.validate(
        data_loader.load_from_api(MockClient(), _period(), ["1", "2"])
    )
    report = analytics.analyze(vehicles, _period(), "ООО Тест", source="api")
    assert report.kpi.vehicles_with_data == 2
    assert report.kpi.total_mileage_km == 8000.0  # 5000 + 3000
    assert report.conclusions


def test_api_mode_autoresolves_ids_when_none():
    """vehicle_ids=None → подтягиваем terminal_id всех ТС из дерева."""
    client = MockClient()
    vehicles = data_loader.load_from_api(client, _period(), None)
    assert client.asked == ["1", "2"]
    assert len(vehicles) == 2


# --- №2: рекурсивный флэттен дерева ТС ---------------------------------------

def test_flatten_vehicle_tree_nested():
    """ТС лежат в children[].objects[] на разной глубине — собрать все."""
    from omnicomm_report.api_client import _flatten_vehicle_tree

    tree = [{
        "id": 1, "name": "root", "objects": [],
        "children": [
            {"id": 2, "name": "Группа A",
             "objects": [{"uuid": "u1", "name": "KAMAZ"}, {"uuid": "u2", "name": "SCANIA"}]},
            {"id": 3, "name": "Группа B", "objects": [],
             "children": [{"id": 4, "name": "Подгруппа",
                           "objects": [{"uuid": "u3", "name": "KATO"}]}]},
        ],
    }]
    vs = _flatten_vehicle_tree(tree)
    assert [v["uuid"] for v in vs] == ["u1", "u2", "u3"]


def test_flatten_vehicle_tree_dedup():
    """Дубли по uuid схлопываются."""
    from omnicomm_report.api_client import _flatten_vehicle_tree

    tree = [{
        "objects": [{"uuid": "u1"}],
        "children": [{"objects": [{"uuid": "u1"}, {"uuid": "u2"}]}],
    }]
    vs = _flatten_vehicle_tree(tree)
    assert sorted(v["uuid"] for v in vs) == ["u1", "u2"]


# --- Нарезка периода по лимиту 31 день ---------------------------------------

def test_period_windows_split():
    from omnicomm_report.api_client import _period_windows

    day = 86400
    # 70 дней → 3 окна (31 + 31 + 8)
    wins = _period_windows(0, 70 * day)
    assert len(wins) == 3
    assert wins[0] == (0, 31 * day)
    assert wins[-1][1] == 70 * day
    # короткий период — одно окно
    assert _period_windows(0, 5 * day) == [(0, 5 * day)]
