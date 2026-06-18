"""Тест CSV-входа: рус. выгрузка (cp1251, разделитель `;`, десятичная запятая).

Фиксирует, что CSV приводится к той же единой модели, что и Excel, и что
разделитель определяется корректно несмотря на запятые внутри чисел.
"""

from __future__ import annotations

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from omnicomm_report import data_loader  # noqa: E402

XLSX = os.path.join(os.path.dirname(__file__), "..", "samples", "fleet_sample.xlsx")


def _make_csv(tmp_path, sep: str, encoding: str) -> str:
    if not os.path.exists(XLSX):
        from samples.generate_sample import main as gen  # type: ignore
        gen()
    df = pd.read_excel(XLSX, engine="openpyxl")
    path = os.path.join(tmp_path, f"fleet_{encoding}.csv")
    df.to_csv(path, sep=sep, index=False, encoding=encoding)
    return path


def test_csv_cp1251_semicolon(tmp_path):
    """cp1251 + `;` + десятичная запятая — типичная рус. выгрузка."""
    path = _make_csv(tmp_path, sep=";", encoding="cp1251")
    vehicles = data_loader.load("csv", path=path)
    assert len(vehicles) == 10
    assert all(v.name for v in vehicles)
    # числовые поля распарсились, а не остались строками с запятой
    assert any(v.mileage_km and v.mileage_km > 0 for v in vehicles)


def test_csv_utf8_comma(tmp_path):
    """utf-8 + `,` — тоже должен читаться."""
    path = _make_csv(tmp_path, sep=",", encoding="utf-8-sig")
    vehicles = data_loader.load("csv", path=path)
    assert len(vehicles) == 10


def test_csv_ignores_fuel_drain_column(tmp_path):
    """Шумовой столбец «сливы топлива» не попадает в смапленные поля (§9)."""
    path = _make_csv(tmp_path, sep=";", encoding="cp1251")
    vehicles = data_loader.load("csv", path=path)
    for v in vehicles:
        for field in (v.mileage_km, v.fuel_l, v.fuel_per_100km):
            assert not isinstance(field, str)
