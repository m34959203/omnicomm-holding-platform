"""Расчёт KPI парка и управленческих выводов (ТЗ §5, §6).

Модуль работает только с единой моделью данных (`models.py`) и не знает
про источник (API/Excel). Считаем агрегаты по парку, формируем официальные
формулировки для отчёта. Стиль выводов — деловой, без обвинений:
перерасход не утверждается без согласованных норм (бизнес-инвариант CLAUDE.md).
"""

from __future__ import annotations

from omnicomm_report import config, norms as norms_mod, vehicle_types
from omnicomm_report.models import (
    FleetKPI,
    FleetReport,
    ReportPeriod,
    VehicleMetrics,
)


# --- Вспомогательные функции --------------------------------------------------


def _safe_div(numerator: float, denominator: float) -> float:
    """Деление без ZeroDivision — пустой знаменатель даёт 0.0.

    Используем везде, где знаменатель агрегируется по парку и теоретически
    может оказаться нулём (нет данных, нулевой пробег/расход).
    """
    if denominator:
        return numerator / denominator
    return 0.0


def _sum_attr(vehicles: list[VehicleMetrics], attr: str) -> float:
    """Сумма по числовому полю ТС, None-значения трактуем как отсутствие вклада."""
    total = 0.0
    for v in vehicles:
        value = getattr(v, attr)
        if value is not None:
            total += value
    return total


def _fmt(value: float, decimals: int = 0) -> str:
    """Русское форматирование чисел: пробел — разделитель тысяч, запятая — дробь.

    Почему свой helper: locale в контейнере может быть не настроен (C/POSIX),
    поэтому формируем строку вручную, не полагаясь на системную локаль.
    """
    rounded = round(value, decimals)
    if decimals <= 0:
        # Целое число: группируем тысячи неразрывным пробелом.
        int_str = f"{int(round(rounded)):,}".replace(",", " ")
        return int_str
    # Дробное: отделяем целую часть, группируем её, дробную — через запятую.
    int_part, frac_part = f"{rounded:.{decimals}f}".split(".")
    int_grouped = f"{int(int_part):,}".replace(",", " ")
    return f"{int_grouped},{frac_part}"


def _fmt_pct(share: float, decimals: int = 1) -> str:
    """Доля 0..1 → строка процента по-русски (без знака %)."""
    return _fmt(share * 100, decimals)


def _fmt_money(value: float) -> str:
    """Сумма в тенге: целое с разделителем тысяч + знак валюты."""
    return f"{_fmt(value)} {config.CURRENCY}"


# --- KPI ----------------------------------------------------------------------


