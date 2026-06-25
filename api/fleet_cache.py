"""Процессный кэш дерева ТС / списка ТС: один забор на TTL, single-flight.

Урок 24.06: тяжёлый эндпоинт `vehicle_tree` (~2000 ТС) забирался В КАЖДОЙ из ~24
задач помесячного бэкфилла (агрегаты+треки) и всеми воркерами пула одновременно —
это деградировало копию Omnicomm (дерево уходило в таймаут). Здесь дерево/список ТС
забираются ОДИН раз на TTL и переиспользуются всеми задачами/потоками; single-flight
не даёт пулу воркеров ударить тяжёлым деревом разом (thundering herd)."""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Optional

from omnicomm_report import config

_lock = threading.Lock()
_cache: dict[str, tuple[float, Any]] = {}
_build_locks: dict[str, threading.Lock] = {}


def _cached(key: str, ttl: float, build: Callable[[], Any]) -> Any:
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
        blk = _build_locks.setdefault(key, threading.Lock())
    with blk:                                    # single-flight: строит ОДИН поток
        with _lock:                              # перепроверка после ожидания лока
            hit = _cache.get(key)
            if hit and time.monotonic() - hit[0] < ttl:
                return hit[1]
        val = build()                            # тяжёлый забор — вне общего лока
        with _lock:
            _cache[key] = (time.monotonic(), val)
        return val


def vehicle_tree(client, ttl: Optional[float] = None) -> Any:
    """Сырое дерево ТС из кэша (один забор на TTL на весь процесс)."""
    ttl = config.FLEET_CACHE_TTL if ttl is None else ttl
    return _cached("tree", ttl, client.get_vehicle_tree)


def list_vehicles(client, ttl: Optional[float] = None) -> list:
    """Плоский список ТС из кэша (один забор на TTL на весь процесс)."""
    ttl = config.FLEET_CACHE_TTL if ttl is None else ttl
    return _cached("vehicles", ttl, lambda: client.list_vehicles() or [])


def clear() -> None:
    """Сбросить кэш (напр. при смене учётки)."""
    with _lock:
        _cache.clear()
