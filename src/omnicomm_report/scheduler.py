"""Встроенный планировщик авторассылки (вариант B).

Демон периодически проверяет расписание каждого клиента и, если подошло время,
сам опрашивает Omnicomm, собирает отчёт и шлёт его/сигналы на e-mail. Контроль:
состояние каждого прогона (когда, статус, период) пишется в `data/schedule_state`,
а сам демон — heartbeat в `data/scheduler_heartbeat.json` (панель видит, жив ли он).

Идемпотентность: для одной запланированной точки времени прогон выполняется один
раз (сравнение last_run с «последним наступившим слотом»). API только на чтение.

Запуск демона:  python -m omnicomm_report.scheduler
Логика `is_due`/`last_occurrence`/`run_due` — чистая, тестируется без сети.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, time as dtime, timedelta, timezone
from typing import Optional

from . import (
    analytics, charts, clients, data_loader, fuel_price, history, norms,
    price_history, report_builder, validator,
)
from .config import Settings, load_env_file

logger = logging.getLogger(__name__)

STATE_DIR = os.path.join("data", "schedule_state")
HEARTBEAT_PATH = os.path.join("data", "scheduler_heartbeat.json")
FUEL_STATE_PATH = os.path.join("data", "fuel_price_state.json")
SCHEDULED_OUT = os.path.join("output", "scheduled")
TICK_SEC = 60


# --- Ежедневный снапшот цены ГСМ в календарь ---------------------------------

def _auto_season(month: int) -> str:
    """РК: ноябрь–март — зимний ДТ."""
    return "winter" if month in (11, 12, 1, 2, 3) else "summer"


def snapshot_fuel_price(now: Optional[datetime] = None) -> Optional[float]:
    """Раз в день спарсить цену ДТ (Royal Petrol) и записать в календарь цен.

    Самогейтится по дате (повторные вызовы в течение дня — no-op). Так календарь
    `price_history` наполняется ежедневно, и авто-отчёты демона считают расход по
    цене конкретного дня. Возвращает записанную цену или None.
    """
    now = now or datetime.now(timezone.utc)
    today = now.date().isoformat()
    state = {}
    try:
        with open(FUEL_STATE_PATH, encoding="utf-8") as fh:
            state = json.load(fh) or {}
    except (OSError, ValueError):
        pass
    if state.get("last_date") == today:
        return None                             # цена за сегодня уже в календаре
    # кулдаун 1ч между попытками, чтобы при сбое не дёргать парсер каждый тик
    if now.timestamp() - float(state.get("last_attempt", 0)) < 3600:
        return None

    def _write(extra):
        os.makedirs(os.path.dirname(FUEL_STATE_PATH) or ".", exist_ok=True)
        with open(FUEL_STATE_PATH, "w", encoding="utf-8") as fh:
            json.dump({"last_attempt": now.timestamp(), **state, **extra}, fh)

    ref = fuel_price.get_reference(_auto_season(now.month))
    price = (ref or {}).get("diesel")
    if not price or price <= 0:
        _write({"last_attempt": now.timestamp()})   # отметить попытку (кулдаун)
        logger.info("Снапшот цены ГСМ: цена не получена (повтор через 1ч)")
        return None
    price_history.add_price(today, float(price))
    _write({"last_date": today, "price": float(price), "last_attempt": now.timestamp()})
    logger.info("Снапшот цены ГСМ: %s = %.0f ₸/л → календарь", today, price)
    return float(price)


# --- Расписание: чистая логика -----------------------------------------------

def last_occurrence(schedule: dict, now: datetime) -> Optional[datetime]:
    """Последний наступивший (<= now) запланированный момент или None."""
    if not schedule or not schedule.get("enabled"):
        return None
    hour = int(schedule.get("hour", 6))
    freq = schedule.get("freq", "monthly")
    at = dtime(hour=max(0, min(23, hour)), tzinfo=timezone.utc)

    if freq == "daily":
        occ = datetime.combine(now.date(), at)
        return occ if occ <= now else occ - timedelta(days=1)
    if freq == "weekly":
        wd = int(schedule.get("weekday", 0))            # 0=Пн
        occ = datetime.combine(now.date(), at) - timedelta(days=(now.weekday() - wd) % 7)
        return occ if occ <= now else occ - timedelta(days=7)
    # monthly
    day = max(1, min(28, int(schedule.get("day", 1))))
    occ = datetime.combine(now.date().replace(day=day), at)
    if occ > now:
        prev = (now.date().replace(day=1) - timedelta(days=1)).replace(day=day)
        occ = datetime.combine(prev, at)
    return occ


def is_due(schedule: dict, last_run_ts: Optional[float], now: datetime) -> bool:
    """Пора ли запускать: есть наступивший слот, новее последнего прогона."""
    occ = last_occurrence(schedule, now)
    if occ is None:
        return False
    return last_run_ts is None or last_run_ts < occ.timestamp()


def preset_period(preset: str, now: datetime):
    """Период из пресета относительно now (UTC)."""
    from .models import ReportPeriod
    today = now.date()
    if preset == "last-day":
        d = today - timedelta(days=1)
        a, b = d, d
    elif preset == "last-week":
        a, b = today - timedelta(days=7), today - timedelta(days=1)
    elif preset == "last-month":
        last_prev = today.replace(day=1) - timedelta(days=1)
        a, b = last_prev.replace(day=1), last_prev
    else:
        a, b = today.replace(day=1), today
    return ReportPeriod(
        start=datetime.combine(a, dtime.min, tzinfo=timezone.utc),
        end=datetime.combine(b, dtime.max, tzinfo=timezone.utc))


# --- Состояние ---------------------------------------------------------------

def _state_path(name: str) -> str:
    return os.path.join(STATE_DIR, f"{clients._slug(name)}.json")


def load_state(name: str) -> dict:
    try:
        with open(_state_path(name), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_state(name: str, state: dict) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(_state_path(name), "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=1)


def write_heartbeat(now: datetime) -> None:
    os.makedirs(os.path.dirname(HEARTBEAT_PATH) or ".", exist_ok=True)
    with open(HEARTBEAT_PATH, "w", encoding="utf-8") as fh:
        json.dump({"tick_ts": now.timestamp()}, fh)


def heartbeat_alive(max_age_s: int = 180) -> bool:
    try:
        with open(HEARTBEAT_PATH, encoding="utf-8") as fh:
            return time.time() - float(json.load(fh).get("tick_ts", 0)) <= max_age_s
    except (OSError, ValueError):
        return False


# --- Прогон клиента ----------------------------------------------------------

def run_for_client(name: str, now: Optional[datetime] = None) -> dict:
    """Сформировать отчёт за период расписания и разослать. Возвращает статус."""
    from . import alerts as alerts_mod, mailer
    now = now or datetime.now(timezone.utc)
    cfg = clients.load_client(name)
    if not cfg:
        return {"ok": False, "message": "клиент не найден"}
    sch = cfg.get("schedule") or {}
    period = preset_period(sch.get("preset", "last-month"), now)
    omni = cfg["omnicomm"]
    try:
        from .api_client import OmnicommClient
        client = OmnicommClient(Settings(
            base_url=omni["base_url"], login=omni["login"],
            password=omni["password"], service=omni.get("service", "")))
        client.login()
        vehicles = data_loader.load_from_api(
            client, period, None, with_track=cfg.get("with_track", False))
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": f"Omnicomm: {exc}", "period": period.human()}

    vehicles = validator.validate(vehicles)
    # Авто-сезон по месяцу периода (РК: ноябрь–март — зима → норма +10%).
    season = _auto_season(period.start.month)
    # Цена за период — из календаря ГСМ (его наполняет ежедневный снапшот),
    # иначе ручная цена клиента.
    price_eff, _bl = price_history.price_for_period(
        cfg.get("fuel_price_kzt", 0), period.start, period.end)
    rep = analytics.analyze(vehicles, period, name, source="api",
                            fuel_price_kzt=price_eff,
                            previous_kpi=history.load_previous(name, period),
                            norms=norms.load_norms(name) or None, season=season,
                            time_fund_hours_per_day=float(
                                cfg.get("time_fund_hours_per_day") or 0))
    rep.generated_at = now
    history.save_snapshot(rep)
    from . import savings as savings_mod
    savings_mod.apply_to_report(rep)   # no-op без замороженного baseline

    outdir = os.path.join(SCHEDULED_OUT, clients._slug(name))
    os.makedirs(outdir, exist_ok=True)
    stamp = now.strftime("%Y_%m_%d")
    cp = charts.build_charts(rep, outdir)
    pptx = os.path.join(outdir, f"report_{stamp}.pptx")
    html = os.path.join(outdir, f"report_{stamp}.html")
    report_builder.build_pptx(rep, cp, pptx)
    report_builder.build_html(rep, cp, html)
    files = [pptx, html]

    email = cfg.get("email", "")
    sent = []
    if email and mailer.smtp_configured():
        if sch.get("send_report", True):
            if mailer.send_report(email, f"Отчёт «{name}» — {period.human()}",
                                  f"Автоотчёт за {period.human()}.", files):
                sent.append("отчёт")
        if sch.get("send_alerts", True) and rep.alerts:
            if alerts_mod.send_alerts(rep, email):
                sent.append(f"сигналы({len(rep.alerts)})")
    from . import audit
    audit.log("scheduled_report", client=name, actor="scheduler",
              period=period.human(), season=season, alerts=len(rep.alerts), sent=sent)
    return {"ok": True, "period": period.human(), "alerts": len(rep.alerts),
            "sent": sent, "files": files,
            "message": f"готово; отправлено: {', '.join(sent) or 'нет (email/SMTP)'}"}


def run_due(now: Optional[datetime] = None, clients_dir: str = clients.DEFAULT_CLIENTS_DIR
            ) -> list[dict]:
    """Прогнать всех клиентов, у кого подошло время. Обновляет состояние."""
    now = now or datetime.now(timezone.utc)
    results = []
    for name in clients.list_clients(clients_dir):
        cfg = clients.load_client(name)
        sch = (cfg or {}).get("schedule") or {}
        st = load_state(name)
        if not is_due(sch, st.get("last_run_ts"), now):
            continue
        logger.info("Планировщик: запуск «%s»", name)
        res = run_for_client(name, now)
        st.update({"last_run_ts": now.timestamp(), "last_status": res.get("message"),
                   "last_period": res.get("period"), "last_ok": res.get("ok")})
        save_state(name, st)
        results.append({"client": name, **res})
    return results


def main() -> None:
    """Демон: тик раз в TICK_SEC, heartbeat + run_due."""
    load_env_file()   # APP_CRYPTO_KEY/SMTP в окружение (cron не сорсит .env)
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s scheduler: %(message)s")
    logger.info("Планировщик запущен (тик %dс)", TICK_SEC)
    while True:
        now = datetime.now(timezone.utc)
        try:
            write_heartbeat(now)
            snapshot_fuel_price(now)        # ежедневный снимок цены ГСМ в календарь
            for r in run_due(now):
                logger.info("  %s: %s", r["client"], r["message"])
        except Exception as exc:  # noqa: BLE001 — демон не должен падать
            logger.warning("тик с ошибкой: %s", exc)
        time.sleep(TICK_SEC)


if __name__ == "__main__":
    main()