def compute_kpi(
    vehicles: list[VehicleMetrics],
    fuel_price_kzt: float = 0.0,
) -> FleetKPI:
    """Свести показатели парка в `FleetKPI` (ТЗ §5).

    В агрегаты идут только ТС с `has_data=True`: ТС с кодами 5/7/9/10/11
    помечены «нет данных» и не должны искажать средневзвешенные величины.
    Все деления защищены от нуля; доли хранятся как дробь 0..1.

    :param fuel_price_kzt: цена топлива в ₸/л для денежной оценки (0 — без денег).
    """
    kpi = FleetKPI()
    kpi.vehicles_total = len(vehicles)
    kpi.fuel_price_kzt = fuel_price_kzt

    # Берём только ТС с данными — остальные не участвуют в расчёте.
    active = [v for v in vehicles if v.has_data]
    kpi.vehicles_with_data = len(active)
    if not active:
        return kpi

    # Базовые суммы по парку.
    kpi.total_mileage_km = round(_sum_attr(active, "mileage_km"), 1)
    kpi.total_fuel_l = round(_sum_attr(active, "fuel_l"), 1)
    kpi.total_engine_hours = round(_sum_attr(active, "engine_hours"), 1)
    kpi.fuel_idle_l = round(_sum_attr(active, "fuel_idle_l"), 1)

    # Моточасы: холостой ход и движение, доля простоя (P0 — utilization).
    kpi.total_idle_hours = round(_sum_attr(active, "engine_idle_hours"), 1)
    kpi.movement_hours = round(max(0.0, kpi.total_engine_hours - kpi.total_idle_hours), 1)
    kpi.idle_hours_share = _safe_div(kpi.total_idle_hours, kpi.total_engine_hours)

    # Классификация ТС: мобильные (л/100км) vs спецтехника (л/моточас).
    stationary = [v for v in active if v.is_stationary]
    kpi.stationary_count = len(stationary)
    kpi.mobile_count = len(active) - len(stationary)
    # Средневзвешенный расход на моточас — по суммам, как и л/100км.
    kpi.weighted_fuel_per_motorhour = round(
        _safe_div(kpi.total_fuel_l, kpi.total_engine_hours), 1
    )

    # Деньги (₸) — P1. Считаем только при заданной цене топлива.
    # potential_savings уточняется в _aggregate_loading (от НЕпродуктивного простоя).
    if fuel_price_kzt and fuel_price_kzt > 0:
        kpi.total_fuel_cost = round(kpi.total_fuel_l * fuel_price_kzt, 0)
        kpi.idle_fuel_cost = round(kpi.fuel_idle_l * fuel_price_kzt, 0)
        kpi.fuel_cost_per_km = round(_safe_div(kpi.total_fuel_cost, kpi.total_mileage_km), 1)
        kpi.fuel_cost_per_mh = round(_safe_div(kpi.total_fuel_cost, kpi.total_engine_hours), 1)

    # Средневзвешенный расход — суммарное топливо на суммарный пробег,
    # НЕ среднее средних: крупные ТС не должны теряться в усреднении.
    kpi.weighted_fuel_per_100km = round(
        _safe_div(kpi.total_fuel_l, kpi.total_mileage_km) * 100, 1
    )
    # Только по мобильным ТС — корректный л/100 км для титула: спецтехника и
    # мусоровозы на околонулевом пробеге завышают общий показатель (Cowork-ревью).
    mobile = [v for v in active if not v.is_stationary]
    mob_fuel = _sum_attr(mobile, "fuel_l")
    mob_km = _sum_attr(mobile, "mileage_km")
    kpi.mobile_fuel_per_100km = round(_safe_div(mob_fuel, mob_km) * 100, 1)

    # Срезы по классам — в KPI (снапшоты истории несут их для baseline v2).
    kpi.mobile_fuel_l = round(mob_fuel, 1)
    kpi.mobile_mileage_km = round(mob_km, 1)
    kpi.mobile_fuel_idle_l = round(_sum_attr(mobile, "fuel_idle_l"), 1)
    kpi.mobile_engine_hours = round(_sum_attr(mobile, "engine_hours"), 1)
    kpi.mobile_idle_hours = round(_sum_attr(mobile, "engine_idle_hours"), 1)
    kpi.stationary_fuel_l = round(_sum_attr(stationary, "fuel_l"), 1)
    kpi.stationary_engine_hours = round(_sum_attr(stationary, "engine_hours"), 1)

    # Доля топлива без движения (простои/прогрев) — 0..1.
    kpi.fuel_idle_share = _safe_div(kpi.fuel_idle_l, kpi.total_fuel_l)

    # Доля пробега с превышением скорости. Прямой источник — speeding_mileage_km.
    # Если по парку его нет вовсе, оценить по пробегу невозможно — оставляем 0
    # (speeding_count даёт лишь количество событий, а не долю пробега).
    speeding_mileage = _sum_attr(active, "speeding_mileage_km")
    has_speeding_mileage = any(
        v.speeding_mileage_km is not None for v in active
    )
    if has_speeding_mileage:
        kpi.speeding_mileage_share = _safe_div(
            speeding_mileage, kpi.total_mileage_km
        )
    else:
        kpi.speeding_mileage_share = 0.0

    # Максимальная скорость по парку.
    speeds = [v.max_speed_kmh for v in active if v.max_speed_kmh is not None]
    kpi.max_speed_kmh = round(max(speeds), 1) if speeds else 0.0

    # Лидер по расходу топлива (управленческая «зона внимания»).
    fuel_candidates = [v for v in active if v.fuel_l is not None]
    if fuel_candidates:
        kpi.top_fuel_vehicle = max(
            fuel_candidates, key=lambda v: v.fuel_l or 0.0
        ).name

    # Лидер по числу аномалий — у кого больше всего пометок «требует проверки».
    anomaly_candidates = [v for v in active if v.anomalies]
    if anomaly_candidates:
        kpi.top_anomalies_vehicle = max(
            anomaly_candidates, key=lambda v: len(v.anomalies)
        ).name

    _aggregate_loading(active, kpi, fuel_price_kzt)
    _aggregate_norms(active, kpi)
    return kpi


