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

import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FTimeout, as_completed
from datetime import datetime, timezone
from typing import Callable, Optional

from omnicomm_report import config, data_loader, track_clean
from omnicomm_report.models import ReportPeriod
from omnicomm_report.rate_limit import AdaptiveRateLimiter, RateLimiter

from . import fleet_cache, raw_store
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
                       refresh_days: Optional[int] = None,
                       workers: Optional[int] = None,
                       adaptive: Optional[bool] = None,
                       raw_path: Optional[str] = None,
                       client=None, make_client=None,
                       name_map: Optional[dict] = None,
                       now: Optional[int] = None) -> dict:
    """Добрать треки за `days` суток в архив, бережно к Omnicomm. См. модуль-докстринг.

    ПРАВИЛО СВЕЖЕСТИ (зеркалит агрегаты, у которых `INGEST_WINDOW_DAYS` довозится
    каждый синк): текущий НЕЗАВЕРШЁННЫЙ день не архивируем (иначе заморозим частичный
    трек), последние `refresh_days` ЗАВЕРШЁННЫХ суток перезабираем даже если уже есть
    (поглощаем опоздавшие точки терминалов), старше — морозим (resume-skip).

    ПАРАЛЛЕЛИЗМ: фаза-1 локально отбирает юниты (ТС×сутки к забору), фаза-2 тянет их
    пулом из `workers` потоков (свой залогиненный клиент на поток). Общий `limiter`
    (`rate_per_min`) + аккаунт-лимитер клиента (170/мин) держат СУММАРНУЮ частоту всех
    потоков под потолком — воркеры лишь утилизируют его, перекрывая сетевую латентность.
    """
    days = days or config.TRACK_BACKFILL_DAYS
    min_km = config.TRACK_MIN_MILEAGE_KM if min_km is None else min_km
    rate_per_min = rate_per_min or config.TRACK_BACKFILL_RATE_PER_MIN
    # max_seconds=0 — легитимный «стоп сразу», поэтому именно None-проверка, не `or`.
    max_seconds = config.TRACK_BACKFILL_MAX_SECONDS if max_seconds is None else max_seconds
    refresh_days = config.INGEST_WINDOW_DAYS if refresh_days is None else refresh_days
    raw_path = raw_path or raw_store.DEFAULT_PATH
    now = int(now if now is not None else time.time())
    deadline = time.monotonic() + max_seconds
    adaptive = config.TRACK_ADAPTIVE if adaptive is None else adaptive
    # Адаптивный темп (AIMD по латентности копии) ИЛИ фиксированный потолок.
    if adaptive:
        limiter = AdaptiveRateLimiter(
            start=min(rate_per_min, config.TRACK_RATE_MAX), min_rate=config.TRACK_RATE_MIN,
            max_rate=config.TRACK_RATE_MAX, lat_low=config.TRACK_LATENCY_LOW,
            lat_high=config.TRACK_LATENCY_HIGH, adjust_every=config.TRACK_ADJUST_EVERY,
            ai_step=config.TRACK_AI_STEP)
    else:
        limiter = RateLimiter(rate_per_min)   # фиксированный потолок на все потоки

    # Фабрика клиента на поток. Если передан единичный `client` (тесты) — один поток.
    if make_client is None and client is None:
        make_client = _new_live_client
    if make_client is None:                       # back-compat: общий клиент → 1 поток
        make_client = lambda: client              # noqa: E731
        workers = 1
    workers = workers or config.TRACK_BACKFILL_WORKERS
    lister = client or make_client()
    if name_map is None:
        tree_vehicles = fleet_cache.list_vehicles(lister)
        name_map = {str(v.get("terminal_id") or v.get("id") or v.get("uuid")): v.get("name")
                    for v in tree_vehicles
                    if (v.get("terminal_id") or v.get("id") or v.get("uuid"))}

    today0 = _day_start(now)
    fresh_after = today0 - refresh_days * 86400   # ds≥fresh_after — свежий: перезабираем
    day_starts = [today0 - k * 86400 for k in range(days)]   # сегодня → назад в прошлое
    present = raw_store.tracks_present(day_starts[-1], today0 + 86400, raw_path)

    skipped_present = skipped_incomplete = idle_days = no_aggregate_days = 0
    stopped = False

    # ФАЗА 1 — локальный отбор юнитов (ТС×сутки) к забору (быстро, без сети).
    units: list[tuple] = []                       # (tid, ds, here)
    progress(2, f"Отбор суток с движением: окно {days} сут")
    for ds in day_starts:
        de = ds + 86400
        if de > now:                              # текущий неполный день — не морозим
            skipped_incomplete += 1
            continue
        day_records = raw_store.load_daily(ds, de - 1, raw_path)
        if not day_records:
            no_aggregate_days += 1                # нет агрегатов → движение неизвестно
            continue
        moved = _moved_vehicles(day_records, name_map, min_km)
        if not moved:
            idle_days += 1
            continue
        for tid in moved:
            here = (str(tid), ds) in present
            if here and ds < fresh_after:         # старый завершённый день — заморожен
                skipped_present += 1
                continue
            units.append((str(tid), ds, here))

    # ФАЗА 2 — параллельный забор под общим лимитером, запись в SQLite под локом.
    pulled = refreshed = 0
    write_lock = threading.Lock()
    counter_lock = threading.Lock()
    tls = threading.local()

    def _client():
        c = getattr(tls, "client", None)
        if c is None:
            c = make_client()
            tls.client = c
        return c

    def _work(unit):
        nonlocal pulled, refreshed
        tid, ds, here = unit
        if time.monotonic() >= deadline:          # после дедлайна — не дёргаем Omnicomm
            return False
        limiter.acquire()                          # темп (адаптивный/фиксированный)
        if time.monotonic() >= deadline:
            return False
        t0 = time.monotonic()
        ok = True
        try:
            raw = _client().get_track(str(tid), ReportPeriod(
                start=datetime.fromtimestamp(ds, timezone.utc),
                end=datetime.fromtimestamp(ds + 86400, timezone.utc)))
        except Exception:                          # noqa: BLE001 — сбой ТС не валит бэкфилл
            raw = []
            ok = False
        if adaptive:                               # сигнал здоровья: латентность+ошибка → AIMD
            limiter.record(time.monotonic() - t0, ok)
        norm = _normalize(raw)
        with write_lock:
            raw_store.upsert_track(str(tid), ds, norm, path=raw_path)  # чекпоинт (даже пустой)
        with counter_lock:
            if here:
                refreshed += 1                     # свежий день перезабрали
            else:
                pulled += 1
        return True

    total = len(units)
    mode = (f"адаптивный {config.TRACK_RATE_MIN:.0f}-{config.TRACK_RATE_MAX:.0f}/мин"
            if adaptive else f"фикс {rate_per_min:.0f}/мин")
    progress(4, f"Забор треков: {total} ТС×сутки, {workers} воркеров, темп {mode}")
    if total and max_seconds > 0:
        ex = ThreadPoolExecutor(max_workers=max(1, min(workers, total)))
        futures = [ex.submit(_work, u) for u in units]
        try:
            done = 0
            for fut in as_completed(futures, timeout=max_seconds):
                fut.result()
                done += 1
                if done % 200 == 0 or done == total:
                    cur = f" · темп {limiter.rate:.0f}/мин" if adaptive else ""
                    progress(4 + 94.0 * done / total,
                             f"Треки {done}/{total} · новых {pulled} (+{refreshed} обновл.){cur}")
        except FTimeout:
            stopped = True
        finally:
            ex.shutdown(wait=False, cancel_futures=True)
    elif max_seconds <= 0:
        stopped = True

    cov = raw_store.track_coverage(raw_path)
    msg = ("слайс завершён по таймауту — остаток добёрет следующий запуск"
           if stopped else "бэкфилл за окно завершён")
    progress(100, f"Готово: {pulled} новых треков (+{refreshed} обновлено), {msg}")
    return {"pulled": pulled, "refreshed": refreshed, "skipped_present": skipped_present,
            "skipped_incomplete": skipped_incomplete, "idle_days": idle_days,
            "no_aggregate_days": no_aggregate_days, "stopped_by_cap": stopped,
            "units": total, "coverage": cov}
