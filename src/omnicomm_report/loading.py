"""Модуль «Работа на погрузке» — для мусоровозов и спецтехники.

Отделяет ПРОДУКТИВНУЮ работу двигателя на стоянке (гидравлика/PTO во время
погрузки) от НЕПРОДУКТИВНОГО простоя, с геопривязкой точек погрузки.

Источник продуктивности определяется АВТОМАТИЧЕСКИ по иерархии достоверности
(спецификация аудита):
  1. 'sensor'      — датчик доп.входа (uniType 0/1, univInputOnTime>0) — ФАКТ;
  2. 'sensor_zero' — датчик есть, но не включался (валидно «не грузил»);
  3. 'rpm'         — НЕТ датчика, но обороты откалиброваны (есть и холостые, и
                     под нагрузкой) — ОЦЕНКА «≈», ограничена временем стоянки;
  4. 'geozone'     — НЕТ датчика/оборотов, но визиты в геозоны-площадки клиента —
                     ОЦЕНКА «≈» (визит = обслуживание); см. estimate_loading_from_stops;
  5. 'gps'         — НЕТ датчика/оборотов/геозон, но есть GPS-трек: короткие
                     остановки маршрута = погрузка, длинные = простой — ОЦЕНКА «≈»;
  6. 'none'        — нет ни одного сигнала → цифру НЕ выдаём.

Единицы Omnicomm уже приведены в data_loader к литрам/часам; сюда приходят
аккумуляторы в базовых единицах (секунды, литры).

Бизнес-инвариант: для 'rpm' всё помечается «≈»; для 'none' значение погрузки не
подставляется (не выдаём 0% как «весь день простой»).
"""

from __future__ import annotations

import math
from typing import Any, Optional

from .models import LoadingPoint, VehicleMetrics

# uniType датчика, пригодный как on/off признак надстройки (0/1).
# uniType=2 — импульсный (счётчик выдач FTC), НЕ on/off PTO — исключаем.
SENSOR_UNI_TYPES = {0, 1}


def classify_and_fill(vm: VehicleMetrics, acc: dict[str, Any]) -> None:
    """Заполнить поля погрузки у `vm` по аккумулятору суточных данных `acc`.

    Ожидаемые ключи acc (суммы по суткам, базовые единицы):
      worked_s, no_move_s, idling_rpm_s, normal_rpm_s, under_load_rpm_s,
      uni_on_s, uni_fuel_l, uni_hour_cons_l, uni_type, uni_present (bool),
      fuel_wo_move_l, max_speed.
    """
    worked = acc.get("worked_s") or 0.0
    no_move = acc.get("no_move_s") or 0.0
    idling = acc.get("idling_rpm_s") or 0.0
    under_load = acc.get("under_load_rpm_s") or 0.0
    normal = acc.get("normal_rpm_s") or 0.0
    uni_present = acc.get("uni_present") and acc.get("uni_type") in SENSOR_UNI_TYPES
    uni_on = acc.get("uni_on_s") or 0.0
    fuel_wo_move = acc.get("fuel_wo_move_l")

    vm.work_no_move_hours = round(no_move / 3600, 2)
    vm.idle_fuel_wo_move_l = round(fuel_wo_move, 1) if fuel_wo_move is not None else None
    vm.vehicle_segment = _segment(acc)

    loading_s: Optional[float]
    if uni_present and uni_on > 0:
        vm.loading_method = "sensor"
        vm.loading_is_estimate = False
        loading_s = uni_on
        vm.loading_fuel_l = round(acc.get("uni_fuel_l") or 0.0, 1)
        # Удельный расход считаем из проверенных тоталов (топливо/часы), а НЕ из
        # univInputHourConsumption: спека помечает его «(л)», но по факту дл —
        # доверять сырому полю нельзя (даёт ×10).
        if loading_s > 0 and vm.loading_fuel_l:
            vm.loading_fuel_per_mh = round(vm.loading_fuel_l / (loading_s / 3600), 1)
    elif uni_present:
        # датчик есть, но не включался за период — валидный «не грузил»
        vm.loading_method = "sensor_zero"
        vm.loading_is_estimate = False
        loading_s = 0.0
        vm.loading_fuel_l = 0.0
    elif under_load > 0:
        # Правило заказчика: обороты >~1000 (полоса «под нагрузкой») + по GPS техника
        # НЕПОДВИЖНА → работает гидравлика (полезная погрузка на месте), а не движение.
        # Omnicomm отдаёт время в полосе workedUnderLoadRPM; «1000» — порог этой полосы
        # (настройка терминала). Холостой ход (<1000) — полоса idlingRPM.
        # Оценка ограничена временем стоянки: грузить нельзя больше, чем стоял с двигателем.
        vm.loading_method = "rpm"
        vm.loading_is_estimate = True
        loading_s = min(under_load, no_move)
        vm.loading_fuel_l = None  # без датчика топливо погрузки не разделяем
    else:
        # ни датчика, ни калибровки оборотов → честно «нет сигнала»
        vm.loading_method = "none"
        vm.loading_is_estimate = False
        loading_s = None

    if loading_s is not None:
        vm.loading_hours = round(loading_s / 3600, 2)
        vm.unproductive_idle_hours = round(max(0.0, no_move - loading_s) / 3600, 2)
        if vm.loading_method == "sensor" and fuel_wo_move is not None and vm.loading_fuel_l is not None:
            vm.unproductive_fuel_l = round(max(0.0, fuel_wo_move - vm.loading_fuel_l), 1)
    # для 'none' loading_hours остаётся None — цифру не выдаём
    _ = (worked, normal, idling)  # полосы оборотов учтены в классификации выше