def _sanitize_speed_by_type(vehicles: list[VehicleMetrics]) -> None:
    """Отсев недостоверной макс. скорости по классу ТС (мусоровоз ≠ 168 км/ч).

    Глобальный >200 уже снят валидатором; здесь — более строгий класс-зависимый
    предел. Значение убирается из KPI + нейтральная пометка «требует проверки».
    """
    from omnicomm_report.models import Anomaly, Severity
    for v in vehicles:
        if not v.has_data or v.max_speed_kmh is None:
            continue
        cap = config.MAX_PLAUSIBLE_SPEED_BY_TYPE.get(
            v.vehicle_type, config.MAX_PLAUSIBLE_SPEED_KMH)
        if v.max_speed_kmh > cap:
            v.anomalies.append(Anomaly(
                code="speed_glitch",
                message="Недостоверная максимальная скорость (сбой GPS) — требует проверки",
                severity=Severity.REVIEW, value=float(v.max_speed_kmh)))
            v.max_speed_kmh = None


def _aggregate_norms(active: list[VehicleMetrics], kpi: FleetKPI) -> None:
    """Свести перерасход/экономию по нормам в KPI парка."""
    for v in active:
        if v.overrun_l is None:
            continue
        kpi.vehicles_with_norm += 1
        if v.overrun_l > 0:
            kpi.vehicles_over_norm += 1
            kpi.total_overrun_l += v.overrun_l
            kpi.total_overrun_cost += v.overrun_cost_kzt or 0.0
        else:
            kpi.total_economy_l += -v.overrun_l
            kpi.total_economy_cost += -(v.overrun_cost_kzt or 0.0)
    kpi.total_overrun_l = round(kpi.total_overrun_l, 1)
    kpi.total_economy_l = round(kpi.total_economy_l, 1)
    kpi.total_overrun_cost = round(kpi.total_overrun_cost, 0)
    kpi.total_economy_cost = round(kpi.total_economy_cost, 0)


def _aggregate_loading(active: list[VehicleMetrics], kpi: FleetKPI,
                       fuel_price_kzt: float) -> None:
    """Свести агрегаты модуля «Работа на погрузке» по парку (P-погрузка)."""
    load_s = 0.0   # часы погрузки по датчику
    load_e = 0.0   # часы погрузки по оборотам (оценка)
    no_move = 0.0  # суммарная работа стоя (для доли полезной)
    for v in active:
        if v.loading_method == "sensor" and v.loading_hours:
            load_s += v.loading_hours
            kpi.total_loading_fuel_l += v.loading_fuel_l or 0.0
        elif v.loading_method in ("rpm", "gps", "geozone") and v.loading_hours:
            load_e += v.loading_hours
        if v.loading_method in ("sensor", "sensor_zero"):
            kpi.vehicles_with_loading_sensor += 1
        if v.unproductive_idle_hours is not None:
            kpi.total_unproductive_idle_hours += v.unproductive_idle_hours
        if v.unproductive_fuel_l is not None:
            kpi.total_unproductive_fuel_l += v.unproductive_fuel_l
        if v.work_no_move_hours:
            no_move += v.work_no_move_hours
        kpi.total_loading_points += len(v.loading_points)

    kpi.total_loading_hours_sensor = round(load_s, 2)
    kpi.total_loading_hours_estimate = round(load_e, 2)
    kpi.total_unproductive_idle_hours = round(kpi.total_unproductive_idle_hours, 2)
    kpi.total_unproductive_fuel_l = round(kpi.total_unproductive_fuel_l, 1)
    kpi.total_loading_fuel_l = round(kpi.total_loading_fuel_l, 1)
    # доля полезной работы из всей работы стоя (только там, где есть оценка погрузки)
    kpi.fleet_loading_utilization = _safe_div(load_s + load_e, no_move)
    if fuel_price_kzt and fuel_price_kzt > 0:
        kpi.total_loading_fuel_cost = round(kpi.total_loading_fuel_l * fuel_price_kzt, 0)
        kpi.total_unproductive_fuel_cost = round(
            kpi.total_unproductive_fuel_l * fuel_price_kzt, 0)
        # Потенциальная экономия — от НЕпродуктивного простоя, а не от всего idle.
        # Есть датчики надстройки (unproductive разделён) → база достоверна (measured);
        # нет → берём весь idle как верхнюю оценку и помечаем флагом.
        if kpi.total_unproductive_fuel_l > 0:
            reducible_l = kpi.total_unproductive_fuel_l
            kpi.savings_is_estimate = False
        else:
            reducible_l = kpi.fuel_idle_l
            kpi.savings_is_estimate = True
        kpi.potential_savings = round(
            reducible_l * fuel_price_kzt * config.IDLE_REDUCIBLE_SHARE, 0)


