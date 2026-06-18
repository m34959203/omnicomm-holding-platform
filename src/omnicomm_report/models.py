"""Единая внутренняя модель данных проекта (ТЗ §16.5).

Общая для режима А (Omnicomm REST API) и режима Б (Excel-выгрузка).
Оба источника приводятся к этим структурам, дальше по конвейеру идёт
только эта модель — модули `validator`, `analytics`, `charts`,
`report_builder` ничего не знают про источник данных.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class Severity(str, Enum):
    """Уровень аномалии. Никаких обвинительных формулировок (ТЗ §7)."""

    OK = "ok"
    NOTE = "note"            # обратить внимание
    REVIEW = "review"        # «требует проверки»


@dataclass
class Anomaly:
    """Помеченное подозрительное значение по ТС. Всегда «требует проверки»."""

    code: str                # машинный код: zero_mileage_with_fuel, high_speed, ...
    message: str             # человекочитаемое описание на русском
    severity: Severity = Severity.REVIEW
    value: Optional[float] = None


@dataclass
class LoadingPoint:
    """Точка погрузки: GPS-кластер стоянки ИЛИ визит в геозону-площадку."""

    latitude: float
    longitude: float
    start_ts: int                         # начало, UNIX UTC
    duration_s: float                     # длительность стоянки/визита, сек
    has_sensor: bool = False              # признак включённой надстройки в окне
    fuel_l: Optional[float] = None        # топливо за сессию, л (если известно)
    name: Optional[str] = None            # название площадки (для геозон)
    source: str = "gps"                   # "gps" (кластер) | "geozone" (визит)


@dataclass
class VehicleMetrics:
    """Показатели одного ТС за период (ТЗ §2, §5).

    Поля, которых нет в источнике, остаются None — это валидно
    (например, Omnicomm вернул код 10 «данных нет» по конкретному ТС).
    """

    # Идентификация
    vehicle_id: str                       # UUID Omnicomm или ID терминала / строка из Excel
    name: str                             # госномер или наименование ТС
    group: Optional[str] = None
    org_id: Optional[str] = None          # узел dim_org (holding-слой: ДЗО/под-ДЗО/подрядчик)

    # Эксплуатационные показатели
    mileage_km: Optional[float] = None            # пробег, км
    fuel_l: Optional[float] = None                # расход топлива, л
    fuel_per_100km: Optional[float] = None        # расход на 100 км
    engine_hours: Optional[float] = None          # моточасы
    engine_idle_hours: Optional[float] = None     # работа двигателя без движения, ч
    fuel_idle_l: Optional[float] = None           # топливо, израсходованное без движения, л
    max_speed_kmh: Optional[float] = None         # максимальная скорость
    speeding_count: Optional[int] = None          # число превышений скорости
    speeding_mileage_km: Optional[float] = None   # пробег с превышением, км

    # --- Модуль «Работа на погрузке» (спецтехника/мусоровозы) ---
    # method: 'sensor' (датчик доп.входа, ФАКТ) | 'rpm' (оценка по оборотам, ≈)
    #         | 'sensor_zero' (датчик есть, не грузил) | 'none' (нет сигнала)
    loading_method: Optional[str] = None
    loading_is_estimate: bool = False         # True для метода 'rpm' (помечать «≈»)
    loading_hours: Optional[float] = None     # время продуктивной погрузки, моточасы
    work_no_move_hours: Optional[float] = None  # вся работа двигателя стоя, моточасы
    unproductive_idle_hours: Optional[float] = None  # простой без надстройки, моточасы
    loading_fuel_l: Optional[float] = None    # топливо на погрузку, л (только датчик)
    loading_fuel_per_mh: Optional[float] = None  # удельный расход гидравлики, л/мч
    idle_fuel_wo_move_l: Optional[float] = None  # топливо на стоянке всего, л
    unproductive_fuel_l: Optional[float] = None  # топливо непродуктивного простоя, л
    vehicle_segment: Optional[str] = None     # refuse_truck | special | transport
    loading_points: list["LoadingPoint"] = field(default_factory=list)

    # --- Паспорт техники (статичные данные, вводятся один раз) ---
    vehicle_type: Optional[str] = None        # тип: refuse_truck/excavator/... (vehicle_types)
    brand: Optional[str] = None               # марка (КАМАЗ, KOMATSU…)
    model: Optional[str] = None               # модель
    year: Optional[int] = None                # год выпуска
    reg_number: Optional[str] = None          # госномер
    tank_capacity_l: Optional[float] = None   # объём бака, л

    # --- Нормы расхода и перерасход/экономия (вводятся клиентом один раз) ---
    engine_model: Optional[str] = None        # марка/модель двигателя (для справки)
    norm_l_per_100km: Optional[float] = None  # норма расхода в движении, л/100км
    norm_l_per_mh: Optional[float] = None      # норма расхода на моточас, л/мч
    norm_coeff: float = 1.0                    # множитель к норме (зима/свалка/город/износ)
    overrun_basis: Optional[str] = None       # "100km" | "mh" — по какой норме считали
    overrun_l: Optional[float] = None         # отклонение факт−норма за период, л (+перерасход/−экономия)
    overrun_cost_kzt: Optional[float] = None  # стоимость отклонения, ₸ (+перерасход/−экономия)

    # Сервис
    has_data: bool = True                 # False → ТС помечен «нет данных» (коды 5/7/9/10/11)
    no_data_reason: Optional[str] = None  # причина отсутствия данных
    anomalies: list[Anomaly] = field(default_factory=list)
    raw: dict = field(default_factory=dict)  # исходная строка/ответ для трассировки

    @property
    def loading_utilization(self) -> Optional[float]:
        """Доля полезной работы из стоянки с двигателем, 0..1."""
        if self.loading_hours is not None and self.work_no_move_hours:
            return min(1.0, self.loading_hours / self.work_no_move_hours)
        return None

    @property
    def fuel_per_100km_calc(self) -> Optional[float]:
        """Расход на 100 км — берём из источника, иначе считаем сами."""
        if self.fuel_per_100km is not None:
            return self.fuel_per_100km
        if self.fuel_l is not None and self.mileage_km and self.mileage_km > 0:
            return round(self.fuel_l / self.mileage_km * 100, 1)
        return None

    @property
    def fuel_per_motorhour(self) -> Optional[float]:
        """Расход на моточас, л/мч — корректная метрика для спецтехники."""
        if self.fuel_l is not None and self.engine_hours and self.engine_hours > 0:
            return round(self.fuel_l / self.engine_hours, 1)
        return None

    @property
    def idle_hours_share(self) -> Optional[float]:
        """Доля холостого хода в моточасах, 0..1."""
        if self.engine_idle_hours is not None and self.engine_hours and self.engine_hours > 0:
            return min(1.0, self.engine_idle_hours / self.engine_hours)
        return None

    @property
    def is_stationary(self) -> bool:
        """Стационарная спецтехника: мало пробега на моточас (см. config)."""
        if self.engine_hours and self.engine_hours > 0:
            km = self.mileage_km or 0.0
            return (km / self.engine_hours) < 5.0  # STATIONARY_KM_PER_HOUR
        return False


@dataclass
class ReportPeriod:
    """Период отчёта. Внутри храним datetime, в API уходит UNIX UTC (ТЗ §4.1)."""

    start: datetime
    end: datetime

    @property
    def start_ts(self) -> int:
        return int(self.start.timestamp())

    @property
    def end_ts(self) -> int:
        return int(self.end.timestamp())

    def human(self) -> str:
        return f"{self.start:%d.%m.%Y} — {self.end:%d.%m.%Y}"


@dataclass
class FleetKPI:
    """Агрегаты по всему парку (ТЗ §5). Заполняет модуль analytics."""

    vehicles_total: int = 0
    vehicles_with_data: int = 0
    total_mileage_km: float = 0.0
    total_fuel_l: float = 0.0
    weighted_fuel_per_100km: float = 0.0   # средневзвешенный по пробегу (весь парк)
    mobile_fuel_per_100km: float = 0.0     # средневзвеш. л/100км только по мобильным ТС
    total_engine_hours: float = 0.0
    fuel_idle_l: float = 0.0
    fuel_idle_share: float = 0.0           # доля топлива без движения, 0..1
    speeding_mileage_share: float = 0.0    # доля пробега с превышением, 0..1
    top_fuel_vehicle: Optional[str] = None
    top_anomalies_vehicle: Optional[str] = None
    max_speed_kmh: float = 0.0

    # Использование / холостой ход (ТЗ §5 + P0)
    total_idle_hours: float = 0.0          # суммарный холостой ход, моточасы
    movement_hours: float = 0.0            # моточасы в движении
    idle_hours_share: float = 0.0          # доля холостого хода в моточасах, 0..1
    weighted_fuel_per_motorhour: float = 0.0   # средневзвеш. л/моточас (спецтехника)
    stationary_count: int = 0              # ТС-спецтехника (метрика л/мч)
    mobile_count: int = 0                  # мобильные ТС (метрика л/100км)
    # Коэффициент использования (ТЗ C1): моточасы к доступному времени.
    time_fund_hours_per_day: float = 0.0   # нормативный фонд клиента, ч/сутки (0 = не задан)
    utilization_calendar: float = 0.0      # моточасы / (ТС × сутки × 24), 0..1
    utilization_fund: float = 0.0          # моточасы / (ТС × сутки × фонд); >1 = сверх фонда
    # Срезы по классам ТС — для baseline v2 (savings): ставки мобильных и
    # спецтехники раздельно, чтобы состав парка не искажал счётчик экономии.
    mobile_fuel_l: float = 0.0             # топливо мобильных ТС, л
    mobile_fuel_idle_l: float = 0.0        # топливо мобильных без движения, л
    mobile_engine_hours: float = 0.0       # моточасы мобильных
    mobile_idle_hours: float = 0.0         # холостой ход мобильных, ч
    mobile_mileage_km: float = 0.0         # пробег мобильных, км
    stationary_fuel_l: float = 0.0         # топливо спецтехники, л
    stationary_engine_hours: float = 0.0   # моточасы спецтехники
    # Себестоимость вывоза (ТКО): объём за период по данным полигона (ввод).
    haul_volume_m3: float = 0.0            # вывезено, м³ (0 = не задано)
    fuel_cost_per_m3: float = 0.0          # топливная себестоимость, ₸/м³

    # Деньги (валюта — тенге, ₸) — P1
    fuel_price_kzt: float = 0.0            # цена топлива, ₸/л (0 = не задана)
    total_fuel_cost: float = 0.0           # стоимость всего топлива, ₸
    idle_fuel_cost: float = 0.0            # стоимость топлива на простое, ₸
    potential_savings: float = 0.0         # потенциальная экономия на простоях, ₸
    savings_is_estimate: bool = True       # True = от всего idle (нет датчиков); False = от непродуктивного (датчик)
    fuel_cost_per_km: float = 0.0          # удельная стоимость, ₸/км
    fuel_cost_per_mh: float = 0.0          # удельная стоимость, ₸/моточас

    # Модуль «Работа на погрузке» — агрегаты по парку
    vehicles_with_loading_sensor: int = 0  # ТС с датчиком надстройки (ФАКТ)
    total_loading_hours_sensor: float = 0.0    # моточасы погрузки по датчику
    total_loading_hours_estimate: float = 0.0  # моточасы погрузки по оборотам (≈)
    total_loading_fuel_l: float = 0.0      # топливо на погрузку (датчик), л
    total_loading_fuel_cost: float = 0.0   # стоимость погрузки, ₸
    total_unproductive_idle_hours: float = 0.0  # непродуктивный простой, моточасы
    total_unproductive_fuel_l: float = 0.0      # топливо непродуктивного простоя, л
    total_unproductive_fuel_cost: float = 0.0   # потери на простое, ₸
    fleet_loading_utilization: float = 0.0      # доля полезной стоянки по парку, 0..1
    total_loading_points: int = 0          # обслужено точек погрузки (GPS-кластеры)

    # Перерасход/экономия по нормам (P-нормы)
    vehicles_with_norm: int = 0            # ТС с заданной нормой расхода
    vehicles_over_norm: int = 0            # ТС с перерасходом
    total_overrun_l: float = 0.0           # суммарный перерасход, л (>0)
    total_overrun_cost: float = 0.0        # суммарный перерасход, ₸
    total_economy_l: float = 0.0           # суммарная экономия, л (>0)
    total_economy_cost: float = 0.0        # суммарная экономия, ₸


@dataclass
class FleetReport:
    """Полный результат анализа — вход для charts и report_builder."""

    period: ReportPeriod
    client_name: str
    vehicles: list[VehicleMetrics]
    kpi: FleetKPI
    conclusions: list[str] = field(default_factory=list)   # управленческие выводы (ТЗ §6)
    recommendations: list[str] = field(default_factory=list)  # план действий (динамический)
    source: str = "excel"                                  # "api" | "excel"
    season: str = "summer"                                 # "summer" | "winter" — режим норм
    generated_at: Optional[datetime] = None
    # Тренды период-к-периоду (P2): KPI прошлого прогона и относительные дельты.
    previous_kpi: Optional["FleetKPI"] = None
    trends: dict = field(default_factory=dict)             # {метрика: дельта в %}
    # Доп. аналитика (алерты, скоринг ТС, «что если», бенчмарк по клиентам).
    alerts: list[str] = field(default_factory=list)
    scorecard: list = field(default_factory=list)         # рейтинг ТС [(имя, балл, ...)]
    whatif: list = field(default_factory=list)            # сценарии экономии простоя
    benchmark: dict = field(default_factory=dict)         # сравнение с другими клиентами
    # Счётчик подтверждённой экономии (savings.py): baseline, запись периода,
    # накопленный итог, серия для графика. Пусто = baseline не заморожен.
    savings: dict = field(default_factory=dict)
