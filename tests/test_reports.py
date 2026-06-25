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


def test_violations_geozone_and_aggregate():
    from omnicomm_report.speeding import Violation
    vios = {"1": [Violation(terminal_id="1", geozone="Инкай 80", limit=80, max_speed=110.0,
                            excess=30.0, duration_s=120, start_ts=1000, points=2,
                            public_road=True, st_kap_severity="грубое",
                            koap_article="ст.592 ч.3", fine_kzt=86500)]}
    vs = [VehicleMetrics(vehicle_id="1", name="A", max_speed_kmh=110.0),
          VehicleMetrics(vehicle_id="2", name="B", max_speed_kmh=95.0,
                         speeding_count=4, speeding_mileage_km=12.0)]
    out = reports.build_violations(vios, vs, {"1": "A", "2": "B"})
    assert out["count"] == 2
    assert out["rows"][0]["fine_kzt"] == 86500          # с штрафом сверху
    agg = next(r for r in out["rows"] if r["vehicle_id"] == "2")
    assert agg["type"] == "Превышение скорости" and "4 эпизодов" in agg["detail"]
    assert out["by_type"]["Превышение в геозоне"] == 1


def test_fuel_form_volumes_and_events():
    vs = [
        VehicleMetrics(vehicle_id="1", name="АТЗ-1", delivery_l=1200.0, refuel_l=50.0,
                       vol_start_l=300.0, vol_end_l=180.0, vol_min_l=120.0, vol_max_l=400.0),
        VehicleMetrics(vehicle_id="2", name="Камаз", refuel_l=80.0, drain_l=15.0, fuel_l=60.0),
        VehicleMetrics(vehicle_id="3", name="Пустой"),   # без топливных данных → пропуск
    ]
    out = reports.build_fuel(vs)
    assert out["count"] == 2                              # «Пустой» отброшен
    assert out["rows"][0]["vehicle_id"] == "1"           # больше движений топлива сверху
    assert out["rows"][0]["delivery_l"] == 1200.0 and out["rows"][0]["vol_end_l"] == 180.0
    assert out["totals"] == {"refuel_l": 130.0, "drain_l": 15.0, "delivery_l": 1200.0}


def test_fuel_fields_mapped_from_consolidated():
    from omnicomm_report import data_loader
    recs = [{"consolidatedReport": {"vehicleId": 7, "date": 1000,
             "fuel": {"refuelling": 500, "draining": 100, "delivery": 2000,
                      "startVolume": 3000, "endVolume": 1500, "minVolume": 800, "maxVolume": 4000}}}]
    vs = data_loader._aggregate_consolidated(recs, {"7": "АТЗ"})
    v = vs[0]
    assert v.refuel_l == 50.0 and v.drain_l == 10.0 and v.delivery_l == 200.0   # дл→л
    assert v.vol_start_l == 300.0 and v.vol_end_l == 150.0 and v.vol_max_l == 400.0
