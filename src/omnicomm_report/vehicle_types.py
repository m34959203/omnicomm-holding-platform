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
    # --- Типы парка геологоразведки КАП (специфика агрегата) ---
    "drill_rig": TypeProfile("drill_rig", "Буровая установка (ЗИФ)", "l_per_mh", True,
        "Стационарное разведочное бурение: расход в л/моточас, пробег ≈0 не показываем; "
        "контроль ТО по наработке, сходимость топливного баланса в поле."),
    "drill_rig_mobile": TypeProfile("drill_rig_mobile", "УРБ (буровая на шасси)", "both", True,
        "И едет, и бурит: раздельный расход л/100 км (перегон) и л/моточас (бурение); "
        "превышения на техдороге = износ; ТО = min(моточасы, пробег)."),
    "compressor": TypeProfile("compressor", "Компрессор дизельный", "l_per_mh", True,
        "Передвижной дизельный компрессор для бурения: л/моточас; НИКОГДА не л/100 км. "
        "КПД корректно мерить по датчику давления магистрали (≥10 бар = полезная работа), "
        "обороты — лишь косвенно; ТО по наработке."),
    "compressor_electric": TypeProfile("compressor_electric", "Компрессор электрический", "none", True,
        "Электрический компрессор: ГСМ НЕ потребляет — исключён из всей топливной "
        "аналитики (ни л/100 км, ни л/моточас); мониторится наработка/онлайн."),
    "des": TypeProfile("des", "Дизель-электростанция (ДЭС)", "l_per_mh", True,
        "Обороты двигателя постоянны (50 Гц) — метрика «холостой ход по оборотам» "
        "неприменима; расход мерить в л/моточас (к выработке кВт·ч при данных); "
        "НИКОГДА не л/100 км."),
    "logging_station": TypeProfile("logging_station", "Каротажная станция", "both", True,
        "Геофизика в скважине: работа спецоборудования на точке + переезды; "
        "стабильность напряжения критична для аппаратуры."),
    "agp": TypeProfile("agp", "Автогидроподъёмник (АГП)", "both", True,
        "Люлька/стрела на месте + переезды: моточасы работы стрелы и КПД, "
        "ТО гидросистемы по наработке."),
    "tanker": TypeProfile("tanker", "Топливозаправщик (АТЗ)", "both", False,
        "Выдача ГСМ (ADR): центральный параметр — баланс выдачи и остаток "
        "в цистерне; расход шасси НЕ смешивать с перекачанным; строгий скор. режим."),
    "semi_truck": TypeProfile("semi_truck", "Седельный тягач", "l_per_100km", False,
        "Магистраль с полуприцепом: л/100 км, контроль сцепки, лимит грузовые>3,5 т с прицепом."),
    "offroad_special": TypeProfile("offroad_special", "Спецтехника вездеход (КрАЗ/Урал)", "both", True,
        "Тяжёлое шасси по пересечёнке: флагман — превышения на техдороге → "
        "ускоренный износ ₸ (не штраф); усиленный контроль шин и ТО."),
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
# ПОРЯДОК ВАЖЕН: специфичные хинты ВЫШЕ общих марок — «УРБ на шасси МАЗ» и
# «Каротажная станция Урал» обязаны матчиться до общих «маз»/«урал».
_NAME_HINTS: list[tuple[str, str]] = [
    # УРБ и каротаж — до общих марок шасси
    ("урб", "drill_rig_mobile"), ("бкм", "drill_rig_mobile"),
    ("каротаж", "logging_station"), ("геофиз", "logging_station"), ("пкс", "logging_station"),
    # буровые стационарные
    ("зиф", "drill_rig"), ("буровая", "drill_rig"), ("буров", "drill_rig"),
    ("сбш", "drill_rig"), ("dml", "drill_rig"),
    # ДЭС / электростанции (постоянные обороты — своя категория)
    ("дэс", "des"), ("электростанц", "des"), ("aksa", "des"), ("jetpower", "des"),
    ("jet-200", "des"), ("дизель-генератор", "des"), ("дизельн станц", "des"),
    # компрессоры: ЭЛЕКТРИЧЕСКИЕ — ДО общего «компресс» (в именах КАП «Компрессор (эл. …)»)
    ("компрессор (эл", "compressor_electric"), ("компрессор(эл", "compressor_electric"),
    ("эл. компресс", "compressor_electric"), ("эл.компресс", "compressor_electric"),
    ("atlas copco", "compressor"), ("атлас копко", "compressor"), ("компресс", "compressor"),
    ("xrvs", "compressor"), ("xaxs", "compressor"), ("xas", "compressor"), ("v900", "compressor"),
    # АГП / автовышка
    ("агп", "agp"), ("автогидропод", "agp"), ("автовышк", "agp"), ("автовышка", "agp"),
    # заправщики / ADR
    ("атз", "tanker"), ("заправщик", "tanker"), ("топливозап", "tanker"),
    ("бензовоз", "tanker"), ("мтоп", "tanker"),
    # мусоровозы/КДМ
    ("мусоров", "refuse_truck"), ("ко-", "refuse_truck"), ("ко 4", "refuse_truck"),
    ("garbage", "refuse_truck"), ("тко", "refuse_truck"), ("бункер", "refuse_truck"),
    ("подмета", "vacuum_sweeper"), ("поливомо", "vacuum_sweeper"),
    ("вакуум", "vacuum_sweeper"), ("кдм", "vacuum_sweeper"),
    # экскаваторы/краны/погрузчики/тракторы
    ("экскаватор", "excavator"), ("komatsu", "excavator"), ("hitachi", "excavator"),
    ("экг", "excavator"), ("pc ", "excavator"),
    ("автокран", "crane"), ("кран", "crane"), ("kato", "crane"),
    ("погрузчик", "loader"), ("develon", "loader"), ("sd300", "loader"), ("doosan", "loader"),
    ("liu gong", "loader"), ("liugong", "loader"), ("xcmg", "loader"), ("zl", "loader"), ("lw", "loader"),
    ("трактор", "tractor"), ("мтз", "tractor"), ("беларус", "tractor"),
    # самосвалы (марки карьерных)
    ("самосвал", "dump_truck"), ("shacman", "dump_truck"), ("shaanxi", "dump_truck"),
    ("volvo fmx", "dump_truck"), ("iveco astra", "dump_truck"), ("howo", "dump_truck"),
    # седельные тягачи
    ("тягач", "semi_truck"), ("седельн", "semi_truck"), ("полуприц", "semi_truck"),
    # спецтехника-вездеход по пересечёнке (общие марки — НИЖЕ специфичных выше)
    ("краз", "offroad_special"), ("урал", "offroad_special"), ("вездеход", "offroad_special"),
    # землеройная спецтехника по марке (до общих грузовых марок)
    ("hidromek", "excavator"), ("jcb", "excavator"), ("hyundai r", "excavator"),
    ("бульдозер", "loader"), ("shantui", "loader"), ("wheel loader", "loader"),
    ("б10", "loader"), ("т-170", "loader"), ("т-130", "loader"),
    ("грейдер", "loader"), ("автогрейдер", "loader"),
    # автобусы по марке
    ("автобус", "bus"), ("паз", "bus"), ("вахтов", "bus"), ("ankai", "bus"),
    ("yutong", "bus"), ("higer", "bus"), ("kavz", "bus"), ("маз-103", "bus"),
    # грузовые/самосвалы по марке (общие марки — НИЖЕ специфичных моделей выше)
    ("камаз", "truck"), ("зил", "truck"), ("маз", "truck"), ("газель", "truck"),
    ("газон", "truck"), ("бортов", "truck"), ("dongfeng", "truck"), ("foton", "truck"),
    ("faw", "truck"), ("unimog", "truck"), ("hyundai hd", "truck"), ("isuzu", "truck"),
    ("hino", "truck"), ("volvo", "truck"),
    # заправщики/бензовозы (доп. марочные — ADR)
    ("топливоз", "tanker"), ("автоцистерн", "tanker"),
    # легковые/внедорожники/пикапы по марке
    ("prado", "car"), ("прадо", "car"), ("land cruiser", "car"), ("hilux", "car"),
    ("l200", "car"), ("уаз", "car"), ("нива", "car"), ("niva", "car"),
    ("toyota", "car"), ("mitsubishi", "car"), ("nissan", "car"), ("hyundai", "car"),
    ("hyunday", "car"), ("kia", "car"), ("changan", "car"), ("ssangyong", "car"),
    ("chevrolet", "car"), ("lada", "car"), ("ваз", "car"), ("skoda", "car"),
    ("jac", "car"), ("staria", "car"), ("пикап", "car"), ("pickup", "car"),
    ("легков", "car"), ("внедорож", "car"),
]


