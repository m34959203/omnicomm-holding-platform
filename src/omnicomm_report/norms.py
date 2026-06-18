"""Нормы расхода по ТС и расчёт перерасхода/экономии (идея Антона/Дмитрия).

Клиент вводит норму один раз на каждую машину (по марке/модели двигателя):
  • l_100km — норма расхода в движении, л/100 км;
  • l_mh    — норма расхода на моточас работы стоя (спецоборудование), л/мч.
Нормы хранятся персистентно ПО КЛИЕНТУ (JSON), чтобы не вводить каждый раз —
это лёгкая «база» enter-once (переносится на сервер без изменения формата).

Модель списания (РК): ожидаемый расход = пробег·l_100km/100 + моточасы_стоя·l_mh.
Отклонение факт−норма: >0 перерасход (сигнал руководителю), <0 экономия.
Бизнес-инвариант: без нормы вывод о перерасходе НЕ делается.
"""

from __future__ import annotations

import json
import os
import re
from typing import Optional

from .models import VehicleMetrics

DEFAULT_NORMS_DIR = os.path.join("output", "norms")


def _slug(client_name: str) -> str:
    s = re.sub(r"\s+", "_", (client_name or "client").strip().lower())
    return re.sub(r"[^\w\-]", "", s, flags=re.UNICODE) or "client"


def load_norms(client_name: str, norms_dir: str = DEFAULT_NORMS_DIR) -> dict[str, dict]:
    """Вернуть нормы клиента: {имя_ТС: {engine, l_100km, l_mh}}; {} если нет."""
    path = os.path.join(norms_dir, f"{_slug(client_name)}.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data.get("vehicles", {}) if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_norms(client_name: str, vehicles: dict[str, dict],
               norms_dir: str = DEFAULT_NORMS_DIR) -> str:
    """Сохранить нормы клиента. vehicles: {имя_ТС: {engine, l_100km, l_mh}}."""
    os.makedirs(norms_dir, exist_ok=True)
    path = os.path.join(norms_dir, f"{_slug(client_name)}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"client": client_name, "vehicles": vehicles}, fh,
                  ensure_ascii=False, indent=1)
    return path


def _num(v) -> Optional[float]:
    try:
        f = float(v)
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def apply_and_compute(
    vehicles: list[VehicleMetrics],
    norms: dict[str, dict],
    fuel_price_kzt: float = 0.0,
    extra_coeff: float = 1.0,
) -> None:
    """Привязать нормы к ТС (по имени) и посчитать перерасход/экономию.

    Заполняет у каждого ТС: norm_*, overrun_basis, overrun_l, overrun_cost_kzt.
    Без нормы — поля остаются None (перерасход не утверждаем).

    :param extra_coeff: общий множитель к норме (напр. зимний +10%) поверх
                        персонального коэффициента ТС. Влияет на сумму в ₸.
    """
    for vm in vehicles:
        if not vm.has_data:
            continue
        n = norms.get(vm.name)
        if not n:
            continue
        # Паспорт техники (статичные данные).
        vm.vehicle_type = n.get("type") or vm.vehicle_type
        vm.brand = n.get("brand") or vm.brand
        vm.model = n.get("model") or vm.model
        vm.reg_number = n.get("reg_number") or vm.reg_number
        try:
            vm.year = int(n["year"]) if n.get("year") else vm.year
        except (TypeError, ValueError):
            pass
        vm.tank_capacity_l = _num(n.get("tank")) or vm.tank_capacity_l
        vm.engine_model = n.get("engine") or vm.engine_model
        # Нормы расхода + коэффициент (зима/свалка/город/износ).
        vm.norm_l_per_100km = _num(n.get("l_100km"))
        vm.norm_l_per_mh = _num(n.get("l_mh"))
        try:
            base = float(n.get("coeff")) if n.get("coeff") else 1.0
        except (TypeError, ValueError):
            base = 1.0
        # эффективный коэффициент = персональный (свалка/город/износ) × сезонный
        vm.norm_coeff = round(base * (extra_coeff or 1.0), 4)
        _compute_overrun(vm, fuel_price_kzt)


def _compute_overrun(vm: VehicleMetrics, fuel_price_kzt: float) -> None:
    """Посчитать отклонение факт−норма по доступным нормам ТС."""
    n100, nmh = vm.norm_l_per_100km, vm.norm_l_per_mh
    mileage = vm.mileage_km or 0.0
    # Нулевой расход при заметной активности = молчащий ДУТ, а не экономия:
    # вердикт по норме не выносим, иначе фиктивная «экономия» −500 л на ТС
    # с неработающим датчиком искажает сальдо парка.
    if (not vm.fuel_l) and (mileage > 10 or (vm.engine_hours or 0) > 1):
        return
    # моточасы работы стоя как база для нормы на моточас (работа спецоборудования)
    stat_h = vm.work_no_move_hours if vm.work_no_move_hours is not None else (vm.engine_idle_hours or 0.0)
    eng_h = vm.engine_hours or 0.0

    overrun: Optional[float] = None
    basis: Optional[str] = None
    k = vm.norm_coeff or 1.0   # множитель к норме (зима/свалка/город/износ)

    if n100 and nmh:
        # полная модель списания: пробег + моточасы стоя (с коэффициентом)
        expected = (n100 * mileage / 100 + nmh * stat_h) * k
        if vm.fuel_l is not None:
            overrun = vm.fuel_l - expected
            basis = "combined"
    elif n100 and vm.fuel_per_100km_calc is not None and mileage > 0:
        overrun = (vm.fuel_per_100km_calc - n100 * k) * mileage / 100
        basis = "100km"
    elif nmh and vm.fuel_per_motorhour is not None and eng_h > 0:
        overrun = (vm.fuel_per_motorhour - nmh * k) * eng_h
        basis = "mh"

    if overrun is not None:
        vm.overrun_basis = basis
        vm.overrun_l = round(overrun, 1)
        if fuel_price_kzt and fuel_price_kzt > 0:
            vm.overrun_cost_kzt = round(overrun * fuel_price_kzt, 0)
