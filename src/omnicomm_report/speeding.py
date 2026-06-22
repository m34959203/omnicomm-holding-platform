"""Детекция превышений скорости по GPS-треку (СТ КАП + КоАП РК).

Инварианты (docs/knowledge-base/05 §0, REVIEW-2026-06-22):
- **R-INV-3:** превышение — только по УСТОЙЧИВОМУ сегменту (≥N правдоподобных точек)
  + физфильтр выбросов (отбрасываем точки с нереальным ускорением и <4 спутников),
  а не по одной GPS-точке.
- **R-INV-1:** тип дороги определяет квалификацию — на дорогах общего пользования
  возможна КоАП-статья, на технологических — только дисциплинарка СТ КАП.
- **R-INV-8:** сумма штрафа проставляется только при `config.KOAP_VERIFIED`.

Привязка точки к геозоне (геометрия) — отдельная задача (нужны полигоны Omnicomm);
здесь `limit_fn(point) -> (геозона, лимит, дорога_общего_пользования)` инъектируется,
что делает алгоритм детекции тестируемым и независимым от источника лимита.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from . import config

# limit_fn: точка трека → (имя геозоны, лимит км/ч или None, дорога_общего_пользования)
LimitFn = Callable[[dict], "tuple[str, Optional[int], bool]"]


@dataclass
class Violation:
    terminal_id: str
    geozone: str
    limit: int
    max_speed: float
    excess: float                 # max_speed − limit, км/ч
    duration_s: int
    start_ts: int
    points: int
    public_road: bool             # дорога общего пользования (КоАП) vs техдорога
    st_kap_severity: str          # дисциплинарная градация СТ КАП
    koap_article: Optional[str] = None    # только для дорог общего пользования
    fine_kzt: Optional[int] = None        # только если config.KOAP_VERIFIED


# --- Физфильтр выбросов -------------------------------------------------------

def _valid_points(track, min_sat: int) -> list[dict]:
    out = []
    for p in track or []:
        if not isinstance(p, dict):
            continue
        if (p.get("satellitesCount") or 0) < min_sat:
            continue
        if p.get("date") is None or p.get("speed") is None:
            continue
        out.append(p)
    out.sort(key=lambda p: p["date"])
    return out


def _despike(points: list[dict], max_accel: float) -> list[dict]:
    """Убрать точки с нереальным ускорением относительно предыдущей валидной
    (GPS-выброс: скачок скорости, несовместимый с физикой). Δv в м/с, Δt в сек.
    """
    out: list[dict] = []
    for p in points:
        if out:
            dt = p["date"] - out[-1]["date"]
            if dt > 0:
                dv = abs(p["speed"] - out[-1]["speed"]) / 3.6
                if dv / dt > max_accel:
                    continue
        out.append(p)
    return out


# --- Квалификация -------------------------------------------------------------

def st_kap_severity(excess: float) -> str:
    """Дисциплинарная градация СТ КАП по величине превышения."""
    for low, label in config.ST_KAP_THRESHOLDS:
        if excess >= low:
            return label
    return "в норме"


def koap_for(excess: float) -> tuple[Optional[str], Optional[int]]:
    """Статья КоАП + сумма штрафа (₸) по превышению. Сумма — только если сверено
    (R-INV-8). Возвращает (статья|None, сумма|None)."""
    for low, mrp, article in config.KOAP_SPEEDING:
        if excess >= low:
            fine = mrp * config.MRP_KZT if config.KOAP_VERIFIED else None
            return article, fine
    return None, None


def _make_violation(terminal_id, segment) -> Optional[Violation]:
    """Собрать нарушение из сегмента over-limit точек (segment: [(p, gz, limit, public)])."""
    if len(segment) < config.SPEEDING_MIN_SEGMENT_POINTS:
        return None
    # опорная точка — с максимальной скоростью
    p, gz, limit, public = max(segment, key=lambda s: s[0]["speed"])
    max_speed = float(p["speed"])
    excess = round(max_speed - limit, 1)
    first, last = segment[0][0], segment[-1][0]
    sev = st_kap_severity(excess)
    article, fine = (koap_for(excess) if public else (None, None))
    return Violation(
        terminal_id=str(terminal_id), geozone=gz, limit=limit,
        max_speed=max_speed, excess=excess,
        duration_s=int(last["date"] - first["date"]), start_ts=int(first["date"]),
        points=len(segment), public_road=public, st_kap_severity=sev,
        koap_article=article, fine_kzt=fine,
    )


# --- Основная детекция --------------------------------------------------------

def detect_speeding(track, limit_fn: LimitFn, *, terminal_id: str = "") -> list[Violation]:
    """Найти устойчивые превышения в треке.

    `limit_fn(point) -> (геозона, лимит, дорога_общего_пользования)`. Точка «над
    лимитом», если `speed > limit`. Подряд идущие over-limit точки группируются в
    сегмент; сегмент ≥ `SPEEDING_MIN_SEGMENT_POINTS` → одно нарушение.
    """
    pts = _despike(_valid_points(track, config.SPEEDING_MIN_SATELLITES),
                   config.SPEEDING_MAX_ACCEL_MS2)
    violations: list[Violation] = []
    segment: list = []

    def flush():
        v = _make_violation(terminal_id, segment) if segment else None
        if v:
            violations.append(v)

    for p in pts:
        gz, limit, public = limit_fn(p)
        if limit is not None and p["speed"] > limit:
            segment.append((p, gz, limit, public))
        else:
            flush()
            segment = []
    flush()
    return violations


def detect_from_visits(visits, *, seed: Optional[dict] = None,
                       category_fn=None) -> dict:
    """Детекция превышений по ВИЗИТАМ геозон (`geozones_report`) — без геометрии.

    Каждый визит несёт `geozoneName` (с лимитом в имени), `mv.maxSpeed`,
    `mv.mileageSpeeding`, `geoInfo`. Лимит → `geozone_limit(имя, категория, seed)`;
    нарушение, если `maxSpeed > лимит` И ТС реально двигался в зоне (mileage>0,
    отсекаем стационарные GPS-выбросы — дух R-INV-3). Тип дороги → гейт КоАП (R-INV-1).

    Возвращает {terminal_id -> [Violation]}.
    """
    from . import geozones as gz
    cat_fn = category_fn or gz.categorize_vehicle
    out: dict = {}
    for v in visits or []:
        if not isinstance(v, dict):
            continue
        name = v.get("geozoneName") or ""
        mv = v.get("mv") or {}
        max_speed = mv.get("maxSpeed")
        if not name or max_speed is None or max_speed <= 0:
            continue
        if (mv.get("mileage") or 0) <= 0:        # не двигался в зоне → пропуск выброса
            continue
        tid = v.get("vehicleId") or v.get("id")
        if tid is None:
            continue
        named = gz.seed_limit(seed, name) if seed else None
        gl = gz.geozone_limit(name, cat_fn(v.get("vehicleName", "")), named)
        if max_speed <= gl.limit:
            continue
        excess = round(float(max_speed) - gl.limit, 1)
        geo = v.get("geoInfo") or {}
        article, fine = (koap_for(excess) if gl.public_road else (None, None))
        out.setdefault(str(tid), []).append(Violation(
            terminal_id=str(tid), geozone=name, limit=gl.limit,
            max_speed=float(max_speed), excess=excess,
            duration_s=int(geo.get("duration") or 0),
            start_ts=int(geo.get("startDate") or 0),
            points=int(mv.get("mileageSpeeding") or 0),   # км с превышением (Omnicomm)
            public_road=gl.public_road, st_kap_severity=st_kap_severity(excess),
            koap_article=article, fine_kzt=fine,
        ))
    return out


def triage_speeding_suspects(consolidated_rows, min_zone_limit: int = 20) -> list[str]:
    """Дешёвый триаж (R-инвариант масштаба): по суточному `mv.maxSpeed` отобрать ТС,
    у кого вообще есть смысл тянуть трек (max за сутки выше минимального лимита зон).
    Возвращает terminal_id-кандидаты — только по ним потом дёргаем тяжёлый трек.
    """
    suspects: set[str] = set()
    for row in consolidated_rows or []:
        cr = row.get("consolidatedReport") if isinstance(row.get("consolidatedReport"), dict) else row
        mv = cr.get("mv") or {}
        mx = mv.get("maxSpeed")
        tid = cr.get("vehicleId") or cr.get("id")
        if tid is not None and mx is not None and mx > min_zone_limit:
            suspects.add(str(tid))
    return sorted(suspects)
