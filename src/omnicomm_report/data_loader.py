"""Загрузка данных автопарка из обоих источников → единая модель (ТЗ §2, §16.5).

Здесь и только здесь источник (Omnicomm REST API / Excel-выгрузка) приводится
к `list[VehicleMetrics]`. Дальше по конвейеру (validator → analytics → charts →
report_builder) источник неизвестен — все работают с единым контрактом.

Почему так:
- Excel — главный режим MVP (ТЗ Режим Б): заголовки у разных клиентов называются
  по-разному (рус/англ, разный регистр, лишние пробелы) → нужно автоопределение
  столбцов по словарю синонимов, а не жёсткий порядок колонок.
- API — поля ответа уточняются по Swagger UI (ТЗ §16), поэтому маппинг вынесен в
  `FIELD_MAP` и устойчив к отсутствию любого поля (→ None).
- Бизнес-инвариант (CLAUDE.md): столбец «возможные сливы топлива» НЕ маппится и
  не попадает дальше — в отчёте его быть не должно.
"""

from __future__ import annotations

import re
from typing import Any, Optional

import pandas as pd

from omnicomm_report import config, loading
from omnicomm_report.config import (
    DECILITRES_TO_LITRES,
    MAX_PLAUSIBLE_SPEED_KMH,
    OMNICOMM_ERRORS,
)
from omnicomm_report.models import ReportPeriod, VehicleMetrics


# --- Синонимы заголовков Excel → поля VehicleMetrics (ТЗ Режим Б) -------------
#
# Ключ — поле модели, значение — список синонимов (нижний регистр, без лишних
# пробелов). Сопоставление по вхождению подстроки, поэтому порядок ВАЖЕН:
# более длинные/специфичные синонимы должны проверяться раньше общих
# (например «расход на 100» раньше «расход»), иначе общий перехватит столбец.
HEADER_SYNONYMS: list[tuple[str, list[str]]] = [
    # сначала специфичные «расход на 100 км» — иначе «расход» перехватит колонку
    ("fuel_per_100km", ["расход на 100 км", "расход на 100", "л/100", "l/100"]),
    ("fuel_idle_l", ["расход без движения", "топливо без движения"]),
    ("fuel_l", ["расход топлива", "расход, л", "расход", "топливо", "fuel"]),
    ("speeding_mileage_km", ["пробег с превышением"]),
    ("mileage_km", ["пробег, км", "пробег", "mileage"]),
    ("engine_idle_hours",
     ["работа двигателя без движения", "двигателя без движения",
      "работа без движения", "двигатель без движения", "простой двигателя"]),
    ("engine_hours", ["время работы двигателя", "моточасов", "моточасы"]),
    ("max_speed_kmh", ["максимальная скорость", "макс скорость", "max speed"]),
    ("speeding_count", ["кол-во превышений", "превышения скорости", "превышения"]),
    ("name", ["гос. номер", "госномер", "наименование", "название", "объект", "тс"]),
]

# Столбцы, которые нужно ПОЛНОСТЬЮ игнорировать (бизнес-инвариант CLAUDE.md):
# «возможные сливы топлива» нельзя выводить дальше по конвейеру.
IGNORED_HEADER_MARKERS: tuple[str, ...] = ("слив", "возможные сливы")

# Явные идентификаторы ТС (если есть отдельная колонка id/uuid).
ID_HEADER_MARKERS: tuple[str, ...] = ("uuid", "id ", " id", "идентификатор")

# Значения-«пусто» в ячейках Excel → None.
_EMPTY_TOKENS: frozenset[str] = frozenset({"", "-", "—", "–", "n/a", "na", "н/д", "нет", "null", "none"})


# Поля модели, которые трактуем как целые (остальные числовые — float).
_INT_FIELDS: frozenset[str] = frozenset({"speeding_count"})


# --- Helpers: чистый парсинг чисел --------------------------------------------