# --- Управленческие выводы ----------------------------------------------------


def build_conclusions(
    vehicles: list[VehicleMetrics], kpi: FleetKPI
) -> list[str]:
    """Сформировать 4–6 официальных выводов по парку (ТЗ §6).

    Формулировки деловые, без обвинений: повышенный расход подаётся как повод
    к проверке, а не как утверждённый перерасход (норм нет — CLAUDE.md).
    Числа форматируются по-русски через `_fmt`.
    """
    conclusions: list[str] = []

    # 1. Общая сводка по объёму работы парка.
    conclusions.append(
        f"За анализируемый период парк отработал "
        f"{_fmt(kpi.total_engine_hours, 1)} моточасов при совокупном пробеге "
        f"{_fmt(kpi.total_mileage_km)} км. Средневзвешенный расход составил "
        f"{_fmt(kpi.weighted_fuel_per_100km, 1)} л/100 км. При этом "
        f"{_fmt_pct(kpi.fuel_idle_share)}% топлива израсходовано без движения, "
        f"что указывает на необходимость дополнительного контроля простоев и "
        f"режимов работы двигателя."
    )

    # 2. Топливная эффективность и полнота данных.
    no_data = kpi.vehicles_total - kpi.vehicles_with_data
    coverage = (
        f"Показатели рассчитаны по {_fmt(kpi.vehicles_with_data)} из "
        f"{_fmt(kpi.vehicles_total)} ТС"
    )
    if no_data > 0:
        coverage += (
            f"; по {_fmt(no_data)} ТС данные за период отсутствуют и в "
            f"агрегаты не включены"
        )
    conclusions.append(
        f"{coverage}. Совокупный расход топлива по парку составил "
        f"{_fmt(kpi.total_fuel_l, 1)} л. Средневзвешенный расход "
        f"{_fmt(kpi.weighted_fuel_per_100km, 1)} л/100 км рекомендуется "
        f"сопоставить с паспортными значениями и условиями эксплуатации: при "
        f"отсутствии утверждённых норм расхода вывод о перерасходе не делается."
    )

    # 3. Расход топлива без движения — с явной долей.
    conclusions.append(
        f"Без движения израсходовано {_fmt(kpi.fuel_idle_l, 1)} л топлива — "
        f"{_fmt_pct(kpi.fuel_idle_share)}% от общего расхода. Этот объём "
        f"связан с работой двигателя на холостом ходу и прогревами; его "
        f"снижение — наиболее быстрый резерв экономии без влияния на "
        f"транспортную работу."
    )

    # 3a. Использование парка: доля холостого хода в моточасах.
    if kpi.total_engine_hours > 0:
        conclusions.append(
            f"Из {_fmt(kpi.total_engine_hours, 1)} моточасов "
            f"{_fmt(kpi.movement_hours, 1)} ч пришлось на движение и "
            f"{_fmt(kpi.total_idle_hours, 1)} ч — на холостой ход "
            f"({_fmt_pct(kpi.idle_hours_share)}% моточасов). Целевой ориентир "
            f"доли холостого хода — не более {_fmt_pct(config.IDLE_TARGET_SHARE, 0)}%."
        )

    # 3b. Денежная оценка (₸) — только при заданной цене топлива.
    if kpi.total_fuel_cost > 0:
        conclusions.append(
            f"В денежном выражении (по цене {_fmt(kpi.fuel_price_kzt)} {config.CURRENCY}/л) "
            f"топливо за период обошлось в {_fmt_money(kpi.total_fuel_cost)}, из них "
            f"{_fmt_money(kpi.idle_fuel_cost)} — на работу без движения. "
            f"Реалистично достижимая экономия на простоях — до "
            f"{_fmt_money(kpi.potential_savings)} за период."
        )

    # 4. Скоростной режим / отклонения.
    if kpi.speeding_mileage_share > 0:
        conclusions.append(
            f"Доля пробега с превышением скорости составила "
            f"{_fmt_pct(kpi.speeding_mileage_share)}% при максимальной "
            f"зафиксированной скорости {_fmt(kpi.max_speed_kmh)} км/ч. "
            f"Рекомендуется проверить маршруты и провести инструктаж по "
            f"соблюдению скоростного режима."
        )
    elif kpi.max_speed_kmh > 0:
        conclusions.append(
            f"Максимальная зафиксированная скорость по парку — "
            f"{_fmt(kpi.max_speed_kmh)} км/ч. Систематических превышений по "
            f"пробегу не выявлено; контроль скоростного режима рекомендуется "
            f"поддерживать на текущем уровне."
        )

    # 5. Зоны внимания — ТС с максимальным расходом и числом отклонений.
    attention_parts: list[str] = []
    if kpi.top_fuel_vehicle:
        attention_parts.append(
            f"наибольший расход топлива приходится на ТС «{kpi.top_fuel_vehicle}»"
        )
    if kpi.top_anomalies_vehicle:
        attention_parts.append(
            f"наибольшее число значений, требующих проверки, отмечено по ТС "
            f"«{kpi.top_anomalies_vehicle}»"
        )
    if attention_parts:
        conclusions.append(
            "В зоне приоритетного внимания: "
            + "; ".join(attention_parts)
            + ". По этим ТС рекомендуется адресная проверка режима эксплуатации "
            "и корректности данных телематики."
        )

    return conclusions