def _segment(acc: dict[str, Any]) -> str:
    """Грубая сегментация ТС: refuse_truck | special | transport.

    Эвристика без справочника (его нет в API): по макс. скорости и удельному
    расходу надстройки. Уточняется справочником типов от заказчика.
    """
    max_speed = acc.get("max_speed") or 0.0
    if max_speed and max_speed < 20:
        return "special"          # экскаватор/кран: почти не ездит
    if max_speed > 60:
        return "transport"        # магистральный транспорт
    return "refuse_truck"         # городская работа со стоянками — кандидат в мусоровозы


# --- GPS-кластеризация точек погрузки ----------------------------------------

def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Расстояние между координатами, метры."""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def parse_geozone_visits(records: list[dict]) -> dict[str, list["LoadingPoint"]]:
    """Визиты в геозоны → {vehicleId: [LoadingPoint(source='geozone')]}.

    Точные точки погрузки по заведённым площадкам клиента (приоритет над GPS-
    кластерами). Топливо визита в децилитрах → литры (÷10).
    """
    out: dict[str, list[LoadingPoint]] = {}
    for rec in records or []:
        if not isinstance(rec, dict):
            continue
        vid = rec.get("vehicleId") or rec.get("vehicle_id")
        if vid is None:
            continue
        gi = rec.get("geoInfo") or {}
        dur = gi.get("duration") or 0
        fuel = (rec.get("fuel") or {}).get("fuelConsumption")
        fuel_l = round(fuel / 10.0, 1) if isinstance(fuel, (int, float)) else None
        out.setdefault(str(vid), []).append(LoadingPoint(
            latitude=0.0, longitude=0.0,
            start_ts=int(gi.get("startDate") or 0), duration_s=float(dur),
            name=rec.get("geozoneName") or rec.get("geozoneId"),
            source="geozone", fuel_l=fuel_l))
    return out


def estimate_loading_from_stops(
    vm: VehicleMetrics,
    points: list["LoadingPoint"],
    *,
    windowed: bool = True,
    min_s: float = 180.0,
    max_s: float = 900.0,
) -> None:
    """Бессенсорная оценка погрузки по остановкам (GPS-маршрут или геозоны).

    Когда нет датчика надстройки и калибровки оборотов, но есть точки остановок:
    короткие остановки маршрута (двигатель работает, обслуживание площадки) —
    это ПОЛЕЗНАЯ работа; длинные стоянки — непродуктивный простой. Оценка
    ограничена временем работы стоя (`work_no_move_hours`) и помечается «≈».

    windowed=True (GPS-кластеры): берём только остановки [min_s..max_s].
    windowed=False (геозоны-площадки): каждый визит — обслуживание (без окна).
    Метод: 'gps' для трека, 'geozone' для площадок.
    """
    no_move = vm.work_no_move_hours or 0.0
    if not points or no_move <= 0:
        return
    if windowed:
        service = [p for p in points if min_s <= p.duration_s <= max_s]
        method = "gps"
    else:
        service = list(points)
        method = "geozone"
    if not service:
        return
    loading_h = min(sum(p.duration_s for p in service) / 3600.0, no_move)
    vm.loading_method = method
    vm.loading_is_estimate = True
    vm.loading_hours = round(loading_h, 2)
    vm.unproductive_idle_hours = round(max(0.0, no_move - loading_h), 2)
    vm.loading_points = service


def cluster_track_points(
    track: list[dict],
    *,
    radius_m: float = 50.0,
    min_stop_s: float = 180.0,
    min_satellites: int = 4,
    speed_eps: float = 1.5,
) -> list[LoadingPoint]:
    """Свести трек в кластеры стоянок-погрузок.

    Стоянка = подряд идущие точки со `speed`≈0 и достаточным числом спутников,
    близкие по координате; кластер засчитывается, если длился не короче порога.
    Возвращает список LoadingPoint (координата центра, начало, длительность).

    `speed_eps` — порог скорости «стоит», км/ч: на реальной стоянке GPS даёт
    джиттер 0.4–1 км/ч, и строгое `speed>0` дробит стоянку на куски (калибровка
    на боевом треке Горкомтранс). По умолчанию считаем ≤1.5 км/ч — стоянкой.
    """
    points: list[LoadingPoint] = []
    run: list[dict] = []

    def flush() -> None:
        if not run:
            return
        dur = (run[-1].get("date", 0) - run[0].get("date", 0))
        if dur >= min_stop_s:
            lat = sum(p["latitude"] for p in run) / len(run)
            lon = sum(p["longitude"] for p in run) / len(run)
            points.append(LoadingPoint(
                latitude=round(lat, 6), longitude=round(lon, 6),
                start_ts=int(run[0].get("date", 0)), duration_s=float(dur),
            ))

    for p in track:
        if (p.get("satellitesCount") or 0) < min_satellites:
            continue
        if (p.get("speed") or 0) > speed_eps or p.get("latitude") is None:
            flush()
            run = []
            continue
        if run and _haversine_m(run[-1]["latitude"], run[-1]["longitude"],
                                p["latitude"], p["longitude"]) > radius_m:
            flush()
            run = [p]
        else:
            run.append(p)
    flush()
    return points
