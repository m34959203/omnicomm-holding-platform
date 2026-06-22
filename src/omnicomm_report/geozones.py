"""Движок скоростных лимитов по геозонам (СТ Казатомпром).

Реализует `geozone_limit(геозона, категория_ТС) → лимит` из стандарта КАП
(docs/knowledge-base/09-kap-geozone-speed-standard.md):

- **Именованные геозоны** (источник истины) — лимит из справочника/имени.
- **Зонная матрица 6×3** (фолбэк) — `риск-зона × категория ТС`.
- Разрешение конфликтов: `min(именованный, матрица)` — превышать внутренний
  лимит нельзя, даже если ПДД допускают больше (СТ КАП п. 7.3/7.7).
- **Тип дороги** (для R-INV-1): Зоны 5/6 = дорога общего пользования (КоАП),
  Зоны 1–4 = технологическая (дисциплинарка СТ КАП, без статьи и ₸).

Категория ТС определяется дефолтным классификатором по имени (уточняется позже,
не требует согласования). Координат у геозон нет — геометрию матчим к Omnicomm
по имени отдельно; здесь — нормативные лимиты и классификация.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class VehicleCategory(str, Enum):
    LIGHT = "light"            # легковые (≤8 мест)
    BUS = "bus"               # автобусы/микроавтобусы (>8 мест)
    TRUCK_SPECIAL = "truck"   # грузовые/спецтехника (КрАЗ, Урал, компрессоры…)


# Таблица 1 СТ КАП (км/ч): риск-зона (1..6) × категория ТС.
ZONE_SPEED_MATRIX: dict[VehicleCategory, dict[int, int]] = {
    VehicleCategory.LIGHT:         {1: 5, 2: 20, 3: 30, 4: 40, 5: 60, 6: 110},
    VehicleCategory.BUS:           {1: 5, 2: 15, 3: 25, 4: 30, 5: 60, 6: 90},
    VehicleCategory.TRUCK_SPECIAL: {1: 5, 2: 10, 3: 20, 4: 20, 5: 60, 6: 70},
}

PUBLIC_ROAD_ZONES = {5, 6}     # дороги общего пользования → применима КоАП


@dataclass
class GeozoneLimit:
    geozone: str
    category: VehicleCategory
    limit: int                 # итоговый лимит, км/ч
    zone: int                  # риск-зона 1..6
    public_road: bool          # дорога общего пользования (КоАП) vs техдорога (СТ КАП)
    source: str                # "named" | "matrix" | "min(named,matrix)"


# --- Классификация риск-зоны по имени геозоны (СТ КАП §4) ---------------------
# Порядок: более специфичные/технологические паттерны раньше. Зона нужна прежде
# всего для гейта «дорога общего пользования (КоАП) vs техдорога (дисциплинарка)»;
# дефолт «неизвестно → Зона 4 (техдорога)» — безопасный (не применяем КоАП-штраф зря).
_ZONE_PATTERNS: list[tuple[int, re.Pattern]] = [
    (4, re.compile(r"\bгтп\b|угтп|тех\.?\s*дорог|технолог|полигон|залеж|\bюк[\s-]", re.I)),
    (1, re.compile(r"вахтов|промплощад|пром\.?\s*площад|шламо|дренаж", re.I)),
    (6, re.compile(r"трасс|автомагистрал|автобан|^[mаaрp][-\s]?\d|шоссе|объезд", re.I)),
    (5, re.compile(r"\bн\.?\s*п\.?\b|\bг\.\s|\bпос\.|\bсело|\bаул|город|посёлок|поселок|улиц", re.I)),
    (2, re.compile(r"\bзавод|\bопз\b|\bабк\b|склад|стоянк", re.I)),
    (6, re.compile(r"дорога до|дорога на", re.I)),
    (3, re.compile(r"подъезд|внутрен|между объект", re.I)),
]


def classify_zone(geozone: str) -> int:
    """Риск-зона 1..6 по имени геозоны. Дефолт (неизвестно) → 4 (технологическая,
    консервативно — самый строгий лимит у спецтехники)."""
    name = geozone or ""
    for zone, pat in _ZONE_PATTERNS:
        if pat.search(name):
            return zone
    return 4


def is_public_road(zone: int) -> bool:
    return zone in PUBLIC_ROAD_ZONES


# --- Дефолтный классификатор категории ТС (по имени; уточняется позже) --------
_BUS_RE = re.compile(r"автобус|микроавтобус|\bпаз\b|вахтовк|вахтов\w*\s*(авто|маш)", re.I)
_TRUCK_RE = re.compile(
    r"краз|урал|камаз|самосвал|компрессор|кран|экскаватор|погрузчик|буров|"
    r"спецтех|грузов|трал|шаланд|тягач|бульдозер|трактор|цистерн|тепловоз|дэс", re.I)
_LIGHT_RE = re.compile(r"легков|prado|прадо|уаз|нива|hilux|хайлюкс|пикап|land\s?cruiser|toyota|lexus", re.I)


def categorize_vehicle(name: str, vehicle_type: Optional[str] = None) -> VehicleCategory:
    """Дефолтная категория ТС по имени (+опц. тип). Эвристика — уточняется
    справочником позже, но даёт рабочий лимит уже сейчас."""
    text = f"{name or ''} {vehicle_type or ''}"
    if _BUS_RE.search(text):
        return VehicleCategory.BUS
    if _LIGHT_RE.search(text):
        return VehicleCategory.LIGHT
    if _TRUCK_RE.search(text):
        return VehicleCategory.TRUCK_SPECIAL
    # неизвестно → спец/грузовой (самый строгий лимит = безопасный дефолт)
    return VehicleCategory.TRUCK_SPECIAL


# --- Лимит из имени геозоны (часть несёт "NN км/ч" / завершается числом) ------
_LIMIT_IN_NAME = re.compile(r"(\d{1,3})\s*км/?ч", re.I)


def parse_limit_from_name(geozone: str) -> Optional[int]:
    """Достать ЯВНЫЙ лимит из имени геозоны ("… 80 км/ч" → 80). None — нет.

    Только форма «NN км/ч» — голое число в конце имени часто номер подзоны
    («Сателлит-1», «Полигон 2»), не лимит, поэтому не берём.
    """
    m = _LIMIT_IN_NAME.search(geozone or "")
    return _sane(int(m.group(1))) if m else None


def _sane(limit: Optional[int]) -> Optional[int]:
    """Отбраковать мусорные лимиты (0/отрицательные/нереальные)."""
    if limit is None:
        return None
    if limit <= 0 or limit > 140:
        return None
    return limit


def normalize_seed_limit(raw) -> Optional[int]:
    """Нормализовать лимит из справочника-выгрузки (строка/число/пусто/СТОП).

    Пустое/None/нечисловое → None (нет лимита). 0 (СТОП) → None (запрет ≠ скор. лимит).
    """
    if raw is None:
        return None
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw or raw.upper() in ("СТОП", "STOP"):
            return None
        m = re.search(r"\d{1,3}", raw)
        raw = int(m.group()) if m else None
    if isinstance(raw, (int, float)):
        return _sane(int(raw))
    return None


# --- Основной резолвер --------------------------------------------------------

def geozone_limit(geozone: str, category: VehicleCategory,
                  named_limit: Optional[int] = None) -> GeozoneLimit:
    """Итоговый лимит для (геозона, категория ТС).

    **Именованный лимит из справочника СТ КАП — источник истины** (это и есть
    внутренний стандарт для конкретной геозоны, учитывающий парк). Если его нет —
    пробуем достать из имени; если и там нет — **фолбэк на зонную матрицу 6×3**.
    Матрица НЕ занижает именованный лимит (СТ КАП: матрица — для точек вне
    именованной геозоны).
    """
    zone = classify_zone(geozone)
    named = named_limit if named_limit is not None else parse_limit_from_name(geozone)
    named = _sane(named)

    if named is not None:
        limit, source = named, "named"
    else:
        limit, source = ZONE_SPEED_MATRIX[category][zone], "matrix"

    return GeozoneLimit(geozone=geozone, category=category, limit=limit,
                        zone=zone, public_road=is_public_road(zone), source=source)