# --- Рейтинги ТС (нормированные, P0) -----------------------------------------


def rank_fuel_contribution(report_vehicles: list[VehicleMetrics], top_n: int = 5
                           ) -> list[tuple[str, float, float]]:
    """Топ ТС по вкладу в общий расход: (имя, литры, доля_парка 0..1)."""
    active = [v for v in report_vehicles if v.has_data and v.fuel_l]
    total = sum(v.fuel_l for v in active) or 0.0
    ranked = sorted(active, key=lambda v: v.fuel_l or 0.0, reverse=True)[:top_n]
    return [(v.name, v.fuel_l, _safe_div(v.fuel_l, total)) for v in ranked]


def rank_idle(report_vehicles: list[VehicleMetrics], top_n: int = 5
              ) -> list[tuple[str, float, float]]:
    """Топ ТС по доле холостого хода: (имя, доля 0..1, часы простоя).

    ТС с символической наработкой (< MIN_HOURS_FOR_IDLE_RANK) отсеиваются:
    0.4 мч с долей «93%» — это шум данных, а не лидер простоя.
    """
    cand = [
        (v.name, v.idle_hours_share, v.engine_idle_hours)
        for v in report_vehicles
        if v.has_data and v.idle_hours_share is not None
        and (v.engine_hours or 0) >= config.MIN_HOURS_FOR_IDLE_RANK
    ]
    return sorted(cand, key=lambda x: x[1], reverse=True)[:top_n]


