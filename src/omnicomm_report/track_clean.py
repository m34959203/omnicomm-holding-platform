"""Физическая чистка GPS-трека на приёме (holding-слой, §4 дизайна).

Power BI резал выбросы скорости (228–450 км/ч) окном по длительности (10–90 с) —
костыль, теряющий и реальные короткие нарушения (<10 с), и устойчивые длинные
(>90 с). Здесь чистим по **физике движения**: между соседними точками считаем
расстояние/Δt → подразумеваемую скорость. «Телепорт-и-возврат» (точка, подойти к
которой и уйти от которой физически невозможно, а соседи без неё согласованы) —
**выбрасываем точку, а не всю запись**. Факт чистки ПОМЕЧАЕМ (аудит-след), не
удаляем молча — для гос-холдинга чистка должна быть объяснимой.

Точка трека Omnicomm: `{latitude, longitude, speed (км/ч), date (UNIX сек),
satellitesCount}` (формат сверен с `loading.cluster_track_points`).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from .config import MAX_PLAUSIBLE_SPEED_KMH

CODE_GPS_OUTLIER_TRACK = "gps_outlier_track"

_EARTH_R_M = 6_371_000.0


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * _EARTH_R_M * math.asin(min(1.0, math.sqrt(a)))


def _implied_kmh(a: dict, b: dict) -> Optional[float]:
    """Подразумеваемая скорость перехода a→b, км/ч. None — нет координат/времени."""
    lat1, lon1 = a.get("latitude"), a.get("longitude")
    lat2, lon2 = b.get("latitude"), b.get("longitude")
    if None in (lat1, lon1, lat2, lon2):
        return None
    try:
        dt = float(b.get("date", 0)) - float(a.get("date", 0))
    except (TypeError, ValueError):
        return None
    dist = _haversine_m(lat1, lon1, lat2, lon2)
    if dt <= 0:                                   # одинаковое/обратное время:
        return math.inf if dist > 1.0 else 0.0    # дальний скачок = телепорт
    return dist / dt * 3.6


def _max_reported(points: list[dict], limit: float) -> Optional[float]:
    """Макс. собственная скорость среди точек, не превышающая порог правдоподобия."""
    speeds = [float(p["speed"]) for p in points
              if p.get("speed") is not None and float(p["speed"]) <= limit]
    return round(max(speeds), 1) if speeds else None


@dataclass
class TrackCleanResult:
    clean: list[dict]                          # точки без выбросов
    dropped_indices: list[int]                 # индексы выброшенных точек (в исходном треке)
    plausible_max_speed_kmh: Optional[float]   # макс. правдоподобная скорость по треку

    @property
    def dropped_count(self) -> int:
        return len(self.dropped_indices)


def clean_track(track: list[dict], *,
                max_speed_kmh: float = MAX_PLAUSIBLE_SPEED_KMH) -> TrackCleanResult:
    """Очистить GPS-трек от физически невозможных выбросов («телепорт-и-возврат»).

    Точка i — выброс, если подразумеваемая скорость подхода (от предыдущей оставленной)
    И ухода (к следующей) превышает порог, а соседи без неё согласованы (мост ≤ порога).
    Так не страдают реальные быстрые участки с разрывами трека. Возвращает очищенный
    трек, индексы выброшенных точек и правдоподобную макс. скорость.
    """
    pts = list(track or [])
    if len(pts) < 3:
        return TrackCleanResult(pts, [], _max_reported(pts, max_speed_kmh))

    dropped: set[int] = set()
    n = len(pts)
    for i in range(1, n - 1):
        # предыдущая НЕ выброшенная точка (чтобы цепочка выбросов не маскировала)
        j = i - 1
        while j >= 0 and j in dropped:
            j -= 1
        if j < 0:
            continue
        s_in = _implied_kmh(pts[j], pts[i])
        s_out = _implied_kmh(pts[i], pts[i + 1])
        s_bridge = _implied_kmh(pts[j], pts[i + 1])   # согласованы ли соседи без i
        if (s_in is not None and s_out is not None
                and s_in > max_speed_kmh and s_out > max_speed_kmh
                and (s_bridge is None or s_bridge <= max_speed_kmh)):
            dropped.add(i)

    clean = [p for k, p in enumerate(pts) if k not in dropped]
    return TrackCleanResult(clean, sorted(dropped),
                            _max_reported(clean, max_speed_kmh))


def reconcile_vehicle_speed(vehicle, track: list[dict], *,
                            max_speed_kmh: float = MAX_PLAUSIBLE_SPEED_KMH) -> TrackCleanResult:
    """Согласовать `vehicle.max_speed_kmh` с правдоподобной по очищенному треку.

    - Если в треке были выбросы — пометить аномалию «требует проверки» (не молча).
    - Если агрегированная макс. скорость недостоверна (нет или выше порога
      правдоподобия) — заменить на правдоподобную по треку. Достоверную НЕ трогаем
      (трек может не попасть в реальный пик из-за дискретизации).
    """
    from .models import Anomaly, Severity

    res = clean_track(track, max_speed_kmh=max_speed_kmh)
    if res.dropped_count:
        vehicle.anomalies.append(Anomaly(
            code=CODE_GPS_OUTLIER_TRACK,
            message=(f"Отброшены GPS-выбросы трека ({res.dropped_count} "
                     "точек, вероятно сбой навигации) — требует проверки"),
            severity=Severity.REVIEW,
            value=float(res.dropped_count),
        ))
    cur = vehicle.max_speed_kmh
    if res.plausible_max_speed_kmh is not None and (cur is None or cur > max_speed_kmh):
        vehicle.max_speed_kmh = res.plausible_max_speed_kmh
    return res
