"""Тест health-gate копии Omnicomm (проба login+дерево+сводный перед слайсом)."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from api import fleet_cache, health_gate  # noqa: E402


class FakeClient:
    def __init__(self, *, login_ok=True, tree_vehicles=12,
                 tree_raises=False, cons_raises=False):
        self.login_ok = login_ok
        self.tree_vehicles = tree_vehicles
        self.tree_raises = tree_raises
        self.cons_raises = cons_raises

    def login(self):
        if not self.login_ok:
            raise RuntimeError("no auth")

    def get_vehicle_tree(self, timeout=None, max_retries=None):
        if self.tree_raises:
            raise TimeoutError("tree timeout")
        return [{"objects": [{"terminal_id": str(i), "name": f"V{i}"}
                             for i in range(self.tree_vehicles)]}]

    def get_consolidated_report(self, ids, period):
        if self.cons_raises:
            raise RuntimeError("404 Not Found")
        return [{"consolidatedReport": {"vehicleId": i, "date": 0}} for i in ids]


def test_probe_healthy_primes_cache():
    fleet_cache.clear()
    r = health_gate.probe(client=FakeClient())
    assert r["ok"] is True and r["reason"] == "healthy"
    assert r["tree_vehicles"] == 12
    # кэш прогрет → слайс не будет тянуть дерево снова (client=None: только из кэша)
    assert len(fleet_cache.list_vehicles(None, ttl=100)) == 12


def test_probe_tree_degraded():
    fleet_cache.clear()
    r = health_gate.probe(client=FakeClient(tree_raises=True))
    assert r["ok"] is False and r["reason"].startswith("tree")


def test_probe_tree_almost_empty():
    fleet_cache.clear()
    r = health_gate.probe(client=FakeClient(tree_vehicles=2))   # огрызок = деградация
    assert r["ok"] is False and "пуст" in r["reason"]


def test_probe_login_fail():
    fleet_cache.clear()
    r = health_gate.probe(client=FakeClient(login_ok=False))
    assert r["ok"] is False and r["reason"].startswith("login")


def test_probe_consolidated_fail():
    fleet_cache.clear()
    r = health_gate.probe(client=FakeClient(cons_raises=True))
    assert r["ok"] is False and r["reason"].startswith("consolidated")
