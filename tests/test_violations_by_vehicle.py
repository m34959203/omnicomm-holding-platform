"""Тест агрегата by_vehicle в violations-detail (для клика по «Тяжести»)."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api import raw_store, violations_detail as vd  # noqa: E402


def _visit(tid, name, veh, maxspeed, start):
    # geozone_limit парсит лимит из имени зоны («… 50 км/ч»); превышение = maxSpeed − лимит.
    return {"vehicleId": tid, "vehicleName": veh, "geozoneName": name,
            "mv": {"maxSpeed": maxspeed, "mileage": 5.0, "averageSpeed": None},
            "geoInfo": {"startDate": start, "endDate": start + 600, "duration": 600}}


def test_by_vehicle_sums_match_severity(tmp_path):
    raw = str(tmp_path / "raw.db")
    base = 1_780_000_000
    # зона с лимитом 50: A превышает на 45 (95, →40+), B на 25 (75, →20–40), B на 10 (60, →6–20)
    visits = [
        _visit("A", "Зона огр 50 км/ч", "КрАЗ A", 95, base + 1),
        _visit("A", "Зона огр 50 км/ч", "КрАЗ A", 96, base + 2),   # ещё 40+
        _visit("B", "Зона огр 50 км/ч", "Prado B", 75, base + 3),  # 20–40
        _visit("B", "Зона огр 50 км/ч", "Prado B", 60, base + 4),  # 6–20
    ]
    raw_store.upsert_visits(visits, raw)
    r = vd.build_violations_detail(raw_path=raw,
                                   from_iso="2026-05-01", to_iso="2026-08-01")
    sev, bv = r["severity"], r["by_vehicle"]
    # инвариант: сумма by_vehicle по каждой корзине == severity (точно, до среза rows)
    for k in ("s6", "s20", "s40"):
        assert sum(v[k] for v in bv) == sev[k], k
    # клик по 40+ → только ТС A (2 нарушения)
    s40 = [v for v in bv if v["s40"] > 0]
    assert [v["vehicleId"] for v in s40] == ["A"]
    assert s40[0]["s40"] == 2 and s40[0]["vehicle"] == "КрАЗ A"
    # клик по 20–40 → только B (1)
    s20 = [v for v in bv if v["s20"] > 0]
    assert [v["vehicleId"] for v in s20] == ["B"] and s20[0]["s20"] == 1
    # порядок by_vehicle — по (s40, s20, total): A впереди B
    assert bv[0]["vehicleId"] == "A"
