"""Календарный учёт цены ГСМ: история изменений стоимости топлива по датам.

Хранит список «с даты X цена = Y ₸/л» (рыночная цена, общая для всех клиентов).
При расчёте за период система берёт цену КОНКРЕТНОГО ДНЯ и считает средневзвешенную
по дням цену периода — так корректно учитываются «взлёты и падения» (например, до
01.06 было 320 ₸, после — 340 ₸). Календарь ежедневно наполняет демон-планировщик
(`scheduler.snapshot_fuel_price`), парся цену Royal Petrol.

Файл `data/fuel_prices.json` (gitignored). Запись: {"date":"YYYY-MM-DD","price":340.0}.

Путь к файлу резолвится при ВЫЗОВЕ (None → DEFAULT_PATH) — это позволяет
переопределять его в тестах через monkeypatch DEFAULT_PATH.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from typing import Optional

DEFAULT_PATH = os.path.join("data", "fuel_prices.json")


def _p(path: Optional[str]) -> str:
    return path or DEFAULT_PATH


def _parse(d) -> Optional[date]:
    if isinstance(d, date):
        return d
    try:
        return datetime.strptime(str(d), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def load_history(path: Optional[str] = None) -> list[dict]:
    """Отсортированная по дате история цен: [{date:'YYYY-MM-DD', price: float}]."""
    path = _p(path)
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return []
    out = []
    for e in data or []:
        d = _parse(e.get("date"))
        try:
            pr = float(e.get("price"))
        except (TypeError, ValueError):
            continue
        if d and pr > 0:
            out.append({"date": d.isoformat(), "price": round(pr, 2)})
    out.sort(key=lambda e: e["date"])
    return out


def save_history(entries: list[dict], path: Optional[str] = None) -> str:
    """Сохранить историю (нормализованную и отсортированную)."""
    path = _p(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    clean = []
    for e in entries or []:
        d = _parse(e.get("date"))
        try:
            pr = float(e.get("price"))
        except (TypeError, ValueError):
            continue
        if d and pr > 0:
            clean.append({"date": d.isoformat(), "price": round(pr, 2)})
    clean.sort(key=lambda e: e["date"])
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(clean, fh, ensure_ascii=False, indent=1)
    return path


def add_price(on_date, price: float, path: Optional[str] = None) -> list[dict]:
    """Добавить/обновить цену, действующую С указанной даты. Возвращает историю."""
    path = _p(path)
    d = _parse(on_date)
    if not d or not price or price <= 0:
        return load_history(path)
    hist = [e for e in load_history(path) if e["date"] != d.isoformat()]
    hist.append({"date": d.isoformat(), "price": round(float(price), 2)})
    save_history(hist, path)
    return load_history(path)


def price_on(day, path_or_history=None) -> Optional[float]:
    """Цена, действующая на конкретный день (последняя запись с датой ≤ day).

    Второй аргумент — путь к файлу (None → DEFAULT_PATH) или уже загруженная история.
    """
    hist = path_or_history if isinstance(path_or_history, list) else load_history(path_or_history)
    d = _parse(day)
    if not d or not hist:
        return None
    eff = None
    for e in hist:                       # история отсортирована по возрастанию
        if e["date"] <= d.isoformat():
            eff = e["price"]
        else:
            break
    return eff


def effective_price(start, end, path: Optional[str] = None) -> Optional[float]:
    """Средневзвешенная по дням цена за период [start..end], ₸/л.

    Для каждого дня берём цену этого дня (price_on) и усредняем по числу дней —
    так «взлёты и падения» внутри периода учитываются пропорционально дням.
    None, если на период нет ни одной известной цены.
    """
    hist = load_history(path)
    s, e = _parse(start), _parse(end)
    if not hist or not s or not e or e < s:
        return None
    total = 0.0
    days = 0
    covered = 0
    cur = s
    while cur <= e:
        pr = price_on(cur, hist)
        if pr is not None:
            total += pr
            covered += 1
        days += 1
        cur += timedelta(days=1)
        if days > 1000:                  # предохранитель
            break
    if covered == 0:
        return None
    return round(total / covered, 2)


def has_history(path: Optional[str] = None) -> bool:
    return bool(load_history(path))


def price_for_period(manual_price: float, start, end,
                     path: Optional[str] = None) -> tuple[float, bool]:
    """Цена для расчёта за период: (цена ₸/л, blended).

    Если есть календарь цен, покрывающий период — возвращаем средневзвешенную по
    дням цену (blended=True). Иначе — ручную цену клиента (blended=False).
    """
    eff = effective_price(start, end, path)
    if eff is not None and eff > 0:
        return eff, True
    return float(manual_price or 0), False
