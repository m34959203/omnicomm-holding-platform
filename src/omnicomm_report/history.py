"""Хранилище снапшотов KPI для трендов период-к-периоду (P2).

БД в проекте нет — храним лёгкие JSON-снапшоты в каталоге (по клиенту).
Каждый снапшот: период + dict KPI. `load_previous` берёт самый свежий снапшот
строго раньше текущего периода, чтобы сравнивать «этот период vs прошлый».

Секретов здесь нет — только агрегаты. Каталог по умолчанию — `output/history`.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, fields
from typing import Optional

from .models import FleetKPI, FleetReport, ReportPeriod

DEFAULT_HISTORY_DIR = os.path.join("output", "history")


def _slug(client_name: str) -> str:
    """Безопасное имя файла из названия клиента."""
    s = re.sub(r"\s+", "_", (client_name or "client").strip().lower())
    s = re.sub(r"[^\w\-]", "", s, flags=re.UNICODE)
    return s or "client"


def _kpi_from_dict(data: dict) -> FleetKPI:
    """Восстановить FleetKPI из dict, игнорируя незнакомые/отсутствующие поля."""
    known = {f.name for f in fields(FleetKPI)}
    return FleetKPI(**{k: v for k, v in data.items() if k in known})


def save_snapshot(report: FleetReport, history_dir: str = DEFAULT_HISTORY_DIR) -> str:
    """Сохранить KPI отчёта снапшотом. Возвращает путь к файлу.

    Имя файла: `<client>__<start>_<end>.json` — идемпотентно для одного периода.
    """
    os.makedirs(history_dir, exist_ok=True)
    p = report.period
    fname = f"{_slug(report.client_name)}__{p.start:%Y%m%d}_{p.end:%Y%m%d}.json"
    path = os.path.join(history_dir, fname)
    payload = {
        "client_name": report.client_name,
        "period_start": int(p.start_ts),
        "period_end": int(p.end_ts),
        "kpi": asdict(report.kpi),
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
    return path


def load_previous(
    client_name: str,
    period: ReportPeriod,
    history_dir: str = DEFAULT_HISTORY_DIR,
) -> Optional[FleetKPI]:
    """Вернуть KPI самого свежего снапшота клиента строго раньше `period`.

    None — если истории нет. Сопоставление по `client_name` и `period_end`
    меньше начала текущего периода (чтобы не сравнивать период сам с собой).
    """
    if not os.path.isdir(history_dir):
        return None
    slug = _slug(client_name)
    cur_span = max(1, int(period.end_ts) - int(period.start_ts))
    best: Optional[tuple[int, FleetKPI]] = None
    for name in os.listdir(history_dir):
        if not name.startswith(slug + "__") or not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(history_dir, name), encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        end = int(data.get("period_end", 0))
        if end >= int(period.start_ts):  # пересекается с текущим или позже
            continue
        # Сопоставимость периодов: тренд «12 дней vs месяц» даёт бессмысленные
        # ▼60%. Сравниваем только периоды близкой длительности (×1.75 макс).
        span = max(1, end - int(data.get("period_start", 0)))
        if max(cur_span, span) / min(cur_span, span) > 1.75:
            continue
        if best is None or end > best[0]:
            best = (end, _kpi_from_dict(data.get("kpi", {})))
    return best[1] if best else None
