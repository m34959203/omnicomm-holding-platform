"""Бережный бэкфилл GPS-треков за год в локальный архив (`raw_store.fact_track`).

Требование: система держит у себя весь год треков, чтения карточки — мгновенные из
архива, в Omnicomm при клике не ходим. Забор устроен так, чтобы **НЕ нагружать
сервер Omnicomm**:

1. **Выделенный медленный потолок** (`TRACK_BACKFILL_RATE_PER_MIN` ≪ лимита аккаунта
   170/мин) ПОВЕРХ глобального аккаунт-лимитера клиента → суммарно к Omnicomm никогда
   не превышаем лимит, а сам бэкфилл «капает», оставляя полосу дневному синку.
2. **Резюмируемость + идемпотентность:** уже сохранённые сутки (`fact_track`)
   пропускаются; повторный запуск ничего не перезабирает. Чекпоинт = строка в БД.
3. **Только дни с движением:** трек тянем лишь за те (ТС×сутки), где агрегат
   (`fact_daily`) показал пробег ≥ `TRACK_MIN_MILEAGE_KM`. Стоянки/простой не дёргаем —
   на порядок меньше запросов, чем 2000 ТС × 365 сут «в лоб». День без агрегатов
   пропускаем целиком (сначала добери агрегаты инкрементальным синком).
4. **Wall-clock-кап на запуск** (`TRACK_BACKFILL_MAX_SECONDS`): cron гоняет короткими
   ночными слайсами, остаток добирается в следующий слайс (за счёт п.2).
5. **Хранение — упрощённой полилинией** (Дуглас-Пекер) после физической чистки выбросов.

`run_track_backfill(days=365)` — разовый годовой бэкфилл (в слайсах до заполнения).
`run_track_backfill(days=2)` — ночной до-вод свежих суток (когда год уже залит,
почти всё пропускается как present → дёшево). Один и тот же код.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Callable, Optional

from omnicomm_report import config, data_loader, track_clean
from omnicomm_report.models import ReportPeriod
from omnicomm_report.rate_limit import RateLimiter

from . import raw_store
from .sync import _dedup_records, _new_live_client

ProgressCb = Callable[[float, str], None]


def _day_start(ts: int) -> int:
    return (int(ts) // 86400) * 86400


def _moved_vehicles(day_records: list, name_map: dict, min_km: float) -> dict:
    """{terminal_id: пробег_км} для ТС, проехавших ≥ min_km за сутки (из агрегатов)."""
    vehicles = data_loader._aggregate_consolidated(_dedup_records(day_records), name_map)
    out: dict = {}
    for vm in vehicles:
        mil = getattr(vm, "mileage_km", 0) or 0
        if mil >= min_km:
            out[str(vm.vehicle_id)] = mil
    return out


def _normalize(raw: list) -> list[dict]:
    """Сырые точки трека → чистка выбросов → упрощение → компактный формат архива."""
    pts = [p for p in (raw or [])
           if p.get("latitude") is not None and p.get("longitude") is not None]
    cleaned = track_clean.clean_track(pts).clean
    simplified = track_clean.simplify_track(cleaned, config.TRACK_SIMPLIFY_EPSILON_DEG)
    return [{"lat": p["latitude"], "lon": p["longitude"],
             "speed": p.get("speed") or 0, "ts": p.get("date"),
             "sat": p.get("satellitesCount")} for p in simplified]


def run_track_backfill(progress: ProgressCb, *, days: Optional[int] = None,
                       min_km: Optional[float] = None,
                       rate_per_min: Optional[float] = None,
                       max_seconds: Optional[float] = None,
                       raw_path: Optional[str] = None,
                       client=None, name_map: Optional[dict] = None,
                       now: Optional[int] = None) -> dict:
    """Добрать треки за `days` суток в архив, бережно к Omnicomm. См. модуль-докстринг."""
    days = days or config.TRACK_BACKFILL_DAYS
    min_km = config.TRACK_MIN_MILEAGE_KM if min_km is None else min_km
    rate_per_min = rate_per_min or config.TRACK_BACKFILL_RATE_PER_MIN
    # max_seconds=0 — легитимный «стоп сразу», поэтому именно None-проверка, не `or`.
    max_seconds = config.TRACK_BACKFILL_MAX_SECONDS if max_seconds is None else max_seconds
    raw_path = raw_path or raw_store.DEFAULT_PATH
    now = int(now if now is not None else time.time())
    deadline = time.monotonic() + max_seconds
    limiter = RateLimiter(rate_per_min)   # бережный потолок именно для бэкфилла

    if client is None:
        client = _new_live_client()
    if name_map is None:
        tree_vehicles = client.list_vehicles() or []
        name_map = {str(v.get("terminal_id") or v.get("id") or v.get("uuid")): v.get("name")
                    for v in tree_vehicles
                    if (v.get("terminal_id") or v.get("id") or v.get("uuid"))}

    today0 = _day_start(now)
    day_starts = [today0 - k * 86400 for k in range(days)]   # сегодня → назад в прошлое
    present = raw_store.tracks_present(day_starts[-1], today0 + 86400, raw_path)

    pulled = skipped_present = idle_days = no_aggregate_days = 0
    stopped = False
    progress(2, f"Бэкфилл треков: {days} сут, лимит {rate_per_min:.0f}/мин (бережно)")
    for di, ds in enumerate(day_starts):
        if time.monotonic() >= deadline:
            stopped = True
            break
        de = ds + 86400
        day_records = raw_store.load_daily(ds, de - 1, raw_path)
        if not day_records:
            no_aggregate_days += 1          # нет агрегатов → не знаем движения, не дёргаем
            continue
        moved = _moved_vehicles(day_records, name_map, min_km)
        if not moved:
            idle_days += 1
            continue
        for tid in moved:
            if time.monotonic() >= deadline:
                stopped = True
                break
            if (str(tid), ds) in present:
                skipped_present += 1
                continue
            limiter.acquire()               # бережная пауза (поверх аккаунт-лимитера клиента)
            try:
                raw = client.get_track(str(tid), ReportPeriod(
                    start=datetime.fromtimestamp(ds, timezone.utc),
                    end=datetime.fromtimestamp(de, timezone.utc)))
            except Exception:               # noqa: BLE001 — сбой одного ТС не валит бэкфилл
                raw = []
            norm = _normalize(raw)
            raw_store.upsert_track(str(tid), ds, norm, path=raw_path)  # чекпоинт (даже пустой)
            present.add((str(tid), ds))
            pulled += 1
        progress(2 + 96.0 * (di + 1) / len(day_starts),
                 f"Дни {di + 1}/{len(day_starts)} · треков добрано {pulled}")
        if stopped:
            break

    cov = raw_store.track_coverage(raw_path)
    msg = ("слайс завершён по таймауту — остаток добёрет следующий запуск"
           if stopped else "бэкфилл за окно завершён")
    progress(100, f"Готово: {pulled} треков, {msg}")
    return {"pulled": pulled, "skipped_present": skipped_present,
            "idle_days": idle_days, "no_aggregate_days": no_aggregate_days,
            "stopped_by_cap": stopped, "coverage": cov}
