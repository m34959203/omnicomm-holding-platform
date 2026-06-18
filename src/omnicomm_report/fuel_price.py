"""Парсер цены ГСМ у поставщика (Royal Petrol, KZ) для сверки/автоподстановки.

Назначение:
  • получить эталонную цену дизеля (лето/зима) с сайта поставщика;
  • сверить с введённой вручную ценой и ПРЕДУПРЕДИТЬ при сильном отклонении;
  • при желании — подставить цену автоматически (с информированием).

Сайт — Tilda zero-block: метки топлива и цены лежат отдельными абсолютно-
позиционированными элементами; пара «метка↔цена» определяется по вертикали (y).
Логика пар вынесена в чистую `pair_prices` (тестируема без сети). Сама загрузка
страницы — через playwright (сайт отдаёт 403 на простой запрос). Результат
кэшируется в `data/` на несколько часов, чтобы не дёргать сайт каждый раз.
Сбой загрузки не критичен — возвращаем None.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Optional

ROYAL_PETROL_URL = "http://royal-petrol.kz/nashe-toplivo-i-ceny/ru"
CACHE_PATH = os.path.join("data", "fuel_price_cache.json")
CACHE_MAX_AGE_S = 6 * 3600          # обновлять не чаще раза в 6 часов
DEVIATION_WARN = 0.15               # отклонение >15% → предупредить

# Метки топлива на сайте → ключ.
_LABEL_MAP = {
    "98": "ai98", "95": "ai95", "92": "ai92", "автогаз": "gas",
}


def _classify_diesel(label: str) -> Optional[str]:
    """Метку дизеля → 'diesel_winter' | 'diesel_summer' | None."""
    low = label.lower().replace(" ", "")
    if "дт" not in low:
        return None
    # зима: явная пометка «зима» или звёздочка «ДТ*» (зимнее/несезонное)
    if "зима" in low or "*" in label:
        return "diesel_winter"
    return "diesel_summer"


def pair_prices(elements: list[tuple[float, float, str]],
                *, y_tol: float = 18.0, price_min_x: float = 340.0) -> dict[str, float]:
    """Сопоставить метки топлива с ценами по вертикали (чистая логика, тестируема).

    :param elements: список (y, x, text) видимых элементов одного блока цен.
    :returns: {ключ_топлива: цена}. Берётся первый (верхний) блок — по каждому
              ключу запоминается первое найденное значение.
    """
    labels: list[tuple[float, str]] = []   # (y, key)
    prices: list[tuple[float, float, float]] = []  # (y, x, value)
    for y, x, text in elements:
        t = text.strip()
        key = _LABEL_MAP.get(t.lower()) or _classify_diesel(t)
        if key:
            labels.append((y, key))
        elif re.fullmatch(r"\d{2,3}", t) and x >= price_min_x:
            prices.append((y, x, float(t)))

    out: dict[str, float] = {}
    used: set[int] = set()
    for ly, key in sorted(labels, key=lambda p: p[0]):
        if key in out:
            continue
        # ближайшая по вертикали цена в пределах допуска
        best = None
        for idx, (py, px, val) in enumerate(prices):
            if idx in used or abs(py - ly) > y_tol:
                continue
            if best is None or abs(py - ly) < abs(prices[best][0] - ly):
                best = idx
        if best is not None:
            used.add(best)
            out[key] = prices[best][2]
    return out


def fetch_reference(url: str = ROYAL_PETROL_URL) -> Optional[dict]:
    """Загрузить и распарсить цены с сайта поставщика (playwright). None при сбое."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(
                viewport={"width": 1400, "height": 2000},
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/120 Safari/537.36")
            pg.goto(url, timeout=45000, wait_until="networkidle")
            pg.wait_for_timeout(1500)
            els = pg.locator(".t396__elem")
            elements: list[tuple[float, float, str]] = []
            for i in range(min(els.count(), 400)):
                e = els.nth(i)
                try:
                    if not e.is_visible():
                        continue
                    txt = e.inner_text().strip()
                    if not txt or len(txt) > 14:
                        continue
                    bb = e.bounding_box()
                except Exception:  # noqa: BLE001
                    continue
                if bb:
                    elements.append((bb["y"], bb["x"], txt))
            b.close()
    except Exception:  # noqa: BLE001 — сеть/блокировка/таймаут не критичны
        return None

    prices = pair_prices(elements)
    if not prices:
        return None
    return {"prices": prices, "source": url, "fetched_at": int(time.time())}


def get_reference(season: str = "summer", *, cache_path: str = CACHE_PATH,
                  max_age_s: int = CACHE_MAX_AGE_S, force: bool = False
                  ) -> Optional[dict]:
    """Эталонная цена дизеля с кэшем. Возвращает dict или None.

    :param season: 'summer'|'winter' — какой дизель брать (чек-поинт вида ДТ).
    :returns: {'diesel': цена|None, 'season': ..., 'all': {...}, 'source', 'fetched_at', 'cached'}
    """
    data = None
    cached = False
    if not force and os.path.exists(cache_path):
        try:
            with open(cache_path, encoding="utf-8") as fh:
                c = json.load(fh)
            if int(time.time()) - int(c.get("fetched_at", 0)) <= max_age_s:
                data, cached = c, True
        except (OSError, ValueError):
            data = None
    if data is None:
        data = fetch_reference()
        if data is None:
            return None
        os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
        try:
            with open(cache_path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False)
        except OSError:
            pass

    prices = data.get("prices", {})
    key = "diesel_winter" if season == "winter" else "diesel_summer"
    diesel = prices.get(key)
    # запасной вариант: если выбранного сезона нет — берём любой дизель
    if diesel is None:
        diesel = prices.get("diesel_summer") or prices.get("diesel_winter")
    return {"diesel": diesel, "season": season, "all": prices,
            "source": data.get("source"), "fetched_at": data.get("fetched_at"),
            "cached": cached}


def check_price(manual: float, reference: Optional[float],
                tolerance: float = DEVIATION_WARN) -> dict:
    """Сверить ручную цену с эталонной. {ok, deviation, message}."""
    if not reference or reference <= 0 or not manual or manual <= 0:
        return {"ok": True, "deviation": None,
                "message": "Эталонная цена недоступна — сверка пропущена."}
    dev = (manual - reference) / reference
    if abs(dev) > tolerance:
        sign = "выше" if dev > 0 else "ниже"
        return {"ok": False, "deviation": dev,
                "message": (f"Указанная цена {manual:.0f} ₸/л на {abs(dev) * 100:.0f}% "
                            f"{sign} цены поставщика ({reference:.0f} ₸/л) — проверьте.")}
    return {"ok": True, "deviation": dev,
            "message": (f"Цена {manual:.0f} ₸/л в пределах нормы относительно "
                        f"поставщика ({reference:.0f} ₸/л).")}
