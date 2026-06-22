"""Health-check service-учётки Omnicomm (Фаза 4).

Учётке могут молча урезать права (каталог отчётов уже отдаёт `permissions`,
часть отчётов — 404). Этот модуль проверяет доступность ключевых эндпоинтов на
старте прогона и сигналит, если набор прав изменился. Read-only.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from .models import ReportPeriod


@dataclass
class AccountHealth:
    login: bool = False
    checks: dict = field(default_factory=dict)   # capability -> (ok, note)
    sample_terminal: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.login and all(v[0] for v in self.checks.values())

    def summary(self) -> str:
        bad = [k for k, v in self.checks.items() if not v[0]]
        return ("учётка ОК, все ключевые эндпоинты доступны" if self.ok else
                f"проблемы доступа: {', '.join(bad) or 'логин'}")


def check(client) -> AccountHealth:
    """Проверить доступ к ключевым эндпоинтам. Не валит прогон — собирает статусы."""
    h = AccountHealth()
    try:
        client.login()
        h.login = True
    except Exception as e:                       # noqa: BLE001
        h.checks["login"] = (False, repr(e)[:80])
        return h

    def probe(name, fn):
        try:
            fn()
            h.checks[name] = (True, "")
        except Exception as e:                   # noqa: BLE001
            h.checks[name] = (False, repr(e)[:80])

    vehicles = []

    def _tree():
        nonlocal vehicles
        vehicles = client.list_vehicles()
        if not vehicles:
            raise RuntimeError("пустое дерево ТС")

    probe("vehicle_tree", _tree)
    probe("activity", lambda: client.get_activity())

    if vehicles:
        tid = str(vehicles[0]["terminal_id"])
        h.sample_terminal = tid
        end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        period = ReportPeriod(start=end - timedelta(days=1), end=end)
        probe("consolidated", lambda: client.get_consolidated_report([tid], period))
        probe("track", lambda: client.get_track(tid, period))
        probe("journal", lambda: client.get_journal(
            tid, ReportPeriod(start=end - timedelta(hours=2), end=end),
            groups=["GENERAL"], columns=["EVENT_DATE", "U_BOARD"]))
    return h
