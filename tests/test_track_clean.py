"""Тесты физической чистки GPS-трека (§4 дизайна)."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from omnicomm_report import track_clean  # noqa: E402
from omnicomm_report.models import VehicleMetrics  # noqa: E402


def _pt(lat, lon, date, speed, sat=8):
    return {"latitude": lat, "longitude": lon, "date": date,
            "speed": speed, "satellitesCount": sat}


# Ровный трек по меридиану ~40 км/ч.
CLEAN = [
    _pt(43.200, 76.900, 0, 40),
    _pt(43.201, 76.900, 10, 42),
    _pt(43.202, 76.900, 20, 41),
    _pt(43.203, 76.900, 30, 43),
]


def test_clean_track_no_outliers():
    res = track_clean.clean_track(CLEAN)
    assert res.dropped_count == 0
    assert res.plausible_max_speed_kmh == 43
    assert len(res.clean) == 4


def test_clean_track_drops_teleport_and_return():
    # Точка 2 «телепортится» на ~11 км за 1 с и возвращается — выброс.
    track = [
        _pt(43.200, 76.900, 0, 40),
        _pt(43.201, 76.900, 10, 42),
        _pt(43.300, 76.900, 11, 450, sat=3),   # сбой GPS
        _pt(43.202, 76.900, 20, 41),
        _pt(43.203, 76.900, 30, 43),
    ]
    res = track_clean.clean_track(track)
    assert res.dropped_indices == [2]
    assert len(res.clean) == 4
    assert res.plausible_max_speed_kmh == 43    # 450 ушёл вместе с точкой


def test_reported_spike_excluded_from_max_even_if_position_ok():
    # Координата правдоподобна, но датчик выдал 450 — в макс. не попадает.
    track = [
        _pt(43.200, 76.900, 0, 40),
        _pt(43.201, 76.900, 10, 450),          # позиция норм, speed-сенсор врёт
        _pt(43.202, 76.900, 20, 41),
    ]
    res = track_clean.clean_track(track)
    assert res.dropped_count == 0               # позиция консистентна — точку не рубим
    assert res.plausible_max_speed_kmh == 41    # но 450 не учитываем в максимуме


def test_short_track_only_reported_clamp():
    track = [_pt(43.2, 76.9, 0, 250), _pt(43.2, 76.9, 10, 60)]
    res = track_clean.clean_track(track)
    assert res.dropped_count == 0               # мало точек для меж-точечной проверки
    assert res.plausible_max_speed_kmh == 60    # 250 (>порога) отсечён из максимума


def test_zero_dt_far_jump_is_teleport():
    track = [
        _pt(43.200, 76.900, 0, 40),
        _pt(43.500, 76.900, 0, 50),            # тот же timestamp, ~33 км — телепорт
        _pt(43.201, 76.900, 10, 41),
    ]
    res = track_clean.clean_track(track)
    assert res.dropped_indices == [1]


def test_reconcile_overrides_implausible_max_and_flags():
    track = [
        _pt(43.200, 76.900, 0, 40),
        _pt(43.201, 76.900, 10, 42),
        _pt(43.300, 76.900, 11, 450, sat=3),
        _pt(43.202, 76.900, 20, 41),
        _pt(43.203, 76.900, 30, 43),
    ]
    v = VehicleMetrics(vehicle_id="x", name="X", max_speed_kmh=450.0)
    res = track_clean.reconcile_vehicle_speed(v, track)
    assert res.dropped_count == 1
    assert v.max_speed_kmh == 43                       # недостоверные 450 → правдоподобные 43
    codes = [a.code for a in v.anomalies]
    assert track_clean.CODE_GPS_OUTLIER_TRACK in codes  # помечено, не молча


def test_reconcile_keeps_plausible_max():
    v = VehicleMetrics(vehicle_id="y", name="Y", max_speed_kmh=90.0)
    track_clean.reconcile_vehicle_speed(v, CLEAN)
    assert v.max_speed_kmh == 90                       # достоверную не трогаем
    assert v.anomalies == []