def classify_from_name(name: Optional[str]) -> str:
    """Тип по одному имени ТС (без полного VehicleMetrics) — по `_NAME_HINTS`.

    Нет совпадения → "other". Для карточки достаточно имени; кинематический
    фолбэк остаётся в `classify_auto` (когда есть метрики)."""
    n = (name or "").lower()
    for hint, key in _NAME_HINTS:
        if hint in n:
            return key
    return "other"


def profile(key: Optional[str]) -> TypeProfile:
    """Профиль по ключу типа (None/неизвестный → DEFAULT). Учитывает JSON-шаблоны."""
    return all_profiles().get(key or "", DEFAULT)


def label(key: Optional[str]) -> str:
    return profile(key).label


def classify_auto(vm: VehicleMetrics) -> str:
    """Авто-классификация типа по названию и кинематике (когда нет паспорта)."""
    by_name = classify_from_name(vm.name)
    if by_name != "other":
        return by_name

    # По кинематике: соотношение пробег/моточас и макс. скорость.
    eng = vm.engine_hours or 0.0
    km = vm.mileage_km or 0.0
    km_per_h = km / eng if eng > 0 else None
    max_speed = vm.max_speed_kmh or 0.0
    if eng > 0 and km < 1 and max_speed < 10:
        return "drill_rig"        # стоит на месте, работает двигателем — буровая/компрессор
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
