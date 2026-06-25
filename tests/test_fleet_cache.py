"""Тест процессного кэша дерева/списка ТС: один забор на TTL, single-flight."""

from __future__ import annotations

import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from api import fleet_cache  # noqa: E402


class Counter:
    """Клиент-счётчик: считает тяжёлые заборы, имитирует латентность."""

    def __init__(self):
        self.tree_calls = 0
        self.veh_calls = 0
        self._lock = threading.Lock()

    def get_vehicle_tree(self):
        with self._lock:
            self.tree_calls += 1
        time.sleep(0.05)              # имитация тяжёлого дерева
        return [{"root": 1}]

    def list_vehicles(self):
        with self._lock:
            self.veh_calls += 1
        return [{"id": 1}, {"id": 2}]


def test_single_flight_one_build_under_concurrency():
    fleet_cache.clear()
    c = Counter()
    results = []

    def worker():
        results.append(fleet_cache.vehicle_tree(c, ttl=100))

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert c.tree_calls == 1                 # 8 потоков — ОДИН забор тяжёлого дерева
    assert all(r == [{"root": 1}] for r in results)


def test_cache_hit_within_ttl():
    fleet_cache.clear()
    c = Counter()
    a = fleet_cache.list_vehicles(c, ttl=100)
    b = fleet_cache.list_vehicles(c, ttl=100)
    assert c.veh_calls == 1                   # второй вызов — из кэша
    assert a == b == [{"id": 1}, {"id": 2}]


def test_ttl_expiry_refetches():
    fleet_cache.clear()
    c = Counter()
    fleet_cache.vehicle_tree(c, ttl=0.0)      # ttl 0 → всегда свежий
    fleet_cache.vehicle_tree(c, ttl=0.0)
    assert c.tree_calls == 2
