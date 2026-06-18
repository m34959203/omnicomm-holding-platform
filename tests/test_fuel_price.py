"""Тест парсера цены ГСМ (логика пар + сверка), без сети."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from omnicomm_report import fuel_price as fp  # noqa: E402

# Реальные координаты блока Алматы (y, x, text) с royal-petrol.kz.
ELEMENTS = [
    (292, 271, "98"), (292, 373, "365"),
    (344, 271, "95"), (344, 374, "322"),
    (397, 271, "92"), (397, 374, "245"),
    (449, 270, "ДТ*"),                       # зимний ДТ — без цены (не сезон)
    (503, 269, "ДТ"), (503, 374, "341"),     # летний ДТ = 341
    (556, 381, "112"), (557, 243, "АвтоГаз"),
]


def test_pair_prices_diesel_summer():
    prices = fp.pair_prices(ELEMENTS)
    assert prices["diesel_summer"] == 341.0
    assert prices["ai98"] == 365.0
    assert prices["ai92"] == 245.0
    assert prices["gas"] == 112.0
    # зимний ДТ без цены рядом — не должен ошибочно подхватить чужую
    assert prices.get("diesel_winter") is None


def test_classify_diesel_season():
    assert fp._classify_diesel("ДТ") == "diesel_summer"
    assert fp._classify_diesel("ДТ*") == "diesel_winter"
    assert fp._classify_diesel("ДТ(зима)") == "diesel_winter"
    assert fp._classify_diesel("АИ-92") is None


def test_check_price_within_and_deviation():
    assert fp.check_price(320, 341)["ok"] is True
    bad = fp.check_price(200, 341)
    assert bad["ok"] is False
    assert "ниже" in bad["message"]
    high = fp.check_price(450, 341)
    assert high["ok"] is False and "выше" in high["message"]
    # нет эталона → сверка пропускается, не падаем
    assert fp.check_price(320, None)["ok"] is True
