"""Синтетические демо-данные холдинга для показа портала без доступа к API.

ВАЖНО: это ВЫМЫШЛЕННЫЕ данные (структура в стиле КАП, но цифры сгенерированы) —
не настоящая телеметрия Казатомпрома. Назначение — демонстрация работы ДЗО и
самой системы, пока боевая учётка Omnicomm не подключена.

Детерминированность: метрики ТС зависят только от стабильного seed (md5 по
vehicle_id) и числа дней периода → один и тот же период всегда даёт те же цифры.
Классы ТС задаются распределением (стационарная техника = мало пробега на
моточас, см. `VehicleMetrics.is_stationary`: km/engine_hours < 5).
"""
from __future__ import annotations

import hashlib
import random
from datetime import datetime

from .models import ReportPeriod, VehicleMetrics
from .org import Org, OrgLevel, OrgRegistry, OrgTree, OrgType

# Цена топлива для пересчёта перерасхода в ₸ (демо; рендер использует свою для
# остальных денег). Близко к ДТ лето в КЗ.
_DEMO_FUEL_PRICE = 330.0

# --- Структура холдинга (org_id, name, parent_id, level, type) ------------------
_ORGS: list[tuple[str, str, str | None, OrgLevel, OrgType]] = [
    ("holding", "АО НАК «Казатомпром» (ДЕМО)", None, OrgLevel.HOLDING, OrgType.OWN),
    ("volkov", "Волковгеология", "holding", OrgLevel.DZO, OrgType.OWN),
    ("appak", "АППАК", "holding", OrgLevel.DZO, OrgType.OWN),
    ("uranenergo", "Уранэнерго", "holding", OrgLevel.DZO, OrgType.OWN),
    ("tfo", "ТФО", "uranenergo", OrgLevel.SUB_DZO, OrgType.OWN),
    ("shfo", "ШФО", "uranenergo", OrgLevel.SUB_DZO, OrgType.OWN),
    ("umz", "УМЗ", "holding", OrgLevel.DZO, OrgType.OWN),
    ("umz_kurchatov", "УМЗ Курчатов", "umz", OrgLevel.SUB_DZO, OrgType.OWN),
    ("burservice", "Подрядчик «БурСервис»", "volkov", OrgLevel.CONTRACTOR,
     OrgType.CONTRACTOR),
]

# Парк только у листовых узлов; родительские агрегируют по поддереву (роллап).
# org_id -> (транспорт мобильный, стационарная спецтехника, «тёмные» без данных)
_FLEET_PLAN: dict[str, tuple[int, int, int]] = {
    "volkov": (6, 8, 1),          # геологоразведка — много буровых
    "appak": (10, 4, 1),          # добыча — транспорт + погрузчики
    "tfo": (5, 3, 0),
    "shfo": (4, 2, 1),
    "umz_kurchatov": (7, 3, 0),
    "burservice": (3, 4, 0),      # подрядчик внутри Волковгеологии
}

_TRANSPORT_NAMES = [
    "Самосвал КАМАЗ-6520", "Самосвал HOWO ZZ3257", "Вахтовка Урал-4320",
    "Бортовой КАМАЗ-43118", "Топливозаправщик КАМАЗ", "Автобус ПАЗ-32053",
    "Самосвал МАЗ-6501", "Вахтовка КАМАЗ-43118",
]
_STATIONARY_NAMES = [
    "Буровая УРБ-2А2", "Буровая ЗИФ-650М", "Погрузчик KOMATSU WA380",
    "Экскаватор HITACHI ZX330", "Автокран Liebherr LTM", "Бульдозер SHANTUI SD22",
    "Погрузчик XCMG LW300", "Буровая установка УБШ-532",
]


def _rng(vehicle_id: str) -> random.Random:
    """Стабильный PRNG по vehicle_id (md5 — без зависимости от PYTHONHASHSEED)."""
    seed = int(hashlib.md5(vehicle_id.encode("utf-8")).hexdigest()[:8], 16)
    return random.Random(seed)


def _iter_specs():
    """Источник истины: (vehicle_id, name, org_id, kind) для всего демо-парка.

    Используется и реестром (vehicle_org), и генератором метрик — id совпадают.
    kind ∈ {"transport", "stationary", "dark"}.
    """
    for org_id, (n_tr, n_st, n_dk) in _FLEET_PLAN.items():
        idx = 0
        for i in range(n_tr):
            nm = _TRANSPORT_NAMES[i % len(_TRANSPORT_NAMES)]
            yield (f"{org_id}-{idx:02d}", f"{nm} · {org_id.upper()}", org_id, "transport")
            idx += 1
        for i in range(n_st):
            nm = _STATIONARY_NAMES[i % len(_STATIONARY_NAMES)]
            yield (f"{org_id}-{idx:02d}", f"{nm} · {org_id.upper()}", org_id, "stationary")
            idx += 1
        for i in range(n_dk):
            yield (f"{org_id}-{idx:02d}", f"ТС без связи · {org_id.upper()}", org_id, "dark")
            idx += 1