def _to_float(value: Any) -> Optional[float]:
    """Привести значение к float, иначе None.

    Почему отдельно: Excel-выгрузки несут «грязные» числа — запятая как
    десятичный разделитель, пробелы/неразрывные пробелы как разделители тысяч,
    суффиксы единиц («1 234,5 км»). NaN из pandas и пустые маркеры → None.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        # bool — подкласс int, но как метрика бессмысленен.
        return None
    if isinstance(value, (int, float)):
        # отсекаем NaN (float('nan') != сам себя).
        return None if value != value else float(value)

    text = str(value).strip()
    if text.lower() in _EMPTY_TOKENS:
        return None

    # Убрать разделители тысяч (обычный/неразрывный/узкий неразрывный пробел),
    # десятичную запятую → точку, оставить только цифры/знак/точку.
    text = text.replace(" ", "").replace(" ", "").replace(" ", "")
    text = text.replace(",", ".")
    # вытащить первое число (на случай суффикса единиц «12.3км» / «12.3 л»)
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if match is None:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _to_int(value: Any) -> Optional[int]:
    """Привести к int через _to_float (с округлением), иначе None."""
    f = _to_float(value)
    return None if f is None else int(round(f))


def _coerce(field_name: str, value: Any) -> Any:
    """Применить нужный числовой парсер по имени поля модели."""
    if field_name in _INT_FIELDS:
        return _to_int(value)
    return _to_float(value)


def _norm_header(header: Any) -> str:
    """Нормализовать заголовок столбца: нижний регистр, схлопнутые пробелы."""
    return re.sub(r"\s+", " ", str(header).strip().lower())


# --- Excel-режим (ТЗ Режим Б) -------------------------------------------------

def _map_columns(columns: list[str]) -> tuple[dict[str, str], Optional[str], list[str]]:
    """Сопоставить заголовки Excel полям модели по словарю синонимов.

    Возвращает (mapping, id_column, ignored) где:
      mapping   — {имя_столбца: поле_модели}
      id_column — имя столбца с явным ID ТС (если найден)
      ignored   — столбцы, намеренно отброшенные (в т.ч. «слив топлива»)

    Почему по вхождению подстроки: реальные заголовки содержат единицы и уточнения
    («Пробег, км», «Расход топлива, л») — точное равенство не сработает.
    Каждое поле занимаем один раз; первый подошедший синоним выигрывает.
    """
    mapping: dict[str, str] = {}
    id_column: Optional[str] = None
    ignored: list[str] = []
    taken_fields: set[str] = set()

    for col in columns:
        norm = _norm_header(col)

        # 1) бизнес-инвариант: «сливы топлива» не маппим вообще.
        if any(marker in norm for marker in IGNORED_HEADER_MARKERS):
            ignored.append(col)
            continue

        # 2) явный ID ТС (берём первый встретившийся).
        if id_column is None and any(marker.strip() in norm for marker in ID_HEADER_MARKERS):
            id_column = col
            continue

        # 3) синонимы метрик/имени (порядок в HEADER_SYNONYMS значим).
        matched = False
        for field_name, synonyms in HEADER_SYNONYMS:
            if field_name in taken_fields:
                continue
            if any(syn in norm for syn in synonyms):
                mapping[col] = field_name
                taken_fields.add(field_name)
                matched = True
                break

        if not matched:
            # неизвестный столбец — не теряем, уйдёт в .raw для трассировки.
            ignored.append(col)

    return mapping, id_column, ignored


def load_from_excel(path: str, *, sheet: Any = None) -> list[VehicleMetrics]:
    """Загрузить ТС из Excel-выгрузки (ТЗ Режим Б).

    Автоопределяет структуру по словарю синонимов `HEADER_SYNONYMS`, нормализует
    числа, складывает неизвестные столбцы в `.raw`. Столбец «сливы топлива»
    игнорируется (бизнес-инвариант). Если явной колонки ID нет — id = name.

    :param path:  путь к .xlsx/.xls
    :param sheet: имя/индекс листа; None → первый лист
    """
    # openpyxl-движок задан явно — стабильно для .xlsx, не зависим от автоопределения.
    sheet_name = 0 if sheet is None else sheet
    df = pd.read_excel(path, sheet_name=sheet_name, engine="openpyxl")
    return _df_to_vehicles(df)


def load_from_csv(path: str, *, sep: Any = None, encoding: Any = None) -> list[VehicleMetrics]:
    """Загрузить ТС из CSV-выгрузки (тот же маппинг колонок, что и Excel).

    Разделитель и кодировка автоопределяются (рус. выгрузки часто `;` и cp1251).

    :param path:     путь к .csv
    :param sep:      разделитель столбцов; None → автоопределение (`engine="python"`)
    :param encoding: кодировка; None → пробуем utf-8-sig, затем cp1251
    """
    encodings = [encoding] if encoding else ["utf-8-sig", "cp1251"]
    last_err: Optional[Exception] = None
    for enc in encodings:
        try:
            delimiter = sep or _sniff_delimiter(path, enc)
            df = pd.read_csv(path, encoding=enc, sep=delimiter, engine="python")
            return _df_to_vehicles(df)
        except (UnicodeDecodeError, UnicodeError) as exc:
            last_err = exc
            continue
    raise ValueError(f"Не удалось прочитать CSV {path!r}: {last_err}")


def _sniff_delimiter(path: str, encoding: str) -> str:
    """Определить разделитель по строке заголовка.

    csv.Sniffer ошибается на рус. выгрузках с десятичной запятой, поэтому
    считаем кандидатов в первой строке и берём самый частый (`;` приоритетнее
    `,`, т.к. при `;` запятая — это десятичный разделитель чисел).
    """
    with open(path, encoding=encoding) as fh:
        header = fh.readline()
    counts = {d: header.count(d) for d in (";", "\t", ",")}
    best = max(counts, key=lambda d: counts[d])
    return best if counts[best] > 0 else ","


def _df_to_vehicles(df: "pd.DataFrame") -> list[VehicleMetrics]:
    """Привести таблицу (Excel/CSV) к списку VehicleMetrics по словарю синонимов."""
    columns = [str(c) for c in df.columns]
    mapping, id_column, ignored_cols = _map_columns(columns)

    vehicles: list[VehicleMetrics] = []
    for _, row in df.iterrows():
        # raw: исходная строка целиком (включая отброшенные столбцы) для трассировки.
        raw: dict[str, Any] = {col: _raw_cell(row[col]) for col in columns}

        # собрать значения смапленных полей
        values: dict[str, Any] = {}
        name_value: Optional[str] = None
        for col, field_name in mapping.items():
            cell = row[col]
            if field_name == "name":
                name_value = _clean_text(cell)
            else:
                values[field_name] = _coerce(field_name, cell)

        # id: явная колонка → иначе имя ТС
        vid = _clean_text(row[id_column]) if id_column is not None else None
        if not vid:
            vid = name_value
        if not vid:
            # ни id, ни имени — строка-пустышка (итоги/разделитель), пропускаем.
            continue
        if not name_value:
            name_value = vid

        vehicles.append(
            VehicleMetrics(
                vehicle_id=vid,
                name=name_value,
                mileage_km=values.get("mileage_km"),
                fuel_l=values.get("fuel_l"),
                fuel_per_100km=values.get("fuel_per_100km"),
                engine_hours=values.get("engine_hours"),
                engine_idle_hours=values.get("engine_idle_hours"),
                fuel_idle_l=values.get("fuel_idle_l"),
                max_speed_kmh=values.get("max_speed_kmh"),
                speeding_count=values.get("speeding_count"),
                speeding_mileage_km=values.get("speeding_mileage_km"),
                raw=raw,
            )
        )

    return vehicles


def _clean_text(value: Any) -> Optional[str]:
    """Текстовое значение ячейки → trimmed str, пустые маркеры → None."""
    if value is None or (isinstance(value, float) and value != value):  # NaN
        return None
    text = str(value).strip()
    return None if text.lower() in _EMPTY_TOKENS else text


def _raw_cell(value: Any) -> Any:
    """Привести ячейку к JSON-дружелюбному виду для .raw (NaN → None)."""
    if isinstance(value, float) and value != value:
        return None
    return value


# --- API-режим (ТЗ §16.1) -----------------------------------------------------

def _no_data_reason(error_code: int) -> Optional[str]:
    """Человекочитаемая причина «нет данных» по коду Omnicomm (config)."""
    entry = OMNICOMM_ERRORS.get(error_code)
    return entry[1] if entry else f"код {error_code}"


def _fnum(value: Any) -> Optional[float]:
    """Число → float, иначе None (для агрегатов сводного отчёта)."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return _to_float(value)


