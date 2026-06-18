"""Контроль качества данных по ТС (ТЗ §3 «проверка», §7).

Третий шаг конвейера: `data_loader → validator → analytics → ...`.
Принимает уже приведённый к `VehicleMetrics` список и проставляет
аномалии. Все формулировки — официальные, без обвинений: каждая
аномалия означает «требует проверки», а не «нарушение/слив» (ТЗ §7,
бизнес-инвариант CLAUDE.md). Перерасход без согласованных норм
нарушением не считается — только поводом для проверки.

Модуль ничего не знает про источник данных (API/Excel) — работает
исключительно с контрактом `models.py`.
"""

from __future__ import annotations

from .config import MAX_PLAUSIBLE_SPEED_KMH
from .models import Anomaly, Severity, VehicleMetrics

# --- Пороговые значения -------------------------------------------------------
# Вынесены в именованные константы: пороги — продуктовая настройка качества
# данных, а не магические числа по месту. Подобраны как «заведомо аномальные»
# для дорожной техники/грузовиков, чтобы не плодить ложные срабатывания.

# Скорость выше этого порога физически сомнительна для коммерческого парка —
# чаще это ошибка датчика/трекинга, чем реальная езда; повод перепроверить.
MAX_SPEED_THRESHOLD_KMH = 130.0

# Расход на 100 км выше порога — крайне высокий даже для тяжёлой техники.
# Это НЕ обвинение в перерасходе (нормы не согласованы), а сигнал проверить
# корректность данных по пробегу/топливу.
HIGH_FUEL_PER_100KM_THRESHOLD = 100.0

# Доля простоя двигателя (работа без движения) от общих моточасов.
# Выше — двигатель значительную часть времени работал на месте, стоит уточнить.
IDLE_SHARE_THRESHOLD = 0.5


# --- Машинные коды аномалий (для трассировки и группировки в отчёте) ----------

CODE_HIGH_SPEED = "high_speed"
CODE_ZERO_MILEAGE_WITH_FUEL = "zero_mileage_with_fuel"
CODE_ZERO_FUEL_WITH_ACTIVITY = "zero_fuel_with_activity"
CODE_HIGH_FUEL_PER_100KM = "high_fuel_per_100km"
CODE_HIGH_IDLE_SHARE = "high_idle_share"
CODE_NO_DATA = "no_data"
CODE_NEGATIVE_VALUE = "negative_value"

NO_DATA_REASON = "Недостаточно данных по ТС"

# Числовые метрики, которые проверяем на отрицательные значения.
# (имя поля -> человекочитаемое название для сообщения)
_NUMERIC_FIELDS: dict[str, str] = {
    "mileage_km": "пробег",
    "fuel_l": "расход топлива",
    "fuel_per_100km": "расход на 100 км",
    "engine_hours": "моточасы",
    "engine_idle_hours": "работа двигателя без движения",
    "fuel_idle_l": "топливо без движения",
    "max_speed_kmh": "максимальная скорость",
    "speeding_count": "число превышений скорости",
    "speeding_mileage_km": "пробег с превышением",
}


def validate(vehicles: list[VehicleMetrics]) -> list[VehicleMetrics]:
    """Проставить аномалии по каждому ТС (мутирует и возвращает тот же список).

    Поведение:
    - заполняет `vehicle.anomalies` найденными `Anomaly`;
    - при полном отсутствии ключевых метрик — `has_data=False` и причина;
    - сохраняет уже выставленный `has_data=False` (например, код 10 из API).

    Возвращает тот же список, чтобы вписаться в конвейер без копий.
    """
    for vehicle in vehicles:
        # Перезапускаем проверку с чистого листа — повторный вызов validate()
        # не должен дублировать аномалии.
        vehicle.anomalies = []
        _validate_one(vehicle)
    return vehicles