def _period_days(period: ReportPeriod) -> int:
    days = (period.end - period.start).days + 1
    return max(1, days)


def build_demo_registry() -> OrgRegistry:
    """Синтетический реестр холдинга КАП (дерево + привязка ТС к узлам)."""
    orgs = [Org(org_id=oid, name=nm, parent_id=par, level=lvl, type=tp)
            for (oid, nm, par, lvl, tp) in _ORGS]
    tree = OrgTree(orgs)
    vehicle_org = {vid: org_id for (vid, _nm, org_id, _kind) in _iter_specs()}
    return OrgRegistry(tree=tree, vehicle_org=vehicle_org)


def demo_fleet(period: ReportPeriod) -> list[VehicleMetrics]:
    """Сгенерировать парк `VehicleMetrics` за период (детерминированно)."""
    days = _period_days(period)
    out: list[VehicleMetrics] = []
    for vid, name, org_id, kind in _iter_specs():
        out.append(_make_vehicle(vid, name, org_id, kind, days))
    return out


def _make_vehicle(vid: str, name: str, org_id: str, kind: str,
                  days: int) -> VehicleMetrics:
    r = _rng(vid)
    if kind == "dark":
        return VehicleMetrics(
            vehicle_id=vid, name=name, org_id=org_id,
            has_data=False, no_data_reason="нет связи с терминалом")

    # Выбросы (детерминированно по seed): «прожорливый» ТС с крупным перерасходом
    # и часть мобильных с высоким простоем — чтобы лента сигналов была живой.
    thirsty = r.random() < 0.10
    high_idle = r.random() < 0.18

    if kind == "transport":
        engine_hours = r.uniform(6.0, 11.0) * days
        mileage_km = r.uniform(90.0, 240.0) * days          # км/моточас >> 5 → мобильный
        per_100 = r.uniform(0.28, 0.42) * (r.uniform(1.8, 2.4) if thirsty else 1.0)
        fuel_l = mileage_km * per_100                        # ~28–42 (прожорл. выше) л/100км
        max_speed = r.uniform(62.0, 96.0)
        speeding_km = mileage_km * r.uniform(0.0, 0.12)
        speeding_count = int(speeding_km / max(1.0, r.uniform(8, 20)))
        # высокий холостой ход — признак мобильных (у спецтехники простой = норма)
        idle_share = r.uniform(0.52, 0.68) if high_idle else r.uniform(0.22, 0.42)
    else:  # stationary — буровые/погрузчики: моточасы есть, пробега почти нет
        engine_hours = r.uniform(5.0, 10.0) * days
        mileage_km = r.uniform(0.0, 12.0) * days             # км/моточас < 5 → стационар
        fuel_l = engine_hours * r.uniform(6.0, 12.0) * (r.uniform(1.6, 2.2) if thirsty else 1.0)
        max_speed = r.uniform(0.0, 8.0)
        speeding_km = 0.0
        speeding_count = 0
        idle_share = r.uniform(0.25, 0.45)

    engine_idle_hours = engine_hours * idle_share
    fuel_idle_l = fuel_l * r.uniform(0.20, 0.40)

    # Перерасход к норме: прожорливые → крупный перерасход; остальные — небольшой
    # разброс ± (часть ТС в экономии, отрицательный overrun).
    overrun_l = fuel_l * (r.uniform(0.28, 0.45) if thirsty else r.uniform(-0.08, 0.14))
    overrun_cost_kzt = overrun_l * _DEMO_FUEL_PRICE

    return VehicleMetrics(
        vehicle_id=vid, name=name, org_id=org_id,
        mileage_km=round(mileage_km, 1),
        fuel_l=round(fuel_l, 1),
        engine_hours=round(engine_hours, 1),
        engine_idle_hours=round(engine_idle_hours, 1),
        fuel_idle_l=round(fuel_idle_l, 1),
        max_speed_kmh=round(max_speed, 1),
        speeding_count=speeding_count,
        speeding_mileage_km=round(speeding_km, 1),
        overrun_l=round(overrun_l, 1),
        overrun_cost_kzt=round(overrun_cost_kzt, 0),
        overrun_basis="mh" if kind == "stationary" else "100km",
        has_data=True,
    )


def save_demo_registry(path: str = "data/org_registry.db") -> str:
    """Записать демо-реестр в стандартный путь портала (.db→SQLite, .json→JSON)."""
    from . import org as org_mod
    return org_mod.save_org_registry(build_demo_registry(), path)