def _aggregate_consolidated(
    records: list[dict[str, Any]],
    name_map: Optional[dict[str, str]] = None,
) -> list[VehicleMetrics]:
    """Свернуть «сырые» items сводного отчёта в VehicleMetrics по каждому ТС.

    consolidatedReport отдаёт строку на ТС × сутки (блоки `mv`/`fuel`). Суммируем
    суточные значения по `vehicleId`, скорость берём максимумом. Имя ТС — из
    `name_map` (terminal_id→имя из дерева), иначе сам id. Маркеры «нет данных»
    (коды 5/7/9/10/11) сохраняются как ТС с has_data=False.
    """
    name_map = name_map or {}
    # аккумуляторы по vehicleId
    acc: dict[str, dict[str, Any]] = {}
    no_data: dict[str, str] = {}

    def bucket(vid: str) -> dict[str, Any]:
        return acc.setdefault(vid, {
            "mileage": 0.0, "fuel": 0.0, "fuel_idle": 0.0,
            "worked_s": 0.0, "idle_s": 0.0, "speed_km": 0.0,
            "max_speed": None, "any": False, "raw": [],
            # поля модуля «Работа на погрузке»
            "idling_rpm_s": 0.0, "normal_rpm_s": 0.0, "under_load_rpm_s": 0.0,
            "uni_on_s": 0.0, "uni_fuel_l": 0.0, "uni_hour_cons_l": None,
            "uni_type": None, "uni_present": False,
            # топливные формы (Заправки/Сливы/Выдача/Объём бака) — из fuel-блока сводного
            "refuel": 0.0, "drain": 0.0, "delivery": 0.0,
            "vol_start": None, "vol_end": None, "vol_min": None, "vol_max": None,
            "vol_start_date": None, "vol_end_date": None,
        })

    for rec in records:
        if rec.get("no_data"):
            vid = str(rec.get("vehicle_id"))
            no_data[vid] = _no_data_reason(int(rec.get("code", 10)))
            continue
        cr = rec.get("consolidatedReport") if isinstance(rec.get("consolidatedReport"), dict) else rec
        vid_raw = cr.get("vehicleId", cr.get("vehicle_id"))
        if vid_raw is None:
            continue
        vid = str(vid_raw)
        mv = cr.get("mv") or {}
        fuel = cr.get("fuel") or {}
        b = bucket(vid)
        b["raw"].append(cr)
        # Топливо в consolidatedReport — в ДЕЦИЛИТРАХ (сверено со спекой) → литры.
        DL = DECILITRES_TO_LITRES
        for key, src, sub, div in (
            ("mileage", "mileage", mv, 1),          # км
            ("speed_km", "mileageSpeeding", mv, 1),  # км
            ("worked_s", "worked", mv, 1),           # сек
            ("idle_s", "workedNoMovement", mv, 1),   # сек
            ("idling_rpm_s", "idlingRPM", mv, 1),
            ("normal_rpm_s", "normalRPM", mv, 1),
            ("under_load_rpm_s", "workedUnderLoadRPM", mv, 1),
            ("fuel", "fuelConsumption", fuel, DL),       # дл → л
            ("fuel_idle", "fuelConsumptionWOMovement", fuel, DL),  # дл → л
            ("refuel", "refuelling", fuel, DL),          # заправки, дл → л
            ("drain", "draining", fuel, DL),             # сливы (измеренные), дл → л
            ("delivery", "delivery", fuel, DL),          # выдача (АТЗ), дл → л
        ):
            val = _fnum(sub.get(src))
            if val is not None:
                b[key] += val / div
                b["any"] = True
        # Объём бака — суточные граничные значения (не сумма): старт=по ранней дате,
        # конец=по поздней, мин/макс — по всему окну. Дл → л.
        _d = cr.get("date") or 0
        _sv, _ev = _fnum(fuel.get("startVolume")), _fnum(fuel.get("endVolume"))
        _mn, _mx = _fnum(fuel.get("minVolume")), _fnum(fuel.get("maxVolume"))
        if _sv is not None and (b["vol_start_date"] is None or _d <= b["vol_start_date"]):
            b["vol_start"], b["vol_start_date"] = _sv / DL, _d
        if _ev is not None and (b["vol_end_date"] is None or _d >= b["vol_end_date"]):
            b["vol_end"], b["vol_end_date"] = _ev / DL, _d
        if _mn is not None:
            b["vol_min"] = _mn / DL if b["vol_min"] is None else min(b["vol_min"], _mn / DL)
        if _mx is not None:
            b["vol_max"] = _mx / DL if b["vol_max"] is None else max(b["vol_max"], _mx / DL)
        ms = _fnum(mv.get("maxSpeed"))
        # Отбрасываем сбойные значения GPS (напр. 655 км/ч) — иначе портят максимум.
        if ms is not None and 0 < ms <= MAX_PLAUSIBLE_SPEED_KMH:
            b["max_speed"] = ms if b["max_speed"] is None else max(b["max_speed"], ms)
            b["any"] = True
        # Универсальный вход (датчик гидравлики/PTO) — берём вход №1.
        for u in cr.get("uniDataList") or []:
            if u.get("univInputNumber") not in (None, 1):
                continue
            b["uni_present"] = True
            if u.get("uniType") is not None:
                b["uni_type"] = u.get("uniType")
            on = _fnum(u.get("univInputOnTime"))
            if on is not None:
                b["uni_on_s"] += on
            fc = _fnum(u.get("univInputOnConsumption"))
            if fc is not None:
                b["uni_fuel_l"] += fc / DECILITRES_TO_LITRES  # дл → л
            hc = _fnum(u.get("univInputHourConsumption"))
            if hc is not None:  # уже л/моточас
                b["uni_hour_cons_l"] = hc
            break

    vehicles: list[VehicleMetrics] = []

    # ТС с данными
    for vid, b in acc.items():
        name = name_map.get(vid) or vid
        if not b["any"]:
            vehicles.append(VehicleMetrics(
                vehicle_id=vid, name=name, has_data=False,
                no_data_reason=_no_data_reason(10)))
            continue
        vm = VehicleMetrics(
            vehicle_id=vid,
            name=name,
            mileage_km=round(b["mileage"], 1),
            fuel_l=round(b["fuel"], 1),
            fuel_idle_l=round(b["fuel_idle"], 1),
            engine_hours=round(b["worked_s"] / 3600, 2),
            engine_idle_hours=round(b["idle_s"] / 3600, 2),
            speeding_mileage_km=round(b["speed_km"], 1),
            max_speed_kmh=b["max_speed"],
            refuel_l=round(b["refuel"], 1) if b["refuel"] else None,
            drain_l=round(b["drain"], 1) if b["drain"] else None,
            delivery_l=round(b["delivery"], 1) if b["delivery"] else None,
            vol_start_l=round(b["vol_start"], 1) if b["vol_start"] is not None else None,
            vol_end_l=round(b["vol_end"], 1) if b["vol_end"] is not None else None,
            vol_min_l=round(b["vol_min"], 1) if b["vol_min"] is not None else None,
            vol_max_l=round(b["vol_max"], 1) if b["vol_max"] is not None else None,
            raw={"days": len(b["raw"])},
        )
        # Модуль «Работа на погрузке»: классификация источника + метрики.
        loading.classify_and_fill(vm, {
            "worked_s": b["worked_s"], "no_move_s": b["idle_s"],
            "idling_rpm_s": b["idling_rpm_s"], "normal_rpm_s": b["normal_rpm_s"],
            "under_load_rpm_s": b["under_load_rpm_s"],
            "uni_present": b["uni_present"], "uni_type": b["uni_type"],
            "uni_on_s": b["uni_on_s"], "uni_fuel_l": b["uni_fuel_l"],
            "uni_hour_cons_l": b["uni_hour_cons_l"],
            "fuel_wo_move_l": b["fuel_idle"], "max_speed": b["max_speed"],
        })
        vehicles.append(vm)

    # ТС с маркером «нет данных» (если не пришли с данными в другом окне периода)
    present = {vm.vehicle_id for vm in vehicles}
    for vid, reason in no_data.items():
        if vid not in present:
            vehicles.append(VehicleMetrics(
                vehicle_id=vid, name=name_map.get(vid) or vid,
                has_data=False, no_data_reason=reason))

    return vehicles