def _validate_one(vehicle: VehicleMetrics) -> None:
    """Проверки одного ТС. Порядок: сначала структурные, затем содержательные."""
    # 1. Отрицательные значения — некорректные данные, проверяем всегда первыми:
    #    дальнейшие расчётные проверки на «грязных» числах смысла не имеют.
    _check_negative_values(vehicle)

    # 2. Полное отсутствие ключевых метрик. Если data_loader уже пометил ТС
    #    «нет данных» (коды 5/7/9/10/11) — уважаем это; иначе определяем сами.
    if _is_empty(vehicle):
        vehicle.has_data = False
        if not vehicle.no_data_reason:
            vehicle.no_data_reason = NO_DATA_REASON
        vehicle.anomalies.append(
            Anomaly(
                code=CODE_NO_DATA,
                message=NO_DATA_REASON,
                severity=Severity.NOTE,  # информационная пометка, не «проверка»
            )
        )
        # Считать скорость/расход по пустому ТС нечего — выходим.
        return

    # Если источник заранее сказал «нет данных» — содержательные метрики
    # недостоверны, дальше не анализируем.
    if not vehicle.has_data:
        return

    # 3. Содержательные аномалии (severity=REVIEW, «требует проверки»).
    _check_high_speed(vehicle)
    _check_zero_mileage_with_fuel(vehicle)
    _check_zero_fuel_with_activity(vehicle)
    _check_high_fuel_per_100km(vehicle)
    _check_high_idle_share(vehicle)


# --- Отдельные проверки -------------------------------------------------------

def _check_negative_values(vehicle: VehicleMetrics) -> None:
    """Любая отрицательная метрика физически некорректна — требует проверки."""
    for field_name, human in _NUMERIC_FIELDS.items():
        value = getattr(vehicle, field_name, None)
        if value is not None and value < 0:
            vehicle.anomalies.append(
                Anomaly(
                    code=CODE_NEGATIVE_VALUE,
                    message=(
                        f"Некорректное (отрицательное) значение «{human}» "
                        f"— требует проверки"
                    ),
                    severity=Severity.REVIEW,
                    value=float(value),
                )
            )


def _check_high_speed(vehicle: VehicleMetrics) -> None:
    """Аномально высокая максимальная скорость — вероятна ошибка датчика/GPS.

    Свыше порога правдоподобия (напр. 655 км/ч) — это сбой: значение УБИРАЕМ из
    показателей (иначе портит макс. по парку), помечаем «требует проверки».
    В диапазоне «высокая, но возможная» — оставляем, только флажим.
    """
    speed = vehicle.max_speed_kmh
    if speed is None:
        return
    if speed > MAX_PLAUSIBLE_SPEED_KMH:
        vehicle.anomalies.append(
            Anomaly(
                code=CODE_HIGH_SPEED,
                message=(
                    "Недостоверная максимальная скорость (вероятно сбой GPS) "
                    "— требует проверки"
                ),
                severity=Severity.REVIEW,
                value=float(speed),
            )
        )
        vehicle.max_speed_kmh = None   # исключаем из KPI/отчёта
    elif speed > MAX_SPEED_THRESHOLD_KMH:
        vehicle.anomalies.append(
            Anomaly(
                code=CODE_HIGH_SPEED,
                message=(
                    "Зафиксирована аномально высокая максимальная скорость "
                    "— требует проверки"
                ),
                severity=Severity.REVIEW,
                value=float(speed),
            )
        )


def _check_zero_mileage_with_fuel(vehicle: VehicleMetrics) -> None:
    """Нулевой пробег при ненулевом расходе — данные противоречивы."""
    fuel = vehicle.fuel_l
    mileage = vehicle.mileage_km
    # «mileage_km == 0 или None» при положительном расходе.
    if fuel is not None and fuel > 0 and (mileage is None or mileage == 0):
        vehicle.anomalies.append(
            Anomaly(
                code=CODE_ZERO_MILEAGE_WITH_FUEL,
                message=(
                    "Нулевой пробег при ненулевом расходе топлива "
                    "— требует проверки"
                ),
                severity=Severity.REVIEW,
                value=float(fuel),
            )
        )


