"""Health-gate копии Omnicomm: можно ли сейчас грузить бэкфилл?

Копя КАП деградирует под массовым забором (см. feedback): тяжёлые эндпоинты (дерево,
сводный) падают, login остаётся быстрым. Перед каждым слайсом бэкфилла дёргаем ЛЁГКУЮ
пробу: login + ОДНО дерево (быстрый отказ) + ОДИН маленький сводный. Здорова — слайсу
зелёный свет (и кэш дерева прогрет, чтобы слайс не тянул его снова); больна — слайс
пропускается, копю не долбим, ждём следующего окна."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional

from omnicomm_report.api_client import _flatten_vehicle_tree
from omnicomm_report.models import ReportPeriod

from . import fleet_cache

# Пороги «здоровья»: дерево должно ответить быстро и непусто, сводный — не упасть.
TREE_PROBE_TIMEOUT = 25      # сек на ОДНУ попытку дерева (быстрый отказ, не 120с×4)
TREE_MIN_VEHICLES = 10       # меньше — дерево пришло пустым/огрызком = деградация
SAMPLE_VEHICLES = 3          # сколько ТС берём в пробный сводный


def _new_client():
    from omnicomm_report.api_client import OmnicommClient
    from omnicomm_report.config import Settings
    return OmnicommClient(Settings.from_env())


def probe(client=None) -> dict:
    """Лёгкая проба копии. Возвращает {ok, login_s, tree_s, tree_vehicles,
    consolidated_s, reason}. При ok=True кэш дерева/ТС прогрет для слайса."""
    r = {"ok": False, "login_s": None, "tree_s": None, "tree_vehicles": 0,
         "consolidated_s": None, "reason": ""}
    c = client or _new_client()

    t = time.monotonic()
    try:
        c.login()
    except Exception as e:  # noqa: BLE001
        r["reason"] = f"login: {type(e).__name__}"
        return r
    r["login_s"] = round(time.monotonic() - t, 2)

    t = time.monotonic()
    try:                                    # дерево — быстрый отказ (1 попытка, короткий таймаут)
        tree = c.get_vehicle_tree(timeout=TREE_PROBE_TIMEOUT, max_retries=1)
    except Exception as e:  # noqa: BLE001
        r["tree_s"] = round(time.monotonic() - t, 2)
        r["reason"] = f"tree: {type(e).__name__}"
        return r
    r["tree_s"] = round(time.monotonic() - t, 2)
    vehs = _flatten_vehicle_tree(tree)
    r["tree_vehicles"] = len(vehs)
    if len(vehs) < TREE_MIN_VEHICLES:       # огрызок дерева = деградация (как 24.06)
        r["reason"] = f"дерево почти пусто ({len(vehs)} ТС)"
        return r

    ids = [str(v.get("terminal_id") or v.get("id")) for v in vehs[:SAMPLE_VEHICLES]
           if (v.get("terminal_id") or v.get("id"))]
    now = int(time.time())
    per = ReportPeriod(start=datetime.fromtimestamp(now - 3 * 86400, timezone.utc),
                       end=datetime.fromtimestamp(now, timezone.utc))
    t = time.monotonic()
    try:                                    # маленький сводный — тот эндпоинт, что падал 25.06
        c.get_consolidated_report(ids, per)
    except Exception as e:  # noqa: BLE001
        r["consolidated_s"] = round(time.monotonic() - t, 2)
        r["reason"] = f"consolidated: {type(e).__name__}"
        return r
    r["consolidated_s"] = round(time.monotonic() - t, 2)

    fleet_cache.prime(tree, vehs)           # прогрет → слайс не тянет дерево снова
    r["ok"] = True
    r["reason"] = "healthy"
    return r
