"""Тесты счётчика подтверждённой экономии: baseline, расчёт, леджер, сезон."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from omnicomm_report import savings  # noqa: E402
from omnicomm_report.models import FleetKPI, FleetReport, ReportPeriod  # noqa: E402


def _period(d1: int = 1, d2: int = 30, month: int = 7):
    return ReportPeriod(start=datetime(2026, month, d1, tzinfo=timezone.utc),
                        end=datetime(2026, month, d2, tzinfo=timezone.utc))


def _baseline(idle_share=0.40, idle_rate=6.0, moving_rate=50.0, season="summer"):
    return {
        "client": "Тест", "frozen_at": "2026-06-01T00:00:00+00:00",
        "date_from": int(datetime(2026, 5, 1, tzinfo=timezone.utc).timestamp()),
        "date_to": int(datetime(2026, 5, 31, tzinfo=timezone.utc).timestamp()),
        "source_periods": 1, "season": season,
        "rates": {"idle_share": idle_share, "idle_rate_l_h": idle_rate,
                  "moving_l_per_100km": moving_rate},
    }


def _report(*, engine_h=1000.0, idle_fuel=2000.0, total_fuel=7000.0,
            mileage=10000.0, price=341.0, season="summer", month=7):
    kpi = FleetKPI(total_engine_hours=engine_h, fuel_idle_l=idle_fuel,
                   total_fuel_l=total_fuel, total_mileage_km=mileage,
                   fuel_price_kzt=price)
    rep = FleetReport(period=_period(month=month), client_name="Тест",
                      vehicles=[], kpi=kpi, season=season)
    rep.generated_at = datetime(2026, 8, 1, tzinfo=timezone.utc)
    return rep


def test_savings_positive_when_better_than_baseline():
    """Факт лучше эталона → положительная экономия по обеим компонентам."""
    # baseline: idle 40% × 1000 ч × 6 л/ч = 2400 л ожидание простоя;
    # движение 50 л/100км × 10 000 км = 5000 л ожидание.
    entry = savings.compute_savings(_report(idle_fuel=2000.0, total_fuel=6500.0),
                                    _baseline())
    assert entry is not None
    assert entry["components"]["idle"]["saved_l"] == 400.0       # 2400-2000
    assert entry["components"]["moving"]["saved_l"] == 500.0     # 5000-4500
    assert entry["saved_l"] == 900.0
    assert entry["saved_kzt"] == round(900.0 * 341.0)


def test_savings_negative_recorded_honestly():
    """Перерасход к эталону → отрицательная экономия, не зануляется."""
    entry = savings.compute_savings(
        _report(idle_fuel=3000.0, total_fuel=9000.0), _baseline())
    assert entry["saved_l"] < 0
    assert entry["saved_kzt"] < 0


def test_normalization_less_activity_is_not_savings():
    """Меньше ездили → ожидание пропорционально меньше, экономия ≈ 0."""
    # Половина активности при тех же ставках, что и baseline.
    entry = savings.compute_savings(
        _report(engine_h=500.0, idle_fuel=1200.0, total_fuel=3700.0,
                mileage=5000.0),
        _baseline())
    assert abs(entry["saved_l"]) < 1.0   # 1200 vs 1200, 2500 vs 2500


def test_season_factor_applied():
    """Baseline летний, период зимний → ожидание ×1.10 (норма РК)."""
    summer = savings.compute_savings(_report(season="summer"), _baseline())
    winter = savings.compute_savings(_report(season="winter", month=12),
                                     _baseline())
    assert winter["season_factor"] == 1.1
    assert winter["expected_l"] > summer["expected_l"]


def test_freeze_from_history_and_min_hours(tmp_path):
    """Заморозка из снапшотов: ставки из сумм; мало наработки → None."""
    hdir = tmp_path / "history"
    hdir.mkdir()
    snap = {
        "client_name": "Тест",
        "period_start": int(datetime(2026, 5, 1, tzinfo=timezone.utc).timestamp()),
        "period_end": int(datetime(2026, 5, 31, tzinfo=timezone.utc).timestamp()),
        "kpi": {"total_engine_hours": 1000.0, "total_idle_hours": 400.0,
                "total_fuel_l": 7000.0, "fuel_idle_l": 2400.0,
                "total_mileage_km": 10000.0},
    }
    (hdir / "тест__20260501_20260531.json").write_text(
        json.dumps(snap, ensure_ascii=False), encoding="utf-8")

    b = savings.freeze_from_history(
        "Тест", datetime(2026, 5, 1, tzinfo=timezone.utc),
        datetime(2026, 6, 1, tzinfo=timezone.utc),
        history_dir=str(hdir), baseline_dir=str(tmp_path / "baseline"))
    assert b is not None
    assert b["rates"]["idle_share"] == 0.4
    assert b["rates"]["idle_rate_l_h"] == 6.0
    assert b["rates"]["moving_l_per_100km"] == 46.0   # (7000-2400)/10000×100
    assert b["season"] == "summer"
    # Повторная загрузка с диска
    assert savings.load_baseline("Тест", str(tmp_path / "baseline")) is not None

    # Мало наработки → не замораживаем.
    snap["kpi"]["total_engine_hours"] = 10.0
    (hdir / "тест__20260501_20260531.json").write_text(
        json.dumps(snap, ensure_ascii=False), encoding="utf-8")
    assert savings.freeze_from_history(
        "Тест", datetime(2026, 5, 1, tzinfo=timezone.utc),
        datetime(2026, 6, 1, tzinfo=timezone.utc),
        history_dir=str(hdir), baseline_dir=str(tmp_path / "b2")) is None


def test_ledger_idempotent_and_cumulative(tmp_path):
    """Повторный прогон периода перезаписывает запись; накопление суммирует."""
    sdir = str(tmp_path / "savings")
    b = _baseline()
    e1 = {"period_start": 100, "period_end": 200, "saved_l": 10.0, "saved_kzt": 3410}
    e2 = {"period_start": 300, "period_end": 400, "saved_l": -5.0, "saved_kzt": -1705}
    savings.update_ledger("Тест", e1, b, sdir)
    savings.update_ledger("Тест", e2, b, sdir)
    # перезапись того же периода другим значением
    savings.update_ledger("Тест", {**e1, "saved_l": 20.0, "saved_kzt": 6820}, b, sdir)
    led = savings.load_ledger("Тест", sdir)
    assert len(led["entries"]) == 2
    cum_l, cum_kzt = savings.cumulative(led)
    assert cum_l == 15.0           # 20 + (-5)
    assert cum_kzt == 5115         # 6820 - 1705


def test_apply_to_report_skips_baseline_window(tmp_path):
    """Период внутри baseline-окна не пишется в счётчик (эталон ≠ факт)."""
    bdir, sdir = str(tmp_path / "b"), str(tmp_path / "s")
    os.makedirs(bdir)
    rep = _report(month=5)   # май = внутри baseline-окна (до date_to)
    with open(os.path.join(bdir, "тест.json"), "w", encoding="utf-8") as fh:
        json.dump(_baseline(), fh)
    assert savings.apply_to_report(rep, baseline_dir=bdir, savings_dir=sdir) is None

    rep2 = _report(month=7)  # июль = после baseline-окна
    res = savings.apply_to_report(rep2, baseline_dir=bdir, savings_dir=sdir)
    assert res is not None
    assert rep2.savings["entries_count"] == 1
    assert rep2.savings["series"]


def test_apply_without_baseline_is_noop(tmp_path):
    rep = _report()
    assert savings.apply_to_report(
        rep, baseline_dir=str(tmp_path / "none"),
        savings_dir=str(tmp_path / "s")) is None
    assert rep.savings == {}


def _baseline_v2():
    b = _baseline()
    b["schema"] = 2
    b["rates_v2"] = {
        "mobile": {"idle_share": 0.30, "idle_rate_l_h": 5.0,
                   "moving_l_per_100km": 40.0},
        "stationary": {"l_per_mh": 6.0},
    }
    return b


def test_savings_v2_three_components_class_split():
    """v2: классы раздельно — спецтехника по л/мч, мобильные idle+движение."""
    rep = _report()
    k = rep.kpi
    # мобильные: 600 мч (180 idle), 9000 км, 5000 л (900 idle);
    # спецтехника: 400 мч, 2300 л.
    k.mobile_engine_hours, k.mobile_idle_hours = 600.0, 180.0
    k.mobile_mileage_km = 9000.0
    k.mobile_fuel_l, k.mobile_fuel_idle_l = 5000.0, 900.0
    k.stationary_engine_hours, k.stationary_fuel_l = 400.0, 2300.0
    entry = savings.compute_savings(rep, _baseline_v2())
    assert entry["schema"] == 2
    comp = entry["components"]
    assert set(comp) == {"idle", "moving", "stationary"}
    # idle: ожидание 0.30×600×5.0=900 vs факт 900 → 0
    assert comp["idle"]["saved_l"] == 0.0
    # движение: 40×9000/100=3600 vs (5000-900)=4100 → −500
    assert comp["moving"]["saved_l"] == -500.0
    # спецтехника: 6.0×400=2400 vs 2300 → +100
    assert comp["stationary"]["saved_l"] == 100.0
    assert entry["saved_l"] == -400.0


def test_savings_v2_fleet_mix_does_not_distort():
    """Выпала спецтехника из работы → ожидание по ней падает, экономии нет."""
    rep = _report()
    k = rep.kpi
    k.mobile_engine_hours, k.mobile_idle_hours = 600.0, 180.0
    k.mobile_mileage_km = 9000.0
    k.mobile_fuel_l, k.mobile_fuel_idle_l = 4500.0, 900.0
    k.stationary_engine_hours, k.stationary_fuel_l = 0.0, 0.0   # не работала
    entry = savings.compute_savings(rep, _baseline_v2())
    assert entry["components"]["stationary"]["expected_l"] == 0.0
    assert entry["components"]["stationary"]["saved_l"] == 0.0


def test_freeze_v2_rates_from_class_sums(tmp_path):
    """Снапшоты со срезами по классам → baseline schema 2 со ставками классов."""
    hdir = tmp_path / "history"
    hdir.mkdir()
    snap = {
        "client_name": "Тест",
        "period_start": int(datetime(2026, 5, 1, tzinfo=timezone.utc).timestamp()),
        "period_end": int(datetime(2026, 5, 31, tzinfo=timezone.utc).timestamp()),
        "kpi": {"total_engine_hours": 1000.0, "total_idle_hours": 400.0,
                "total_fuel_l": 7000.0, "fuel_idle_l": 2400.0,
                "total_mileage_km": 10000.0,
                "mobile_fuel_l": 5000.0, "mobile_fuel_idle_l": 1500.0,
                "mobile_engine_hours": 600.0, "mobile_idle_hours": 300.0,
                "mobile_mileage_km": 10000.0,
                "stationary_fuel_l": 2000.0, "stationary_engine_hours": 400.0},
    }
    (hdir / "тест__20260501_20260531.json").write_text(
        json.dumps(snap, ensure_ascii=False), encoding="utf-8")
    b = savings.freeze_from_history(
        "Тест", datetime(2026, 5, 1, tzinfo=timezone.utc),
        datetime(2026, 6, 1, tzinfo=timezone.utc),
        history_dir=str(hdir), baseline_dir=str(tmp_path / "baseline"))
    assert b["schema"] == 2
    assert b["rates_v2"]["mobile"]["idle_share"] == 0.5         # 300/600
    assert b["rates_v2"]["mobile"]["moving_l_per_100km"] == 35.0  # 3500/10000
    assert b["rates_v2"]["stationary"]["l_per_mh"] == 5.0       # 2000/400
    # v1-ставки тоже на месте (fallback для старых сравнений)
    assert b["rates"]["idle_share"] == 0.4


def test_cumulative_dedupes_overlapping_periods():
    """Двойной счёт пересекающихся периодов не должен раздувать итог.

    Регресс: дневная запись 12.06 внутри блока 01–12.06 ранее суммировалась
    дважды (headline завышался на величину пересечения).
    """
    led = {"client": "T", "entries": [
        {"period_start": 1748736000, "period_end": 1749772799,  # 01–12.06
         "period_human": "01-12.06", "saved_l": 1687.7, "saved_kzt": 576856},
        {"period_start": 1749686400, "period_end": 1749772799,  # 12.06 (внутри)
         "period_human": "12.06", "saved_l": 418.0, "saved_kzt": 142538},
        {"period_start": 1749772800, "period_end": 1749859199,  # 13.06
         "period_human": "13.06", "saved_l": 56.5, "saved_kzt": 19266},
    ]}
    saved_l, saved_kzt = savings.cumulative(led)
    # 12.06 пересекает блок 01–12 → исключается; остаются блок + 13.06
    assert saved_kzt == 576856 + 19266
    assert saved_l == round(1687.7 + 56.5, 1)


def test_cumulative_keeps_disjoint_periods():
    """Непересекающиеся периоды считаются все."""
    led = {"client": "T", "entries": [
        {"period_start": 100, "period_end": 199, "saved_l": 10, "saved_kzt": 1000},
        {"period_start": 200, "period_end": 299, "saved_l": 20, "saved_kzt": 2000},
    ]}
    saved_l, saved_kzt = savings.cumulative(led)
    assert saved_kzt == 3000 and saved_l == 30