def _extract_records(payload: Any) -> list[dict[str, Any]]:
    """Достать список записей ТС из ответа API произвольной обёртки.

    Клиент может вернуть list напрямую либо dict с обёрткой
    ('data'/'rows'/'vehicles'/'result'/'items') — поддерживаем оба варианта.
    """
    if payload is None:
        return []
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        for key in ("data", "rows", "vehicles", "result", "items", "report"):
            inner = payload.get(key)
            if isinstance(inner, list):
                return [r for r in inner if isinstance(r, dict)]
        # одиночная запись в виде dict
        return [payload]
    return []


def load_from_api(
    client: Any,
    period: ReportPeriod,
    vehicle_ids: Optional[list[str]] = None,
    *,
    with_track: bool = False,
) -> list[VehicleMetrics]:
    """Загрузить ТС через Omnicomm REST API (ТЗ §16.1).

    Резолвит дерево ТС (`client.list_vehicles`) для карты terminal_id→имя и для
    автоподстановки всех ТС, если список не задан. Затем берёт
    `client.get_consolidated_report(...)` и сворачивает суточные строки в
    VehicleMetrics. Батчинг, ретраи, коды ошибок и нарезка периода — на стороне
    api_client; здесь только маппинг/агрегация ответа в модель.

    :param client:      объект api_client (get_consolidated_report + list_vehicles)
    :param period:      период отчёта (даёт start_ts/end_ts, UNIX UTC)
    :param vehicle_ids: terminal_id ТС; None → все доступные ТС из дерева
    :param with_track:  True → дозапросить GPS-трек и выделить точки погрузки
                        (кластеры стоянок) для ТС, где это осмысленно (модуль погрузки)
    """
    # Карта terminal_id → имя ТС (из дерева): consolidatedReport отдаёт только
    # числовой vehicleId без названия. №3: список ТС не задан → берём все из дерева.
    name_map: dict[str, str] = {}
    catalog = getattr(client, "list_vehicles", None)
    if callable(catalog):
        fleet = catalog() or []
        for v in fleet:
            tid = v.get("terminal_id") or v.get("id") or v.get("uuid")
            nm = v.get("name")
            if tid is not None and nm:
                name_map[str(tid)] = nm
        if not vehicle_ids:
            vehicle_ids = [
                str(v.get("terminal_id") or v.get("id") or v.get("uuid"))
                for v in fleet
                if (v.get("terminal_id") or v.get("id") or v.get("uuid")) is not None
            ] or None

    payload = client.get_consolidated_report(vehicle_ids or [], period)
    records = _extract_records(payload)
    vehicles = _aggregate_consolidated(records, name_map)

    # Точки погрузки (опц.). АВТОДЕТЕКТ: сначала геозоны-площадки клиента (точно),
    # если их нет/пусто — фолбэк на GPS-кластеризацию стоянок (приблизительно).
    if with_track:
        by_vid = {vm.vehicle_id: vm for vm in vehicles}
        used_geozones = False
        gz = getattr(client, "get_geozones_report", None)
        if callable(gz):
            try:
                visits = loading.parse_geozone_visits(gz(vehicle_ids or [], period))
            except Exception:  # noqa: BLE001 — геозоны не критичны
                visits = {}
            if visits:                       # у клиента заведены геозоны и есть визиты
                used_geozones = True
                for vid, pts in visits.items():
                    vm = by_vid.get(vid)
                    if not vm:
                        continue
                    vm.loading_points = pts
                    # Площадки = обслуживание: оцениваем погрузку, если нет датчика.
                    if vm.loading_method in (None, "none"):
                        loading.estimate_loading_from_stops(vm, pts, windowed=False)

        tracker = getattr(client, "get_track", None)
        if not used_geozones and callable(tracker):
            for vm in vehicles:
                # Трек нужен ТОЛЬКО для бессенсорной GPS-оценки погрузки — т.е. там, где
                # НЕТ датчика/оборотов (метод none) и есть работа стоя. Остальным ТС трек
                # не запрашиваем (GPS-карта убрана) — это и экономит запросы.
                if (not vm.has_data or vm.loading_method not in (None, "none")
                        or not vm.work_no_move_hours):
                    continue
                try:
                    track = tracker(vm.vehicle_id, period)
                except Exception:  # noqa: BLE001 — трек не критичен
                    continue
                # Остановки от LOADING_STOP_MIN_SEC (калибровка gct — обслуживание
                # площадок часто <3 мин, дефолтные 180с их теряли); спутники не
                # фильтруем — на стоянке их часто 0, иначе стоянка дробится.
                pts = loading.cluster_track_points(
                    track, min_stop_s=config.LOADING_STOP_MIN_SEC, min_satellites=0)
                if pts:
                    loading.estimate_loading_from_stops(
                        vm, pts, min_s=config.LOADING_STOP_MIN_SEC,
                        max_s=config.LOADING_STOP_MAX_SEC)

    return vehicles


# --- Диспетчер ----------------------------------------------------------------

def load(source: str, **kwargs: Any) -> list[VehicleMetrics]:
    """Единая точка входа: выбрать загрузчик по источнику.

    :param source: 'excel' → load_from_excel; 'api' → load_from_api
    :param kwargs: проброс в выбранный загрузчик (path/sheet или client/period/vehicle_ids)
    :raises ValueError: неизвестный источник
    """
    key = source.strip().lower()
    if key == "excel":
        return load_from_excel(**kwargs)
    if key == "csv":
        return load_from_csv(**kwargs)
    if key == "api":
        return load_from_api(**kwargs)
    raise ValueError(
        f"Неизвестный источник данных: {source!r} (ожидалось 'excel', 'csv' или 'api')"
    )