def rank_loading_utilization(report_vehicles: list[VehicleMetrics], top_n: int = 10
                             ) -> list[tuple[str, float, float, str]]:
    """ТС по КПИ погрузки: (имя, доля_полезной 0..1, часы_погрузки, метод)."""
    cand = []
    for v in report_vehicles:
        u = v.loading_utilization
        if v.has_data and u is not None and v.loading_method in (
                "sensor", "rpm", "gps", "geozone"):
            cand.append((v.name, u, v.loading_hours or 0.0, v.loading_method))
    return sorted(cand, key=lambda x: x[1], reverse=True)[:top_n]


def rank_speeding_per_1000km(report_vehicles: list[VehicleMetrics], top_n: int = 5
                             ) -> list[tuple[str, float]]:
    """Топ ТС по превышениям на 1000 км (нормировано на пробег)."""
    cand = []
    for v in report_vehicles:
        if v.has_data and v.speeding_count and v.mileage_km and v.mileage_km > 0:
            cand.append((v.name, v.speeding_count / v.mileage_km * 1000))
    return sorted(cand, key=lambda x: x[1], reverse=True)[:top_n]


# --- Динамический план действий (P0) -----------------------------------------


def build_recommendations(vehicles: list[VehicleMetrics], kpi: FleetKPI) -> list[str]:
    """Сформировать план действий, привязанный к фактическим цифрам парка.

    В отличие от статичного списка — каждый пункт появляется только если данные
    его подтверждают (высокий простой, конкретные ТС-лидеры, деньги и т.п.).
    """
    recs: list[str] = []

    # 1. Простой: если доля холостого хода выше целевой — приоритетная мера.
    if kpi.idle_hours_share > config.IDLE_TARGET_SHARE:
        msg = (
            f"Сократить холостой ход: {_fmt_pct(kpi.idle_hours_share)}% моточасов "
            f"приходится на работу двигателя без движения "
            f"(цель ≤ {_fmt_pct(config.IDLE_TARGET_SHARE, 0)}%)"
        )
        if kpi.potential_savings > 0:
            msg += (
                f". Потенциальная экономия — до {_fmt_money(kpi.potential_savings)} "
                f"за период при сокращении простоя на "
                f"{_fmt_pct(config.IDLE_REDUCIBLE_SHARE, 0)}%"
            )
        recs.append(msg + ".")

    # 2. Адресные ТС-лидеры по простою.
    idle_top = rank_idle(vehicles, top_n=3)
    flagged = [f"«{n}» ({_fmt_pct(s)}%)" for n, s, _ in idle_top if s and s > 0.4]
    if flagged:
        recs.append(
            "Проверить режим работы ТС с наибольшим простоем: "
            + ", ".join(flagged)
            + " — возможен неоправданный простой с работающим двигателем."
        )

    # 3. Нормирование расхода — пока норм нет, без вывода о перерасходе.
    recs.append(
        "Утвердить нормы расхода по типам ТС (л/100 км для мобильных, "
        "л/моточас для спецтехники) — без них перерасход оценивать некорректно."
    )

    # 4. Качество данных — если есть ТС без данных.
    no_data = kpi.vehicles_total - kpi.vehicles_with_data
    if no_data > 0:
        recs.append(
            f"Провести ревизию {_fmt(no_data)} ТС с пометкой «нет данных»: "
            f"проверить терминалы/датчики и полноту телеметрии за период."
        )

    # 5. Скоростной режим — если фиксировались превышения.
    if kpi.speeding_mileage_share > 0:
        recs.append(
            f"Контроль скоростного режима: доля пробега с превышением "
            f"{_fmt_pct(kpi.speeding_mileage_share)}% — провести инструктаж "
            f"и проверить проблемные маршруты."
        )

    # 6. Регулярность — всегда уместно.
    recs.append(
        "Ввести регулярную отчётность по этому формату (ежемесячно) для "
        "отслеживания динамики KPI и эффекта принятых мер."
    )
    return recs


