"""Тесты отчётных форм паритета (kb-14): посещение геозон, таблица по ТС."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from omnicomm_report import reports  # noqa: E402
from omnicomm_report.models import VehicleMetrics  # noqa: E402


def test_geozone_visits_table_and_summary():
    visits = [
        {"vehicleId": 1, "geozoneName": "Рудник Инкай", "geoInfo": {"startDate": 1000, "duration": 600},
         "mv": {"maxSpeed": 82, "mileage": 5.2, "mileageSpeeding": 1.1}},
        {"vehicleId": 2, "geozoneName": "Рудник Инкай", "geoInfo": {"startDate": 2000, "duration": 300},
         "mv": {"maxSpeed": 40, "mileage": 2.0, "mileageSpeeding": 0}},
        {"vehicleId": 1, "geozoneName": "База", "geoInfo": {"startDate": 500, "duration": 120},
         "mv": {"maxSpeed": 10, "mileage": 0.3}},
    ]
    out = reports.build_geozone_visits(visits, {"1": "Камаз-1", "2": "МАЗ-2"})
    assert out["count"] == 3
    assert out["rows"][0]["enter_ts"] == 2000           # сортировка свежие→старые
    r = next(x for x in out["rows"] if x["vehicle_id"] == "1" and x["geozone"] == "Рудник Инкай")
    assert r["vehicle"] == "Камаз-1" and r["exit_ts"] == 1600 and r["max_speed_kmh"] == 82
    inkai = next(g for g in out["by_geozone"] if g["geozone"] == "Рудник Инкай")
    assert inkai["visits"] == 2 and inkai["vehicles"] == 2   # сводка по геозоне


def test_geozone_visits_empty():
    out = reports.build_geozone_visits([], {})
    assert out == {"count": 0, "rows": [], "by_geozone": []}


def test_fleet_table_all_fields_sorted():
    vs = [
        VehicleMetrics(vehicle_id="1", name="A", mileage_km=10.0, fuel_l=5.0, engine_hours=2.0,
                       max_speed_kmh=80.0, speeding_count=3, has_data=True),
        VehicleMetrics(vehicle_id="2", name="B", mileage_km=50.0, fuel_l=20.0, has_data=True),
    ]
    out = reports.build_fleet_table(vs, {"1": "org-a", "2": "org-b"})
    assert out["count"] == 2
    assert out["rows"][0]["vehicle_id"] == "2"          # больший пробег сверху
    a = next(r for r in out["rows"] if r["vehicle_id"] == "1")
    assert a["fuel_l"] == 5.0 and a["speeding_count"] == 3 and a["org_id"] == "org-a"
