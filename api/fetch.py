"""Параллельный забор consolidatedReport — лекарство от 5-минутного ожидания.

`_report_post` тянет ~40 батчей (≤50 ТС) ПОСЛЕДОВАТЕЛЬНО, каждый ~5–7с +
throttle → ~5 мин на парк КАП. Здесь те же батчи идут КОНКУРЕНТНО: пул потоков,
у каждого потока — свой залогиненный клиент (своя сессия/токен, throttle не
шарится). Под лимит Omnicomm (180 запросов/мин/польз.): запросы длинные (~6с),
6 воркеров → ~1 старт/с ≪ 3/с. Итог: ~5 мин → ~40–60с.

Отдаёт тот же `payload` (items[]), что и `get_consolidated_report`, поэтому
агрегация переиспользует `data_loader._extract_records/_aggregate_consolidated`.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FTimeout, as_completed
from datetime import timedelta
from typing import Callable, Optional

from omnicomm_report import config
from omnicomm_report.api_client import MAX_VEHICLES_PER_REPORT
from omnicomm_report.models import ReportPeriod

ProgressCb = Callable[[float, str], None]
MakeClient = Callable[[], object]   # фабрика залогиненного клиента (по потоку)


def _chunks(items: list, size: int) -> list[list]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def _time_windows(period, window_days: Optional[int]) -> list:
    """Нарезать период на окна по window_days суток (чанкинг по времени).

    Без чанкинга (window_days falsy) — одно окно = весь период. Маленькие окна
    делают каждый запрос быстрым (≤window_days × ≤50 ТС) → нет зависаний на
    длинных периодах, прогресс двигается по каждому окну.
    """
    if not window_days or window_days <= 0:
        return [period]
    out, cur, step = [], period.start, timedelta(days=window_days)
    while cur < period.end:
        nxt = min(cur + step, period.end)
        out.append(ReportPeriod(start=cur, end=nxt))
        cur = nxt
    return out or [period]


def fetch_report_parallel(make_client: MakeClient, vehicle_ids: list[str], period,
                          *, call, label: str, workers: int = 6,
                          progress: Optional[ProgressCb] = None,
                          pct_from: float = 0.0, pct_to: float = 100.0,
                          best_effort: bool = False,
                          max_seconds: Optional[float] = None,
                          window_days: Optional[int] = None) -> list[dict]:
    """Собрать любой батч-отчёт по всем ТС конкурентно. `payload` (items[]).

    `call(client, chunk, period) -> list` — конкретный вызов отчёта. Один поток =
    один клиент (thread-local). РАБОЧАЯ ЕДИНИЦА = (батч ТС × окно времени): при
    `window_days` длинный период режется на окна, каждое окно — отдельный быстрый
    запрос, прогресс по каждому. `best_effort=True` — упавшая единица даёт [].
    `max_seconds` — wall-clock-кап: по истечении отдаём собранное, зависшее бросаем.
    """
    chunks = _chunks(list(vehicle_ids), MAX_VEHICLES_PER_REPORT)
    if not chunks:
        return []
    windows = _time_windows(period, window_days)
    units = [(chunk, win) for chunk in chunks for win in windows]

    tls = threading.local()

    def client_for_thread():
        c = getattr(tls, "client", None)
        if c is None:
            c = make_client()
            tls.client = c
        return c

    def work(unit) -> list[dict]:
        chunk, win = unit
        try:
            return call(client_for_thread(), chunk, win) or []
        except Exception:  # noqa: BLE001
            if best_effort:
                return []
            raise

    payload: list[dict] = []
    done = 0
    lock = threading.Lock()
    total = len(units)
    span = max(pct_to - pct_from, 0.0)

    ex = ThreadPoolExecutor(max_workers=max(1, min(workers, total)))
    futures = [ex.submit(work, u) for u in units]
    try:
        for fut in as_completed(futures, timeout=max_seconds):
            res = fut.result()
            with lock:
                payload.extend(res)
                done += 1
                if progress:
                    progress(pct_from + span * done / total,
                             f"{label}: {done}/{total} запросов")
    except FTimeout:
        # кап исчерпан — отдаём частичный результат, зависшие единицы бросаем
        if progress:
            progress(pct_to, f"{label}: {done}/{total} (по таймауту, частично)")
    finally:
        # не ждём зависшие единицы (они дойдут в фоне и осядут вхолостую)
        ex.shutdown(wait=False, cancel_futures=True)
    return payload


def fetch_consolidated_parallel(make_client: MakeClient, vehicle_ids: list[str],
                                period, *, workers: int = 6,
                                progress: Optional[ProgressCb] = None,
                                pct_from: float = 0.0, pct_to: float = 100.0
                                ) -> list[dict]:
    """Параллельный consolidatedReport (тонкая обёртка над fetch_report_parallel)."""
    return fetch_report_parallel(
        make_client, vehicle_ids, period,
        call=lambda c, ch, p: c.get_consolidated_report(ch, p),
        label="Загрузка телеметрии", workers=workers, progress=progress,
        pct_from=pct_from, pct_to=pct_to)