def rank_money_loss(vehicles: list[VehicleMetrics], fuel_price_kzt: float,
                    top_n: int = 5) -> list[dict]:
    """Топ ТС по денежным потерям (₸): простой + перерасход к норме.

    Возвращает [{name, loss, share}] — где деньги (парето). share — доля в
    суммарных потерях парка.
    """
    if not fuel_price_kzt or fuel_price_kzt <= 0:
        return []
    items = []
    for v in vehicles:
        if not v.has_data:
            continue
        idle_cost = (v.fuel_idle_l or 0.0) * fuel_price_kzt
        over_cost = max(0.0, v.overrun_cost_kzt or 0.0)
        loss = idle_cost + over_cost
        if loss > 0:
            items.append((v.name, loss))
    total = sum(x[1] for x in items) or 1.0
    items.sort(key=lambda x: x[1], reverse=True)
    return [{"name": n, "loss": round(c, 0), "share": c / total}
            for n, c in items[:top_n]]


def annualize(value: float, period: ReportPeriod) -> float:
    """Привести сумму за период к году (×365/дней периода)."""
    days = max(1.0, (period.end_ts - period.start_ts) / 86400)
    return round(value * 365.0 / days, 0)


def build_whatif(kpi: FleetKPI) -> list[dict]:
    """Сценарии «что если сократить простой на X%» → экономия л и ₸."""
    out = []
    for cut in config.WHATIF_IDLE_CUTS:
        saved_l = round(kpi.fuel_idle_l * cut, 1)
        saved_kzt = round(kpi.idle_fuel_cost * cut, 0) if kpi.idle_fuel_cost else 0
        out.append({"cut": cut, "saved_l": saved_l, "saved_kzt": saved_kzt})
    return out


def build_scorecard(vehicles: list[VehicleMetrics]) -> list[dict]:
    """Балл проблемности ТС (0 = идеально, выше = больше внимания).

    Складывается из штрафов: перерасход к норме, доля холостого хода, превышения.
    Сортировка — худшие сверху. Драйвер-скоринг по водителям недоступен (нет
    привязки водитель↔ТС в данных) — оцениваем по ТС.
    """
    cards = []
    for v in vehicles:
        if not v.has_data:
            continue
        score = 0.0
        reasons = []
        if v.overrun_cost_kzt and v.overrun_cost_kzt > 0:
            pts = min(40.0, v.overrun_cost_kzt / config.ALERT_OVERRUN_COST_KZT * 40)
            score += pts
            reasons.append(f"перерасход {v.overrun_cost_kzt:,.0f} ₸".replace(",", " "))
        if v.idle_hours_share:
            score += min(40.0, v.idle_hours_share * 40)
            reasons.append(f"холостой {v.idle_hours_share * 100:.0f}%")
        if v.speeding_count:
            score += min(20.0, v.speeding_count / 50 * 20)
            reasons.append(f"превышений {v.speeding_count}")
        cards.append({"name": v.name, "score": round(score, 1),
                      "reasons": "; ".join(reasons) or "в норме"})
    cards.sort(key=lambda c: c["score"], reverse=True)
    return cards


def compute_trends(current: FleetKPI, previous: FleetKPI | None) -> dict:
    """Относительные дельты ключевых метрик период-к-периоду, % (P2)."""
    if previous is None:
        return {}
    metrics = (
        "total_mileage_km", "total_fuel_l", "weighted_fuel_per_100km",
        "total_engine_hours", "idle_hours_share", "total_fuel_cost",
    )
    trends: dict[str, float] = {}
    for m in metrics:
        prev = getattr(previous, m, 0.0) or 0.0
        cur = getattr(current, m, 0.0) or 0.0
        if prev:
            trends[m] = round((cur - prev) / prev * 100, 1)
    return trends


# --- Сборка отчёта ------------------------------------------------------------


