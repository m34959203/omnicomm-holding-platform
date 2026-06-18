"""Счётчик подтверждённой экономии: baseline + verified savings (Ф2, STRATEGY §4.2).

Методология IPMVP-lite (стандарт энергосервисных контрактов, адаптация):
    ожидание = baseline-ставки × фактическая активность периода (± сезон)
    экономия = ожидание − факт (литры → ₸ по цене периода)

Две компоненты без двойного счёта:
  • idle   — ожидаемые часы простоя = baseline.idle_share × моточасы периода,
             топливо = часы × baseline-ставка л/ч на холостом ходу;
  • moving — ожидаемое топливо движения = baseline.л/100км(в движении) × пробег.

Нормализация: активность (пробег/моточасы) всегда берётся ФАКТИЧЕСКАЯ за
текущий период — «ездили меньше, потратили меньше» экономией не считается.
Сезон: если сезон периода отличается от сезона baseline, ожидание корректируется
коэффициентом NORM_COEFFICIENTS['winter'] (РК ≈ +10% зимой).

Baseline замораживается ЯВНО (кнопка/CLI) из снапшотов истории (history.py)
за выбранный диапазон дат и далее не пересчитывается — это контрактная точка
отсчёта программы экономии. Перезаморозка = новая программа (леджер очищается
только вручную).

Леджер: output/savings/<slug>.json — по записи на период (идемпотентно,
повторный прогон периода перезаписывает запись). Накопленный итог = сумма.
Отрицательная экономия (перерасход к эталону) записывается честно.

CLI:
    python -m omnicomm_report.savings freeze --client "Горкомтранс" \
        --from 2026-05-01 --to 2026-05-31
    python -m omnicomm_report.savings status --client "Горкомтранс"
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from omnicomm_report import config
from omnicomm_report.models import FleetReport

log = logging.getLogger(__name__)

DEFAULT_BASELINE_DIR = os.path.join("output", "baseline")
DEFAULT_SAVINGS_DIR = os.path.join("output", "savings")
# Минимальная фактическая база для заморозки — иначе ставки случайны.
MIN_BASELINE_ENGINE_HOURS = 100.0


def _slug(client_name: str) -> str:
    from omnicomm_report.history import _slug as hslug
    return hslug(client_name)


def _season_of_month(month: int) -> str:
    """Сезон РК: ноябрь–март — зима (зеркало scheduler._auto_season)."""
    return "winter" if month in (11, 12, 1, 2, 3) else "summer"


# --- Baseline ------------------------------------------------------------------

def freeze_from_history(
    client_name: str,
    date_from: datetime,
    date_to: datetime,
    *,
    history_dir: str = os.path.join("output", "history"),
    baseline_dir: str = DEFAULT_BASELINE_DIR,
) -> Optional[dict]:
    """Заморозить baseline из снапшотов истории, попавших в [date_from, date_to].

    Ставки считаются по СУММАМ за все снапшоты (не среднее средних).
    Возвращает baseline-словарь или None (нет данных/мало наработки).
    """
    slug = _slug(client_name)
    sums = {"engine_h": 0.0, "idle_h": 0.0, "fuel_l": 0.0,
            "fuel_idle_l": 0.0, "mileage_km": 0.0}
    # Срезы по классам (есть только в новых снапшотах) — для baseline v2.
    cls = {"mob_fuel": 0.0, "mob_idle_fuel": 0.0, "mob_h": 0.0,
           "mob_idle_h": 0.0, "mob_km": 0.0, "stat_fuel": 0.0, "stat_h": 0.0}
    cls_present = True   # False, если хоть один снапшот без срезов (старый)
    periods: list[tuple[int, int]] = []
    if not os.path.isdir(history_dir):
        return None
    for name in sorted(os.listdir(history_dir)):
        if not name.startswith(slug + "__") or not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(history_dir, name), encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        ps, pe = int(data.get("period_start", 0)), int(data.get("period_end", 0))
        if ps < int(date_from.timestamp()) or pe > int(date_to.timestamp()):
            continue
        kpi = data.get("kpi", {})
        sums["engine_h"] += float(kpi.get("total_engine_hours") or 0)
        sums["idle_h"] += float(kpi.get("total_idle_hours") or 0)
        sums["fuel_l"] += float(kpi.get("total_fuel_l") or 0)
        sums["fuel_idle_l"] += float(kpi.get("fuel_idle_l") or 0)
        sums["mileage_km"] += float(kpi.get("total_mileage_km") or 0)
        if "mobile_fuel_l" in kpi:
            cls["mob_fuel"] += float(kpi.get("mobile_fuel_l") or 0)
            cls["mob_idle_fuel"] += float(kpi.get("mobile_fuel_idle_l") or 0)
            cls["mob_h"] += float(kpi.get("mobile_engine_hours") or 0)
            cls["mob_idle_h"] += float(kpi.get("mobile_idle_hours") or 0)
            cls["mob_km"] += float(kpi.get("mobile_mileage_km") or 0)
            cls["stat_fuel"] += float(kpi.get("stationary_fuel_l") or 0)
            cls["stat_h"] += float(kpi.get("stationary_engine_hours") or 0)
        else:
            cls_present = False
        periods.append((ps, pe))

    if not periods or sums["engine_h"] < MIN_BASELINE_ENGINE_HOURS:
        log.warning("Baseline не заморожен: снапшотов %d, моточасов %.0f (мин. %.0f)",
                    len(periods), sums["engine_h"], MIN_BASELINE_ENGINE_HOURS)
        return None

    idle_share = sums["idle_h"] / sums["engine_h"] if sums["engine_h"] else 0.0
    idle_rate = (sums["fuel_idle_l"] / sums["idle_h"]) if sums["idle_h"] else 0.0
    moving_fuel = max(0.0, sums["fuel_l"] - sums["fuel_idle_l"])
    moving_rate = (moving_fuel / sums["mileage_km"] * 100.0
                   if sums["mileage_km"] else 0.0)

    # Сезон baseline — по большинству месяцев начала периодов-источников.
    months = [datetime.fromtimestamp(ps, tz=timezone.utc).month for ps, _ in periods]
    winters = sum(1 for m in months if _season_of_month(m) == "winter")
    season = ("winter" if winters > len(months) / 2
              else "summer" if winters == 0 else "mixed")

    baseline = {
        "client": client_name,
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "date_from": int(date_from.timestamp()),
        "date_to": int(date_to.timestamp()),
        "source_periods": len(periods),
        "season": season,
        "rates": {
            "idle_share": round(idle_share, 4),
            "idle_rate_l_h": round(idle_rate, 3),
            "moving_l_per_100km": round(moving_rate, 2),
        },
        "totals": {k: round(v, 1) for k, v in sums.items()},
    }
    # v2: ставки по классам — мобильные и спецтехника раздельно, чтобы состав
    # парка (выпал экскаватор из строя и т.п.) не искажал счётчик. Доступно,
    # только если ВСЕ снапшоты диапазона несут срезы по классам.
    if cls_present and cls["mob_h"] > 0:
        baseline["schema"] = 2
        baseline["rates_v2"] = {
            "mobile": {
                "idle_share": round(cls["mob_idle_h"] / cls["mob_h"], 4),
                "idle_rate_l_h": round(
                    cls["mob_idle_fuel"] / cls["mob_idle_h"], 3)
                if cls["mob_idle_h"] else 0.0,
                "moving_l_per_100km": round(
                    max(0.0, cls["mob_fuel"] - cls["mob_idle_fuel"])
                    / cls["mob_km"] * 100, 2) if cls["mob_km"] else 0.0,
            },
            "stationary": {
                "l_per_mh": round(cls["stat_fuel"] / cls["stat_h"], 3)
                if cls["stat_h"] else 0.0,
            },
        }
    os.makedirs(baseline_dir, exist_ok=True)
    path = os.path.join(baseline_dir, f"{slug}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(baseline, fh, ensure_ascii=False, indent=1)
    log.info("Baseline заморожен: %s (%d периодов, idle %.0f%%, %.1f л/100км движ.)",
             path, len(periods), idle_share * 100, moving_rate)
    return baseline


def load_baseline(client_name: str,
                  baseline_dir: str = DEFAULT_BASELINE_DIR) -> Optional[dict]:
    path = os.path.join(baseline_dir, f"{_slug(client_name)}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


# --- Расчёт экономии периода ----------------------------------------------------

def _season_factor(baseline_season: str, report_season: str) -> float:
    """Коэффициент к ожиданию при смене сезона baseline → период.

    mixed-baseline сезонно не корректируем (усреднён по сезонам).
    """
    w = config.NORM_COEFFICIENTS["winter"]
    if baseline_season == "mixed" or baseline_season == report_season:
        return 1.0
    if report_season == "winter":   # baseline летний, период зимний → ждём больше
        return w
    return 1.0 / w                  # baseline зимний, период летний → ждём меньше


def compute_savings(report: FleetReport, baseline: dict) -> Optional[dict]:
    """Экономия периода против baseline. None — если активность нулевая.

    Отрицательные значения = перерасход к эталону (записываются честно).
    """
    kpi = report.kpi
    rates = baseline.get("rates", {})
    if kpi.total_engine_hours <= 0 and kpi.total_mileage_km <= 0:
        return None

    factor = _season_factor(baseline.get("season", "summer"),
                            report.season or "summer")

    v2 = baseline.get("rates_v2") if baseline.get("schema") == 2 else None
    components: dict[str, dict] = {}
    if v2 and (kpi.mobile_engine_hours > 0 or kpi.stationary_engine_hours > 0):
        # v2: классы раздельно — состав парка не искажает счётчик.
        mob = v2.get("mobile", {})
        # idle мобильных: доля от ФАКТИЧЕСКИХ моточасов мобильных.
        exp_idle_l = (mob.get("idle_share", 0.0) * kpi.mobile_engine_hours
                      * mob.get("idle_rate_l_h", 0.0) * factor)
        act_idle_l = kpi.mobile_fuel_idle_l
        # движение мобильных: ставка × фактический пробег мобильных.
        exp_mov_l = (mob.get("moving_l_per_100km", 0.0)
                     * kpi.mobile_mileage_km / 100.0 * factor)
        act_mov_l = max(0.0, kpi.mobile_fuel_l - kpi.mobile_fuel_idle_l)
        # спецтехника: л/мч × фактические моточасы (idle внутри — её режим).
        exp_stat_l = (v2.get("stationary", {}).get("l_per_mh", 0.0)
                      * kpi.stationary_engine_hours * factor)
        act_stat_l = kpi.stationary_fuel_l
        components = {
            "idle": {"expected_l": round(exp_idle_l, 1),
                     "actual_l": round(act_idle_l, 1),
                     "saved_l": round(exp_idle_l - act_idle_l, 1)},
            "moving": {"expected_l": round(exp_mov_l, 1),
                       "actual_l": round(act_mov_l, 1),
                       "saved_l": round(exp_mov_l - act_mov_l, 1)},
            "stationary": {"expected_l": round(exp_stat_l, 1),
                           "actual_l": round(act_stat_l, 1),
                           "saved_l": round(exp_stat_l - act_stat_l, 1)},
        }
    else:
        # v1 (старые снапшоты без срезов): ставки по парку целиком.
        exp_idle_h = rates.get("idle_share", 0.0) * kpi.total_engine_hours
        exp_idle_l = exp_idle_h * rates.get("idle_rate_l_h", 0.0) * factor
        act_idle_l = kpi.fuel_idle_l
        exp_mov_l = (rates.get("moving_l_per_100km", 0.0)
                     * kpi.total_mileage_km / 100.0 * factor)
        act_mov_l = max(0.0, kpi.total_fuel_l - kpi.fuel_idle_l)
        components = {
            "idle": {"expected_l": round(exp_idle_l, 1),
                     "actual_l": round(act_idle_l, 1),
                     "saved_l": round(exp_idle_l - act_idle_l, 1)},
            "moving": {"expected_l": round(exp_mov_l, 1),
                       "actual_l": round(act_mov_l, 1),
                       "saved_l": round(exp_mov_l - act_mov_l, 1)},
        }

    expected_total = sum(c["expected_l"] for c in components.values())
    actual_total = sum(c["actual_l"] for c in components.values())
    saved_l = expected_total - actual_total
    price = kpi.fuel_price_kzt or 0.0
    entry = {
        "period_start": int(report.period.start_ts),
        "period_end": int(report.period.end_ts),
        "period_human": report.period.human(),
        "computed_at": (report.generated_at or datetime.now(timezone.utc)).isoformat(),
        "season_factor": round(factor, 3),
        "schema": 2 if "stationary" in components else 1,
        "expected_l": round(expected_total, 1),
        "actual_l": round(actual_total, 1),
        "saved_l": round(saved_l, 1),
        "saved_kzt": round(saved_l * price) if price > 0 else 0,
        "fuel_price_kzt": price,
        "components": components,
    }
    return entry


# --- Леджер ----------------------------------------------------------------------

def _ledger_path(client_name: str, savings_dir: str = DEFAULT_SAVINGS_DIR) -> str:
    return os.path.join(savings_dir, f"{_slug(client_name)}.json")


def load_ledger(client_name: str,
                savings_dir: str = DEFAULT_SAVINGS_DIR) -> dict:
    path = _ledger_path(client_name, savings_dir)
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            pass
    return {"client": client_name, "entries": []}


def update_ledger(client_name: str, entry: dict, baseline: dict,
                  savings_dir: str = DEFAULT_SAVINGS_DIR) -> dict:
    """Записать/обновить запись периода (идемпотентно). Возвращает леджер.

    Защита от двойного счёта: период, ПЕРЕСЕКАЮЩИЙСЯ с уже учтёнными (кроме
    точного совпадения — оно перезаписывается), в леджер не пишется. Иначе
    ручной отчёт «за месяц» поверх ежедневных записей задвоил бы экономию.
    """
    ledger = load_ledger(client_name, savings_dir)
    ledger["baseline_frozen_at"] = baseline.get("frozen_at")
    entries = [e for e in ledger.get("entries", [])
               if not (e.get("period_start") == entry["period_start"]
                       and e.get("period_end") == entry["period_end"])]
    for e in entries:
        if (entry["period_start"] < e.get("period_end", 0)
                and e.get("period_start", 0) < entry["period_end"]):
            log.info("Счётчик: период %s пересекает учтённый %s — пропуск "
                     "(защита от двойного счёта)",
                     entry.get("period_human"), e.get("period_human"))
            return ledger
    entries.append(entry)
    entries.sort(key=lambda e: e.get("period_end", 0))
    ledger["entries"] = entries
    os.makedirs(savings_dir, exist_ok=True)
    with open(_ledger_path(client_name, savings_dir), "w", encoding="utf-8") as fh:
        json.dump(ledger, fh, ensure_ascii=False, indent=1)
    return ledger


def _dedupe_overlaps(entries: list[dict]) -> list[dict]:
    """Убрать пересекающиеся по времени записи — защита от двойного счёта.

    Жадно по возрастанию начала: берём запись, пропускаем последующие, что
    пересекаются с уже взятой (напр. дневная 12.06 внутри блока 01–12.06).
    Делает накопленный итог устойчивым, даже если леджер «загрязнён» ручными
    бэкфилл-прогонами поверх ежедневных (исторически так и случалось →
    headline завышался на величину пересечения).
    """
    ok: list[dict] = []
    last_end: Optional[int] = None
    for e in sorted(entries, key=lambda x: (x.get("period_start", 0),
                                            x.get("period_end", 0))):
        s, en = int(e.get("period_start", 0)), int(e.get("period_end", 0))
        if last_end is not None and s < last_end:
            log.info("Счётчик: запись %s пересекает учтённую — исключена из "
                     "итога (защита от двойного счёта)", e.get("period_human"))
            continue
        ok.append(e)
        last_end = max(last_end or 0, en)
    return ok


def cumulative(ledger: dict) -> tuple[float, float]:
    """(литры, ₸) накопленно по леджеру — БЕЗ двойного счёта пересечений."""
    entries = _dedupe_overlaps(ledger.get("entries", []))
    saved_l = sum(float(e.get("saved_l") or 0) for e in entries)
    saved_kzt = sum(float(e.get("saved_kzt") or 0) for e in entries)
    return round(saved_l, 1), round(saved_kzt)


# --- Интеграция в конвейер --------------------------------------------------------

def apply_to_report(report: FleetReport, *,
                    baseline_dir: str = DEFAULT_BASELINE_DIR,
                    savings_dir: str = DEFAULT_SAVINGS_DIR) -> Optional[dict]:
    """Посчитать экономию периода, обновить леджер, прикрепить к отчёту.

    Без замороженного baseline — no-op (None). Периоды, пересекающие baseline-окно,
    в счётчик не пишутся (нельзя сравнивать эталон сам с собой).
    """
    baseline = load_baseline(report.client_name, baseline_dir)
    if not baseline:
        return None
    if int(report.period.start_ts) < int(baseline.get("date_to", 0)):
        log.info("Счётчик экономии: период пересекает baseline-окно — пропуск")
        return None
    entry = compute_savings(report, baseline)
    if entry is None:
        return None
    ledger = update_ledger(report.client_name, entry, baseline, savings_dir)
    saved_l, saved_kzt = cumulative(ledger)
    counted = _dedupe_overlaps(ledger.get("entries", []))  # без пересечений
    series = [(e["period_end"],
               round(sum(float(x.get("saved_kzt") or 0)
                         for x in counted[:i + 1])))
              for i, e in enumerate(counted)]
    report.savings = {
        "baseline": baseline,
        "period": entry,
        "cumulative_l": saved_l,
        "cumulative_kzt": saved_kzt,
        "entries_count": len(counted),
        "series": series,
    }
    report.alerts.extend(_program_digest(report))
    return report.savings


def _program_digest(report: FleetReport) -> list[str]:
    """Дайджест программы экономии для сигналов/рассылки («машины недели»).

    Короткие строки: результат периода + накопление + 3 первоочередные ТС
    (холостой ход выше медианы парка). Формулировки нейтральные.
    """
    s = report.savings or {}
    entry = s.get("period")
    if not entry:
        return []

    def _kzt(v: float) -> str:
        return f"{abs(v):,.0f} ₸".replace(",", " ")

    sign = "экономия" if entry["saved_kzt"] >= 0 else "перерасход к эталону"
    cum = s.get("cumulative_kzt", 0)
    cum_sign = "экономия" if cum >= 0 else "перерасход к эталону"
    out = [
        f"Программа экономии: за период {_kzt(entry['saved_kzt'])} — {sign}; "
        f"накоплено {_kzt(cum)} за {s.get('entries_count', 0)} пер. — {cum_sign}."
    ]
    from omnicomm_report import economics as econ_mod
    worst = econ_mod.build_economics(report).worst_vehicles[:3]
    if worst:
        names = "; ".join(f"«{n}» ({_kzt(k)})" for n, k in worst)
        out.append(f"Машины недели (приоритет программы): {names} — "
                   "холостой ход выше медианы парка, проверить режим.")
    return out


# --- CLI ---------------------------------------------------------------------------

def _cli() -> None:
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(
        description="Программа экономии: заморозка baseline и статус счётчика")
    sub = ap.add_subparsers(dest="cmd", required=True)

    fz = sub.add_parser("freeze", help="заморозить baseline из истории снапшотов")
    fz.add_argument("--client", required=True)
    fz.add_argument("--from", dest="date_from", required=True, help="YYYY-MM-DD")
    fz.add_argument("--to", dest="date_to", required=True, help="YYYY-MM-DD")

    stt = sub.add_parser("status", help="показать baseline и накопленный счётчик")
    stt.add_argument("--client", required=True)

    args = ap.parse_args()
    if args.cmd == "freeze":
        df = datetime.strptime(args.date_from, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        dt = datetime.strptime(args.date_to, "%Y-%m-%d").replace(
            hour=23, minute=59, second=59, tzinfo=timezone.utc)
        b = freeze_from_history(args.client, df, dt)
        raise SystemExit(0 if b else "Baseline не заморожен (нет истории за диапазон)")
    if args.cmd == "status":
        b = load_baseline(args.client)
        if not b:
            raise SystemExit("Baseline не заморожен")
        led = load_ledger(args.client)
        saved_l, saved_kzt = cumulative(led)
        print(f"Baseline: {b['frozen_at'][:10]} · {b['source_periods']} периодов · "
              f"idle {b['rates']['idle_share'] * 100:.0f}% · "
              f"{b['rates']['moving_l_per_100km']:.1f} л/100км движ. · сезон {b['season']}")
        print(f"Счётчик: {len(led.get('entries', []))} периодов · "
              f"{saved_l:+.0f} л · {saved_kzt:+,.0f} ₸".replace(",", " "))


if __name__ == "__main__":
    _cli()