def _check_zero_fuel_with_activity(vehicle: VehicleMetrics) -> None:
    """Нулевой расход при заметном пробеге/наработке — молчащий ДУТ.

    Такие ТС не должны проходить как «экономия к норме» — это пробел данных.
    """
    fuel = vehicle.fuel_l or 0.0
    mileage = vehicle.mileage_km or 0.0
    hours = vehicle.engine_hours or 0.0
    if fuel <= 0 and (mileage > 10 or hours > 1):
        vehicle.anomalies.append(
            Anomaly(
                code=CODE_ZERO_FUEL_WITH_ACTIVITY,
                message=(
                    "Нулевой расход топлива при пробеге/наработке — "
                    "проверить датчик уровня топлива"
                ),
                severity=Severity.REVIEW,
                value=float(mileage or hours),
            )
        )


def _check_high_fuel_per_100km(vehicle: VehicleMetrics) -> None:
    """Очень высокий расход на 100 км — повод проверить, а не констатировать."""
    fuel_per_100 = vehicle.fuel_per_100km_calc
    if fuel_per_100 is not None and fuel_per_100 > HIGH_FUEL_PER_100KM_THRESHOLD:
        vehicle.anomalies.append(
            Anomaly(
                code=CODE_HIGH_FUEL_PER_100KM,
                message=(
                    "Высокий расход на 100 км — требует проверки "
                    "(без утверждённых норм не является нарушением)"
                ),
                severity=Severity.REVIEW,
                value=float(fuel_per_100),
            )
        )


def _check_high_idle_share(vehicle: VehicleMetrics) -> None:
    """Большая доля работы двигателя без движения относительно моточасов."""
    engine_hours = vehicle.engine_hours
    idle_hours = vehicle.engine_idle_hours
    # Доля считается только при положительных моточасах, иначе деления нет.
    if (
        engine_hours is not None
        and engine_hours > 0
        and idle_hours is not None
        and idle_hours >= 0
    ):
        share = idle_hours / engine_hours
        if share > IDLE_SHARE_THRESHOLD:
            vehicle.anomalies.append(
                Anomaly(
                    code=CODE_HIGH_IDLE_SHARE,
                    message=(
                        "Значительная работа двигателя без движения "
                        "— требует проверки"
                    ),
                    severity=Severity.REVIEW,
                    value=round(share, 2),
                )
            )


def _is_empty(vehicle: VehicleMetrics) -> bool:
    """ТС «пустой», если нет ни пробега, ни расхода, ни моточасов.

    Это ключевые показатели отчёта: без любого из них ТС в анализе бесполезно.
    None и 0 трактуем как «значения нет» (нулевой пробег и нулевой расход
    одновременно = терминал ничего не отдал за период).
    """
    return (
        not vehicle.mileage_km
        and not vehicle.fuel_l
        and not vehicle.engine_hours
    )


# --- Сводка для отчёта --------------------------------------------------------

def validation_summary(vehicles: list[VehicleMetrics]) -> dict:
    """Счётчики по результатам валидации — для шапки отчёта/логов (ТЗ §3).

    Возвращает: всего ТС, сколько с данными, сколько с аномалиями,
    общее число аномалий и разбивку по машинным кодам.
    """
    by_code: dict[str, int] = {}
    with_anomalies = 0
    with_data = 0
    total_anomalies = 0

    for vehicle in vehicles:
        if vehicle.has_data:
            with_data += 1
        if vehicle.anomalies:
            with_anomalies += 1
            total_anomalies += len(vehicle.anomalies)
            for anomaly in vehicle.anomalies:
                by_code[anomaly.code] = by_code.get(anomaly.code, 0) + 1

    return {
        "vehicles_total": len(vehicles),
        "vehicles_with_data": with_data,
        "vehicles_with_anomalies": with_anomalies,
        "anomalies_total": total_anomalies,
        "anomalies_by_code": by_code,
    }