def analyze(
    vehicles: list[VehicleMetrics],
    period: ReportPeriod,
    client_name: str,
    source: str = "excel",
    fuel_price_kzt: float = 0.0,
    previous_kpi: FleetKPI | None = None,
    norms: dict | None = None,
    season: str = "summer",
    time_fund_hours_per_day: float = 0.0,
    haul_volume_m3: float = 0.0,
) -> FleetReport:
    """Собрать полный `FleetReport`: KPI + выводы + рекомендации (ТЗ §5, §6).

    `generated_at` намеренно оставляем None — его проставит CLI в момент
    фактической генерации, чтобы аналитика не зависела от системных часов.

    :param fuel_price_kzt: цена топлива ₸/л для денежной оценки (0 — без денег).
    :param previous_kpi:   KPI прошлого прогона для трендов (None — без трендов).
    :param norms:          нормы расхода по ТС {имя: {engine,l_100km,l_mh}} →
                           перерасход/экономия (None — без вывода о перерасходе).
    """
    # Паспорт+нормы → перерасход/экономия (до KPI). Зимой норма выше на
    # config.NORM_COEFFICIENTS['winter'] → это меняет сумму перерасхода в ₸.
    if norms:
        extra = config.NORM_COEFFICIENTS["winter"] if season == "winter" else 1.0
        norms_mod.apply_and_compute(vehicles, norms, fuel_price_kzt, extra_coeff=extra)
    vehicle_types.apply_types(vehicles)
    _sanitize_speed_by_type(vehicles)   # класс-зависимый отсев GPS-глюков
    kpi = compute_kpi(vehicles, fuel_price_kzt=fuel_price_kzt)
    # Коэффициент использования (ТЗ C1): моточасы к доступному времени.
    # Календарный — всегда; эксплуатационный — при заданном фонде клиента
    # (8 ч/сут, 24/7 и т.п.). Значение >1 = работа сверх фонда (вторая смена).
    days = max(1.0, (period.end_ts - period.start_ts) / 86400.0)
    if kpi.vehicles_with_data and kpi.total_engine_hours > 0:
        base_vehicle_days = kpi.vehicles_with_data * days
        kpi.utilization_calendar = round(
            kpi.total_engine_hours / (base_vehicle_days * 24.0), 4)
        if time_fund_hours_per_day > 0:
            kpi.time_fund_hours_per_day = time_fund_hours_per_day
            kpi.utilization_fund = round(
                kpi.total_engine_hours
                / (base_vehicle_days * time_fund_hours_per_day), 4)
    # Себестоимость вывоза (ТКО): топливная составляющая на 1 м³ по данным
    # полигона. Только топливо — не полная себестоимость (без ФОТ/амортизации).
    if haul_volume_m3 > 0 and kpi.total_fuel_cost > 0:
        kpi.haul_volume_m3 = haul_volume_m3
        kpi.fuel_cost_per_m3 = round(kpi.total_fuel_cost / haul_volume_m3, 1)
    conclusions = build_conclusions(vehicles, kpi)
    if kpi.fuel_cost_per_m3 > 0:
        conclusions.append(
            f"Топливная себестоимость вывоза: {kpi.fuel_cost_per_m3:,.0f} ₸/м³ "
            f"({kpi.haul_volume_m3:,.0f} м³ за период; только топливо, без "
            "ФОТ и амортизации).".replace(",", " ")
        )
    if kpi.utilization_fund > 0:
        conclusions.append(
            f"Коэффициент использования парка: {kpi.utilization_fund * 100:.0f}% "
            f"нормативного фонда ({kpi.time_fund_hours_per_day:g} ч/сутки на ТС)"
            + (" — работа сверх фонда." if kpi.utilization_fund > 1 else ".")
        )
    elif kpi.utilization_calendar > 0:
        conclusions.append(
            f"Техническое использование парка: {kpi.utilization_calendar * 100:.0f}% "
            "календарного времени (фонд смены клиентом не задан)."
        )
    recommendations = build_recommendations(vehicles, kpi)
    trends = compute_trends(kpi, previous_kpi)
    report = FleetReport(
        period=period,
        client_name=client_name,
        vehicles=vehicles,
        kpi=kpi,
        conclusions=conclusions,
        recommendations=recommendations,
        source=source,
        season=season,
        generated_at=None,
        previous_kpi=previous_kpi,
        trends=trends,
    )
    report.whatif = build_whatif(kpi)
    report.scorecard = build_scorecard(vehicles)
    from omnicomm_report import alerts as alerts_mod, benchmark as bench_mod
    report.alerts = alerts_mod.build_alerts(report)
    try:
        report.benchmark = bench_mod.compute(client_name, kpi)
    except Exception:  # noqa: BLE001 — бенчмарк не критичен
        report.benchmark = {}
    return report
