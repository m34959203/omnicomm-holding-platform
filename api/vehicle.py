"""Карточка ТС: live-данные одного ТС по запросу (трек + телеметрия).

Трек тяжёлый и не лежит в снапшоте → тянем по запросу для конкретного ТС
(дёшево: один ТС). Залогиненный клиент кэшируется в процессе, токен освежается
самим OmnicommClient. Источник трека: GET /reports/track/{id} (проверено,
точки {date,latitude,longitude,speed,direction,satellitesCount}).
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Callable, Optional

from omnicomm_report import data_loader
from omnicomm_report.models import ReportPeriod

_client = None
_lock = threading.Lock()

# TTL-кэш карточки ТС: карточка — единственное место, где клик пользователя =
# живой запрос в Omnicomm. Кэшируем результат на ТС×период, чтобы повторные/
# параллельные открытия не пуляли в московский сервер (как весь дашборд —
# «пуляем раз, отдаём многим»). Трек/состояние — короткий TTL, телеметрия (дневной
# агрегат) — длиннее.
TRACK_TTL_SEC = 300       # 5 мин
TELEMETRY_TTL_SEC = 900   # 15 мин
_CACHE_MAX = 600          # потолок записей (по ТС×период), защита памяти
_card_cache: dict[str, tuple[float, dict]] = {}
_card_lock = threading.Lock()


def _cached(key: str, ttl: int, build: Callable[[], dict]) -> dict:
    """Вернуть из кэша, если свежо (< ttl), иначе собрать и положить."""
    now = time.monotonic()
    with _card_lock:
        hit = _card_cache.get(key)
        if hit is not None and now - hit[0] < ttl:
            return hit[1]
    value = build()  # медленный live-вызов — вне лока
    with _card_lock:
        _card_cache[key] = (now, value)
        if len(_card_cache) > _CACHE_MAX:  # чистка протухших
            for k in [k for k, (t, _) in _card_cache.items() if now - t >= ttl]:
                _card_cache.pop(k, None)
    return value


def _get_client():
    """Залогиненный клиент Omnicomm, кэш на процесс (ленивый, под локом)."""
    global _client
    with _lock:
        if _client is None:
            from omnicomm_report.api_client import OmnicommClient
            from omnicomm_report.config import Settings
            cl = OmnicommClient(Settings.from_env())
            cl.login()
            _client = cl
        return _client


def _downsample(seq: list, cap: int) -> list:
    """Прорядить список до ~cap элементов, сохранив первый/последний."""
    n = len(seq)
    if n <= cap:
        return seq
    step = n / cap
    out = [seq[int(i * step)] for i in range(cap)]
    if seq[-1] is not out[-1]:
        out[-1] = seq[-1]
    return out


def _period(start_ts: int, end_ts: int) -> ReportPeriod:
    return ReportPeriod(start=datetime.fromtimestamp(start_ts, timezone.utc),
                        end=datetime.fromtimestamp(end_ts, timezone.utc))


def track_detail(terminal_id: str, start_ts: int, end_ts: int) -> dict:
    """Карточка-трек. СНАЧАЛА из локального архива (`raw_store.fact_track`) — мгновенно,
    в Omnicomm не ходим (год треков уже добран бэкфиллом). Если архив за окно пуст
    (ТС/период ещё не залит) — live-фолбэк с TTL-кэшем."""
    from . import raw_store
    stored = raw_store.load_track(terminal_id, start_ts, end_ts, raw_store.DEFAULT_PATH)
    if stored:
        return _payload_from_track(terminal_id, start_ts, end_ts, stored,
                                   state={}, source="store")
    return _cached(f"track:{terminal_id}:{start_ts}:{end_ts}", TRACK_TTL_SEC,
                   lambda: _track_detail_live(terminal_id, start_ts, end_ts))


def _payload_from_track(terminal_id: str, start_ts: int, end_ts: int,
                        track: list[dict], *, state: dict, source: str) -> dict:
    """Собрать ответ карточки из уже нормализованных точек {lat,lon,speed,ts,sat}."""
    poly = _downsample(track, 1000)
    speed_series = [{"ts": t["ts"], "speed": t["speed"]}
                    for t in _downsample(track, 400)]
    return {
        "terminal_id": str(terminal_id),
        "name": None,
        "period": {"start_ts": start_ts, "end_ts": end_ts},
        "track": poly,
        "speed_series": speed_series,
        "last": track[-1] if track else None,
        "track_points": len(track),
        "track_max_speed": round(max((t["speed"] for t in track), default=0), 1),
        "state": state,
        "telemetry": {},
        "source": source,
    }


def telemetry(terminal_id: str, start_ts: int, end_ts: int) -> dict:
    """Телеметрия с TTL-кэшем."""
    return _cached(f"tele:{terminal_id}:{start_ts}:{end_ts}", TELEMETRY_TTL_SEC,
                   lambda: _telemetry_live(terminal_id, start_ts, end_ts))


def _track_detail_live(terminal_id: str, start_ts: int, end_ts: int) -> dict:
    """Трек ТС: полилиния + маркеры + ряд скорости. БЫСТРО (~1-2с) — без сводного.

    Имя ТС не дёргаем из дерева (~2000-элементный запрос) — фронт знает имя сам.
    Телеметрия (сводный отчёт ~16с на медленном контуре) грузится отдельно `telemetry()`.
    """
    client = _get_client()

    # Текущее состояние (мгновенное, лёгкий вызов): напряжение бортсети, адрес,
    # зажигание, текущие скорость/топливо — из /vehicles/{id}/state.
    st = client.get_vehicle_state(str(terminal_id))
    state = {
        "voltage": st.get("voltage"),
        "address": st.get("address"),
        "ignition": st.get("currentIgn"),
        "current_speed": st.get("currentSpeed"),
        "current_fuel": st.get("currentFuel"),
        "last_data_ts": st.get("lastDataDate"),
        "sat": st.get("lastGPSSat"),
    } if st else {}

    raw = client.get_track(str(terminal_id), _period(start_ts, end_ts))
    pts = [p for p in raw
           if p.get("latitude") is not None and p.get("longitude") is not None]
    track = [{"lat": p["latitude"], "lon": p["longitude"],
              "speed": p.get("speed") or 0, "ts": p.get("date"),
              "sat": p.get("satellitesCount")} for p in pts]
    return _payload_from_track(terminal_id, start_ts, end_ts, track,
                               state=state, source="live")


def _telemetry_live(terminal_id: str, start_ts: int, end_ts: int) -> dict:
    """Телеметрия ТС из сводного отчёта (МЕДЛЕННО ~16с) — грузится лениво."""
    client = _get_client()
    out: dict = {}
    try:
        payload = client.get_consolidated_report([str(terminal_id)], _period(start_ts, end_ts))
        records = data_loader._extract_records(payload)
        vehicles = data_loader._aggregate_consolidated(records, {str(terminal_id): None})
        if vehicles:
            vm = vehicles[0]
            out = {
                "max_speed_kmh": getattr(vm, "max_speed_kmh", None),
                "mileage_km": getattr(vm, "mileage_km", None),
                "fuel_l": getattr(vm, "fuel_l", None),
                "engine_hours": getattr(vm, "engine_hours", None),
                "fuel_idle_l": getattr(vm, "fuel_idle_l", None),
                "speeding_mileage_km": getattr(vm, "speeding_mileage_km", None),
            }
    except Exception:  # noqa: BLE001 — телеметрия не валит карточку
        out = {}
    return {"terminal_id": str(terminal_id), "telemetry": out}
