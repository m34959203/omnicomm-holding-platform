"""Классификация типов техники и профили анализа под специфику работы.

У разной техники разный «основной параметр» расхода:
  • мусоровоз/экскаватор/кран/погрузчик — работа на месте → главное л/моточас;
  • самосвал/бортовой/автобус/легковой — пробег → главное л/100 км;
  • поливомоечная/подметальная — и пробег, и работа спецоборудования.

Тип берётся из паспорта (если задан), иначе авто-классифицируется по названию
и кинематике (скорость, пробег на моточас). Профиль определяет, какую метрику
подсвечивать и ждать ли продуктивной работы на стоянке.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Optional

from .models import VehicleMetrics


@dataclass(frozen=True)
class TypeProfile:
    key: str
    label: str                 # русское название для отчёта
    primary_metric: str        # 'l_per_mh' | 'l_per_100km' | 'both'
    stationary_work: bool      # ждём ли продуктивную работу на стоянке (гидравлика)
    note: str                  # как трактовать в отчёте


# Реестр типов техники по умолчанию (ключ → профиль анализа). Это «заводские»
# шаблоны-сиды; их можно переопределять/дополнять из интерфейса — см.
# `data/vehicle_types.json` (load_profiles/save_profiles).
DEFAULT_PROFILES: dict[str, TypeProfile] = {
    "refuse_truck": TypeProfile("refuse_truck", "Мусоровоз", "both", True,
        "Основная работа — погрузка контейнеров на месте: ключевой параметр "
        "л/моточас, плюс л/100 км на переездах между площадками."),
    "vacuum_sweeper": TypeProfile("vacuum_sweeper", "Поливомоечная/подметальная", "both", True,
        "Работа спецоборудования в движении и на месте: учитываем и л/100 км, и л/моточас."),
    "excavator": TypeProfile("excavator", "Экскаватор", "l_per_mh", True,
        "Почти не передвигается: расход корректно мерить в л/моточас, не в л/100 км."),
    "crane": TypeProfile("crane", "Автокран", "l_per_mh", True,
        "Работа крановой установки на месте: основной параметр — л/моточас."),
    "loader": TypeProfile("loader", "Погрузчик", "l_per_mh", True,
        "Циклы погрузки на месте: основной параметр — л/моточас."),
    "tractor": TypeProfile("tractor", "Трактор", "l_per_mh", True,
        "Навесное оборудование: основной параметр — л/моточас."),
    "dump_truck": TypeProfile("dump_truck", "Самосвал", "l_per_100km", False,
        "Перевозки: основной параметр — л/100 км; стоянка с двигателем — потери."),
    "truck": TypeProfile("truck", "Грузовой/бортовой", "l_per_100km", False,
        "Магистральные/городские перевозки: основной параметр — л/100 км."),
    "bus": TypeProfile("bus", "Автобус", "l_per_100km", False,
        "Пассажирские перевозки: основной параметр — л/100 км."),
    "car": TypeProfile("car", "Легковой", "l_per_100km", False,
        "Основной параметр — л/100 км."),
    "other": TypeProfile("other", "Прочее", "both", False,
        "Тип не определён — показываем и л/100 км, и л/моточас."),
}

DEFAULT = DEFAULT_PROFILES["other"]
TEMPLATES_PATH = os.path.join("data", "vehicle_types.json")


def all_profiles() -> dict[str, TypeProfile]:
    """Действующие шаблоны: дефолты, переопределённые/дополненные из JSON."""
    profiles = dict(DEFAULT_PROFILES)
    if os.path.exists(TEMPLATES_PATH):
        try:
            with open(TEMPLATES_PATH, encoding="utf-8") as fh:
                data = json.load(fh)
            for key, d in (data or {}).items():
                profiles[key] = TypeProfile(
                    key, d.get("label", key),
                    d.get("primary_metric", "both"),
                    bool(d.get("stationary_work", False)),
                    d.get("note", ""))
        except (OSError, ValueError):
            pass
    return profiles


def save_profiles(profiles: dict[str, dict], path: str = TEMPLATES_PATH) -> str:
    """Сохранить пользовательские шаблоны (ключ → {label,primary_metric,...})."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    clean = {}
    for key, d in profiles.items():
        k = (key or "").strip()
        if not k:
            continue
        clean[k] = {
            "label": d.get("label", k),
            "primary_metric": d.get("primary_metric", "both"),
            "stationary_work": bool(d.get("stationary_work", False)),
            "note": d.get("note", ""),
        }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(clean, fh, ensure_ascii=False, indent=1)
    return path


# Ключевые слова в названии/марке → тип (нижний регистр, подстрока).
_NAME_HINTS: list[tuple[str, str]] = [
    ("мусоров", "refuse_truck"), ("ко-", "refuse_truck"), ("ко 4", "refuse_truck"),
    ("garbage", "refuse_truck"), ("тко", "refuse_truck"), ("бункер", "refuse_truck"),
    ("подмета", "vacuum_sweeper"), ("поливомо", "vacuum_sweeper"),
    ("вакуум", "vacuum_sweeper"), ("кдм", "vacuum_sweeper"),
    ("экскаватор", "excavator"), ("komatsu", "excavator"), ("hitachi", "excavator"),
    ("экг", "excavator"), ("pc ", "excavator"),
    ("кран", "crane"), ("kato", "crane"), ("автокран", "crane"),
    ("погрузчик", "loader"), ("liu gong", "loader"), ("liugong", "loader"),
    ("xcmg", "loader"), ("zl", "loader"), ("lw", "loader"),
    ("трактор", "tractor"), ("мтз", "tractor"), ("беларус", "tractor"),
    ("самосвал", "dump_truck"),
    ("автобус", "bus"), ("паз", "bus"), ("газель", "truck"),
]


def profile(key: Optional[str]) -> TypeProfile:
    """Профиль по ключу типа (None/неизвестный → DEFAULT). Учитывает JSON-шаблоны."""
    return all_profiles().get(key or "", DEFAULT)


def label(key: Optional[str]) -> str:
    return profile(key).label


def classify_auto(vm: VehicleMetrics) -> str:
    """Авто-классификация типа по названию и кинематике (когда нет паспорта)."""
    name = (vm.name or "").lower()
    for hint, key in _NAME_HINTS:
        if hint in name:
            return key

    # По кинематике: соотношение пробег/моточас и макс. скорость.
    eng = vm.engine_hours or 0.0
    km_per_h = (vm.mileage_km or 0.0) / eng if eng > 0 else None
    max_speed = vm.max_speed_kmh or 0.0
    if max_speed and max_speed < 20:
        return "excavator"        # почти не ездит
    if km_per_h is not None and km_per_h < 3 and eng > 0:
        return "loader"           # много моточасов, мало пробега
    if max_speed > 70:
        return "truck"            # магистральный профиль
    return "other"


def apply_types(vehicles: list[VehicleMetrics]) -> None:
    """Проставить vehicle_type там, где он ещё не задан (из паспорта)."""
    for vm in vehicles:
        if not vm.vehicle_type:
            vm.vehicle_type = classify_auto(vm)
