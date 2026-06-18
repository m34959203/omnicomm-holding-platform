"""Тесты модуля «Работа на погрузке»: классификация источника, единицы, GPS."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from omnicomm_report import loading  # noqa: E402
from omnicomm_report.models import VehicleMetrics  # noqa: E402


def _fill(**acc):
    base = {"worked_s": 0, "no_move_s": 0, "idling_rpm_s": 0, "normal_rpm_s": 0,
            "under_load_rpm_s": 0, "uni_present": False, "uni_type": None,
            "uni_on_s": 0, "uni_fuel_l": 0, "uni_hour_cons_l": None,
            "fuel_wo_move_l": None, "max_speed": 50}
    base.update(acc)
    vm = VehicleMetrics("1", "ТС")
    loading.classify_and_fill(vm, base)
    return vm


def test_method_sensor_fact():
    vm = _fill(uni_present=True, uni_type=0, uni_on_s=3600, uni_fuel_l=20.0,
              no_move_s=7200, fuel_wo_move_l=30.0)
    assert vm.loading_method == "sensor"
    assert vm.loading_is_estimate is False
    assert vm.loading_hours == 1.0
    assert vm.unproductive_idle_hours == 1.0           # (7200-3600)/3600
    assert vm.loading_fuel_l == 20.0
    assert vm.loading_fuel_per_mh == 20.0              # 20 л / 1 ч
    assert vm.unproductive_fuel_l == 10.0              # 30 - 20


def test_method_sensor_zero():
    vm = _fill(uni_present=True, uni_type=1, uni_on_s=0, no_move_s=3600)
    assert vm.loading_method == "sensor_zero"
    assert vm.loading_hours == 0.0
    assert vm.loading_fuel_l == 0.0


def test_method_rpm_estimate_bounded():
    """Оценка по оборотам ограничена временем стоянки, топливо не выдаётся."""
    vm = _fill(idling_rpm_s=1800, under_load_rpm_s=9000, no_move_s=3600)
    assert vm.loading_method == "rpm"
    assert vm.loading_is_estimate is True
    assert vm.loading_hours == 1.0                     # min(9000,3600)/3600
    assert vm.loading_fuel_l is None


def test_method_rpm_under_load_without_idle_band():
    """Правило заказчика: обороты под нагрузкой при неподвижности = гидравлика,
    даже без полосы холостого хода (idling=0)."""
    vm = _fill(idling_rpm_s=0, under_load_rpm_s=7200, no_move_s=7200)
    assert vm.loading_method == "rpm"
    assert vm.loading_hours == 2.0          # min(7200,7200)/3600


def test_method_none_without_under_load():
    """Нет ни датчика, ни оборотов под нагрузкой → нет сигнала."""
    vm = _fill(idling_rpm_s=3600, under_load_rpm_s=0, no_move_s=3600)
    assert vm.loading_method == "none"
    assert vm.loading_hours is None


def test_uni_type2_excluded():
    """uniType=2 (импульсный, FTC) не считается датчиком надстройки."""
    vm = _fill(uni_present=True, uni_type=2, uni_on_s=3600, no_move_s=3600,
              idling_rpm_s=0, under_load_rpm_s=0)
    assert vm.loading_method == "none"


def test_segment():
    assert _fill(max_speed=10).vehicle_segment == "special"
    assert _fill(max_speed=80).vehicle_segment == "transport"
    assert _fill(max_speed=45).vehicle_segment == "refuse_truck"


def test_cluster_track_points():
    # стоянка 4 точки по 60с в одной координате (sat=8) → 1 кластер ~180с
    track = [
        {"date": 0, "latitude": 49.8, "longitude": 73.1, "speed": 0, "satellitesCount": 8},
        {"date": 60, "latitude": 49.8, "longitude": 73.1, "speed": 0, "satellitesCount": 8},
        {"date": 120, "latitude": 49.8, "longitude": 73.1, "speed": 0, "satellitesCount": 8},
        {"date": 200, "latitude": 49.8, "longitude": 73.1, "speed": 0, "satellitesCount": 8},
        {"date": 260, "latitude": 49.81, "longitude": 73.2, "speed": 40, "satellitesCount": 8},
    ]
    pts = loading.cluster_track_points(track, min_stop_s=180)
    assert len(pts) == 1
    assert pts[0].duration_s == 200
    assert abs(pts[0].latitude - 49.8) < 1e-3


def test_cluster_tolerates_speed_jitter():
    """Джиттер скорости 0.4–1 км/ч на стоянке не должен дробить её (калибровка gct)."""
    track = [
        {"date": 0, "latitude": 49.8, "longitude": 73.1, "speed": 0, "satellitesCount": 8},
        {"date": 40, "latitude": 49.8, "longitude": 73.1, "speed": 0.4, "satellitesCount": 8},
        {"date": 90, "latitude": 49.8, "longitude": 73.1, "speed": 0.9, "satellitesCount": 8},
        {"date": 140, "latitude": 49.8, "longitude": 73.1, "speed": 0, "satellitesCount": 8},
        {"date": 200, "latitude": 49.82, "longitude": 73.2, "speed": 40, "satellitesCount": 8},
    ]
    pts = loading.cluster_track_points(track, min_stop_s=60)   # speed_eps=1.5 по умолчанию
    assert len(pts) == 1                       # джиттер не разорвал стоянку
    assert pts[0].duration_s == 140            # 0..140 стоянка; точка 200 (40 км/ч) — движение


def test_cluster_filters_low_satellites():
    track = [{"date": t, "latitude": 49.8, "longitude": 73.1, "speed": 0,
              "satellitesCount": 1} for t in (0, 60, 120, 200)]
    assert loading.cluster_track_points(track, min_stop_s=180) == []


def test_cluster_skips_short_stops():
    track = [{"date": t, "latitude": 49.8, "longitude": 73.1, "speed": 0,
              "satellitesCount": 8} for t in (0, 60)]
    assert loading.cluster_track_points(track, min_stop_s=180) == []


def test_estimate_loading_from_gps_stops():
    """Бессенсорная оценка: короткие остановки=погрузка, длинные=простой, метод gps."""
    vm = VehicleMetrics("1", "Мусоровоз")
    vm.work_no_move_hours = 2.0   # 2 ч двигатель стоя
    pts = [
        loading.LoadingPoint(49.8, 73.1, 0, 300.0),    # 5 мин — обслуживание
        loading.LoadingPoint(49.8, 73.2, 0, 240.0),    # 4 мин — обслуживание
        loading.LoadingPoint(49.8, 73.3, 0, 3600.0),   # 60 мин — стоянка (исключить)
    ]
    loading.estimate_loading_from_stops(vm, pts, min_s=180, max_s=900)
    assert vm.loading_method == "gps"
    assert vm.loading_is_estimate is True
    # погрузка ≈ (300+240)/3600 = 0.15 ч; простой = 2.0 - 0.15 = 1.85 ч
    assert vm.loading_hours == 0.15
    assert vm.unproductive_idle_hours == 1.85
    assert len(vm.loading_points) == 2          # длинная стоянка не считается погрузкой


def test_estimate_loading_geozone_no_window():
    """Геозоны-площадки: каждый визит — обслуживание (без окна), метод geozone."""
    vm = VehicleMetrics("1", "Мусоровоз")
    vm.work_no_move_hours = 1.0
    pts = [loading.LoadingPoint(0, 0, 0, 1200.0, name="Площадка-1", source="geozone")]
    loading.estimate_loading_from_stops(vm, pts, windowed=False)
    assert vm.loading_method == "geozone"
    assert vm.loading_hours == round(1200 / 3600, 2)   # 0.33 ч, в пределах 1.0


def test_parse_geozone_visits():
    """Визиты в геозоны → LoadingPoint(source='geozone'), топливо дл→л (÷10)."""
    records = [
        {"vehicleId": 42, "geozoneName": "Площадка №1",
         "geoInfo": {"startDate": 1000, "duration": 600},
         "fuel": {"fuelConsumption": 35}},
        {"vehicleId": 42, "geozoneName": "Площадка №2",
         "geoInfo": {"startDate": 2000, "duration": 300},
         "fuel": {"fuelConsumption": None}},
    ]
    out = loading.parse_geozone_visits(records)
    assert set(out) == {"42"}
    pts = out["42"]
    assert len(pts) == 2
    assert pts[0].source == "geozone"
    assert pts[0].name == "Площадка №1"
    assert pts[0].duration_s == 600
    assert pts[0].fuel_l == 3.5            # 35 дл / 10
    assert pts[1].fuel_l is None           # нет топлива → None


def test_parse_geozone_visits_skips_garbage():
    """Записи без vehicleId/не-dict отбрасываются молча."""
    out = loading.parse_geozone_visits([None, {"geozoneName": "X"}, "bad"])
    assert out == {}
