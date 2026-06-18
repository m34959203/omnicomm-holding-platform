"""Платформа Omnicomm Fleet Report (песочница, Streamlit).

Мульти-клиентский режим: учётка Omnicomm и настройки клиента вводятся ОДИН РАЗ
и хранятся на сервере (data/clients, gitignored). Дальше — выбрал клиента →
период → клик → отчёт с перерасходом/экономией по сохранённым нормам/паспортам.

Также: разовый режим из файла (Excel/CSV) и онбординг нового клиента.

Запуск:  streamlit run app.py
Безопасность: пароли клиентов хранятся обфусцированно в gitignored-каталоге —
это песочница, не продакшен-секрет-хранилище.
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import date, datetime, time, timedelta, timezone
from time import monotonic

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

import streamlit as st  # noqa: E402

from omnicomm_report import (  # noqa: E402
    analytics, audit, auth, charts, clients, data_loader, history, norms, price_history,
    report_builder, validator, vehicle_types,
)
from omnicomm_report.config import (  # noqa: E402
    DEFAULT_FUEL_PRICE_KZT, Settings, load_env_file)
from omnicomm_report.models import ReportPeriod  # noqa: E402

load_env_file()   # .env в окружение (cron-запуск голым `env` его не сорсит)

st.set_page_config(page_title="Omnicomm Fleet Report — Платформа",
                   page_icon="🚚", layout="wide")

PRESETS = ["Сегодня", "Вчера", "Последние 7 дней", "Последние 30 дней",
           "Текущий месяц", "Прошлый месяц", "Текущий год", "Произвольный диапазон"]


def _preset_range(preset: str, today: date) -> tuple[date, date]:
    if preset == "Сегодня":
        return today, today
    if preset == "Вчера":
        d = today - timedelta(days=1)
        return d, d
    if preset == "Последние 7 дней":
        return today - timedelta(days=6), today
    if preset == "Последние 30 дней":
        return today - timedelta(days=29), today
    if preset == "Текущий месяц":
        return today.replace(day=1), today
    if preset == "Прошлый месяц":
        last_prev = today.replace(day=1) - timedelta(days=1)
        return last_prev.replace(day=1), last_prev
    if preset == "Текущий год":
        return today.replace(month=1, day=1), today
    return today.replace(day=1), today


def _period_from(start_d: date, end_d: date) -> ReportPeriod:
    return ReportPeriod(
        start=datetime.combine(start_d, time.min, tzinfo=timezone.utc),
        end=datetime.combine(end_d, time.max, tzinfo=timezone.utc),
    )


def _pick_period() -> ReportPeriod:
    today = datetime.now(timezone.utc).date()
    preset = st.selectbox("Период", PRESETS, index=4)
    if preset == "Произвольный диапазон":
        c1, c2 = st.columns(2)
        start_d = c1.date_input("Начало", value=today.replace(day=1))
        end_d = c2.date_input("Конец", value=today)
    else:
        start_d, end_d = _preset_range(preset, today)
        st.info(f"Период: **{start_d:%d.%m.%Y} — {end_d:%d.%m.%Y}**")
    if start_d > end_d:
        st.error("Начало позже конца — исправьте диапазон.")
        st.stop()
    return _period_from(start_d, end_d)


# --- Конвейер и вывод --------------------------------------------------------

def _stage(status, msg: str, started: float) -> None:
    """Показать стадию прогресса в st.status с прошедшим таймингом."""
    if status is None:
        return
    status.update(label=f"⏳ {msg}")
    status.write(f"• {msg} · {monotonic() - started:.1f} с")


def _gen_clicked(slot: str, *, disabled: bool = False) -> bool:
    """Кнопка «Сформировать отчёт» с деактивацией на время генерации.

    Клик → ставит флаг и перезапускает скрипт (кнопка рендерится disabled).
    Возвращает True только на прогоне, где нужно выполнять генерацию `slot`.
    """
    running = st.session_state.get("gen_running") is not None
    if st.button("🚀 Сформировать отчёт", type="primary", use_container_width=True,
                 disabled=running or disabled, key=f"gen_btn_{slot}"):
        st.session_state["gen_running"] = slot
        st.rerun()
    return st.session_state.get("gen_running") == slot


def _finalize_and_store(report, *, email="", send_report=False, send_alerts=False,
                        status=None, started=None):
    """Собрать файлы отчёта, разослать (опц.) и СОХРАНИТЬ результат в session_state.

    Рендер вынесен в `_render_last_report` — чтобы отчёт переживал rerun (нажатие
    «Скачать» не закрывало его). Здесь только тяжёлая часть, один раз.
    """
    from omnicomm_report import alerts as alerts_mod, mailer, savings as savings_mod
    started = started if started is not None else monotonic()
    history.save_snapshot(report)
    savings_mod.apply_to_report(report)   # no-op без замороженного baseline
    with tempfile.TemporaryDirectory() as work:
        _stage(status, "Построение графиков", started)
        cp = charts.build_charts(report, work)
        stamp = report.generated_at.strftime("%Y_%m_%d")
        _stage(status, "Сборка презентации (.pptx)", started)
        pptx = os.path.join(work, f"report_{stamp}.pptx")
        report_builder.build_pptx(report, cp, pptx)
        pptx_bytes = open(pptx, "rb").read()
        _stage(status, "Сборка веб-отчёта (.html)", started)
        html_path = os.path.join(work, f"report_{stamp}.html")
        report_builder.build_html(report, cp, html_path)
        html_bytes = open(html_path, "rb").read()

        sent_msg = ""
        if email and (send_report or send_alerts):
            if not mailer.smtp_configured():
                sent_msg = "⚠️ Email не отправлен: SMTP не настроен (.env)."
            else:
                _stage(status, f"Отправка на {email}", started)
                if send_report and mailer.send_report(
                        email, f"Отчёт по автопарку «{report.client_name}» — {report.period.human()}",
                        f"Отчёт за период {report.period.human()} во вложении.",
                        [pptx, html_path]):
                    sent_msg = f"Отчёт отправлен на {email}. "
                if send_alerts and report.alerts:
                    alerts_mod.send_alerts(report, email)
                    sent_msg += f"Сигналов отправлено: {len(report.alerts)}."

    audit.log("report_generated", client=report.client_name, period=report.period.human(),
              season=report.season, vehicles=len(report.vehicles), alerts=len(report.alerts))
    st.session_state["last_report"] = {
        "client": report.client_name, "period": report.period.human(), "stamp": stamp,
        "n": len(report.vehicles),
        "with_data": sum(1 for v in report.vehicles if v.has_data),
        "kpi": report.kpi, "sent_msg": sent_msg,
        "pptx": pptx_bytes, "html": html_bytes,
        "elapsed": monotonic() - started,
    }
    st.session_state["passport_ctx"] = {
        "client": report.client_name,
        "rows": [{
            "ТС": v.name, "Тип": vehicle_types.label(v.vehicle_type),
            "Марка": v.brand or "", "Модель": v.model or "",
            "Двигатель": v.engine_model or "", "Госномер": v.reg_number or "",
            "Норма л/100км": v.norm_l_per_100km or 0.0, "Норма л/мч": v.norm_l_per_mh or 0.0,
            "Факт л/100км": round(v.fuel_per_100km_calc or 0.0, 1),
            "Факт л/мч": round(v.fuel_per_motorhour or 0.0, 1),
        } for v in report.vehicles if v.has_data],
    }


def _render_last_report():
    """Отрисовать последний отчёт из session_state (переживает «Скачать»/rerun)."""
    r = st.session_state.get("last_report")
    if not r:
        return
    k = r["kpi"]
    elapsed = f" · за {r['elapsed']:.1f} с" if r.get("elapsed") else ""
    st.success(f"Готово: {r['n']} ТС (с данными {r['with_data']}), {r['period']}. "
               f"Клиент: {r['client']}{elapsed}.")
    if r.get("sent_msg"):
        st.info(r["sent_msg"])
    m = st.columns(4)
    m[0].metric("Пробег, км", f"{k.total_mileage_km:,.0f}".replace(",", " "))
    m[1].metric("Расход, л", f"{k.total_fuel_l:,.0f}".replace(",", " "))
    m[2].metric("Стоимость", f"{k.total_fuel_cost:,.0f} ₸".replace(",", " "))
    m[3].metric("Холостой ход", f"{k.idle_hours_share * 100:.0f}%")
    if k.vehicles_with_norm > 0:
        net = k.total_overrun_cost - k.total_economy_cost
        o = st.columns(3)
        o[0].metric("Перерасход", f"{k.total_overrun_cost:,.0f} ₸".replace(",", " "),
                    f"{k.vehicles_over_norm} ТС")
        o[1].metric("Экономия", f"{k.total_economy_cost:,.0f} ₸".replace(",", " "))
        o[2].metric("Сальдо", f"{net:,.0f} ₸".replace(",", " "))
    d = st.columns(2)
    d[0].download_button("⬇️ .pptx", r["pptx"], f"report_{r['stamp']}.pptx",
                         use_container_width=True)
    d[1].download_button("⬇️ .html", r["html"], f"report_{r['stamp']}.html",
                         mime="text/html", use_container_width=True)
    with st.expander("Предпросмотр HTML-отчёта", expanded=True):
        st.components.v1.html(r["html"].decode("utf-8"), height=700, scrolling=True)


def _apply_supplier_price(key, price, name, omni, with_track, email):
    """on_click-колбэк: обновить поле цены и сохранить клиента (до пересоздания виджета)."""
    st.session_state[key] = float(price)
    clients.save_client(name, base_url=omni["base_url"], login=omni["login"],
                        password=omni["password"], service=omni.get("service", ""),
                        fuel_price_kzt=float(price), with_track=with_track, email=email)
    audit.log("fuel_price_substituted", client=name, price_kzt=float(price),
              source="royal-petrol")


def _api_client(omni: dict):
    from omnicomm_report.api_client import OmnicommClient
    settings = Settings(base_url=omni["base_url"], login=omni["login"],
                        password=omni["password"], service=omni.get("service", ""))
    c = OmnicommClient(settings)
    c.login()
    return c


# --- Аутентификация и роли ---------------------------------------------------

_new_admin_pw = auth.ensure_admin()   # засеять админа при первом запуске
if _new_admin_pw:
    st.session_state["_admin_seed_pw"] = _new_admin_pw

if "user" not in st.session_state:
    st.title("🚚 Omnicomm Fleet Report — Вход")
    if st.session_state.get("_admin_seed_pw"):
        st.warning(f"Создан администратор: логин **admin**, пароль "
                   f"**{st.session_state['_admin_seed_pw']}** — войдите и смените.")
    lu = st.text_input("Логин", autocomplete="off")
    lp = st.text_input("Пароль", type="password", autocomplete="off")
    if st.button("Войти", type="primary"):
        role = auth.verify(lu, lp)
        if role:
            st.session_state["user"] = lu.strip()
            st.session_state["role"] = role
            audit.set_actor(lu.strip())
            audit.log("login", role=role)
            st.rerun()
        else:
            st.error("Неверный логин или пароль.")
    st.stop()

USER = st.session_state["user"]
ROLE = st.session_state["role"]
IS_ADMIN = auth.is_admin(ROLE)
audit.set_actor(USER)   # привязать все действия сессии к пользователю

# --- Шапка и выбор режима ----------------------------------------------------

st.title("🚚 Omnicomm Fleet Report — Платформа")
st.caption("Учётка и настройки клиента — один раз; дальше выбрал клиента, период, "
           "клик → отчёт с перерасходом/экономией по нормам.")

with st.sidebar:
    st.header("Навигация")
    role_label = "Администратор" if IS_ADMIN else "Менеджер"
    st.caption(f"👤 {USER} · {role_label}")
    if st.button("Выйти"):
        audit.log("logout", role=ROLE)
        for k in ("user", "role"):
            st.session_state.pop(k, None)
        st.rerun()
    saved = clients.list_clients(user=USER, role=ROLE)  # изоляция: свои/все
    # Менеджер: только формирование/просмотр отчётов. Админ: всё + пользователи.
    if IS_ADMIN:
        section = st.radio("Раздел",
                           ["📊 Отчёты", "🚛 Парк и клиенты", "⏱ Автоматизация"])
        if section == "📊 Отчёты":
            mode = st.radio("Экран", ["Отчёт по клиенту", "Отчёт из файла"])
        elif section == "🚛 Парк и клиенты":
            mode = st.radio("Экран",
                            ["Парк техники", "Шаблоны техники", "Новый клиент", "Пользователи"])
        else:
            mode = st.radio("Экран", ["Планировщик", "Журнал действий"])
    else:
        mode = st.radio("Экран", ["Отчёт по клиенту", "Отчёт из файла"])
    st.caption(f"Клиентов сохранено: {len(saved)}")


# --- Основной блок -----------------------------------------------------------

if mode == "Новый клиент":
    st.subheader("Добавить клиента")
    c1, c2 = st.columns(2)
    with c1:
        nc_name = st.text_input("Название клиента")
        nc_url = st.text_input("Адрес контура", value="https://kz.omnicomm.online")
        nc_login = st.text_input("Логин Omnicomm", autocomplete="off")
        nc_pass = st.text_input("Пароль Omnicomm", type="password", autocomplete="off")
    with c2:
        nc_service = st.text_input("Сервис", value="omnicomm")
        nc_price = st.number_input("Цена топлива, ₸/л", min_value=0.0,
                                   value=float(DEFAULT_FUEL_PRICE_KZT), step=10.0)
        nc_track = st.checkbox("GPS-карта точек погрузки", value=True)
        nc_email = st.text_input("E-mail для авторассылки (отчёты/сигналы)",
                                 placeholder="director@client.kz")
    st.caption("🔒 Пароль шифруется (Fernet) в gitignored-каталоге; запись "
               "привязывается к вашей учётке.")
    if st.button("💾 Сохранить клиента", type="primary",
                 disabled=not (nc_name and nc_login and nc_pass)):
        clients.save_client(nc_name, base_url=nc_url, login=nc_login,
                            password=nc_pass, service=nc_service,
                            fuel_price_kzt=nc_price, with_track=nc_track,
                            email=nc_email, owner=USER)
        audit.log("client_created", client=nc_name, contour=nc_url, owner=USER)
        st.success(f"Клиент «{nc_name}» сохранён. Переключитесь: Отчёты → «Отчёт по клиенту».")

elif mode == "Отчёт по клиенту":
    if not saved:
        st.info("Пока нет сохранённых клиентов. Добавьте в разделе «Парк и клиенты» → «Новый клиент».")
        st.stop()
    sel = st.selectbox("Клиент", saved)
    cfg = clients.load_client(sel, user=USER, role=ROLE)
    if not cfg:
        st.error("Нет доступа к этому клиенту.")
        st.stop()
    omni = cfg["omnicomm"]
    st.caption(f"Контур: {omni['base_url']} · логин: {omni['login'][:2]}•••")
    period = _pick_period()
    # Цена топлива — keyed session_state (чтобы кнопка «подставить» обновляла поле).
    sp_key = f"fuel_price__{sel}"
    if sp_key not in st.session_state:
        st.session_state[sp_key] = float(cfg.get("fuel_price_kzt") or DEFAULT_FUEL_PRICE_KZT)
    pc1, pc2 = st.columns(2)
    with pc1:
        fuel_price = st.number_input(
            "Цена топлива, ₸/л", min_value=0.0, step=10.0, key=sp_key,
            help="Меняется в любой момент; сохраняется как настройка клиента.",
        )
    with pc2:
        with_track = st.checkbox("GPS-карта точек погрузки",
                                 value=bool(cfg.get("with_track", False)))
        time_fund = st.number_input(
            "Фонд времени, ч/сутки на ТС", min_value=0.0, max_value=24.0,
            value=float(cfg.get("time_fund_hours_per_day") or 0), step=1.0,
            help="Нормативная смена (8, 12, 24…). 0 = коэффициент использования "
                 "считается только к календарному времени.")

    # Сверка цены ГСМ с поставщиком (Royal Petrol) + чек-поинт лето/зима.
    from omnicomm_report import fuel_price as _fp
    season_label = st.radio("Тип ДТ для сверки", ["Лето", "Зима"], horizontal=True)
    season = "winter" if season_label == "Зима" else "summer"
    ref = _fp.get_reference(season)  # кэш (6 ч); первый раз — загрузка с сайта
    if ref and ref.get("diesel"):
        chk = _fp.check_price(fuel_price, ref["diesel"])
        (st.warning if not chk["ok"] else st.caption)(
            f"⛽ Поставщик (Royal Petrol, ДТ {season_label.lower()}): "
            f"{ref['diesel']:.0f} ₸/л. {chk['message']}")
        if abs(fuel_price - ref["diesel"]) > 0.5:
            st.button(
                f"Подставить цену поставщика {ref['diesel']:.0f} ₸/л",
                on_click=_apply_supplier_price,
                args=(sp_key, ref["diesel"], sel, omni, with_track, cfg.get("email", "")))
    else:
        st.caption("⛽ Цену поставщика получить не удалось — сверка пропущена.")

    # Календарь цены ГСМ — учёт изменений стоимости по датам.
    with st.expander("🗓 Календарь цены ГСМ (учёт изменений по датам)"):
        st.caption("Если цена менялась внутри периода (напр. до 01.06 — 320 ₸, после — 340 ₸), "
                   "система берёт цену каждого дня и считает среднюю по периоду.")
        hist = price_history.load_history()
        if hist:
            st.table([{"С даты": e["date"], "Цена, ₸/л": e["price"]} for e in hist])
        else:
            st.caption("Календарь пуст — используется ручная цена выше.")
        pc1, pc2, pc3 = st.columns([1, 1, 1])
        with pc1:
            np_date = st.date_input("С даты", value=date.today(), key="pp_date")
        with pc2:
            np_price = st.number_input("Цена, ₸/л", min_value=0.0, value=float(fuel_price),
                                       step=5.0, key="pp_price")
        with pc3:
            st.write("")
            st.write("")
            if st.button("➕ Добавить цену"):
                price_history.add_price(np_date, np_price)
                audit.log("fuel_price_calendar_add", date=str(np_date), price=np_price)
                st.rerun()

    # Программа экономии: baseline + накопительный счётчик (Ф2, STRATEGY §4.2).
    with st.expander("💰 Программа экономии (baseline и счётчик)"):
        from omnicomm_report import savings as savings_mod
        bl = savings_mod.load_baseline(sel)
        if bl:
            r = bl.get("rates", {})
            st.success(
                f"Baseline заморожен {str(bl.get('frozen_at', ''))[:10]} "
                f"({bl.get('source_periods', 0)} пер., сезон {bl.get('season')}): "
                f"холостой ход {r.get('idle_share', 0) * 100:.0f}%, "
                f"движение {r.get('moving_l_per_100km', 0):.1f} л/100 км, "
                f"простой {r.get('idle_rate_l_h', 0):.1f} л/ч."
            )
            led = savings_mod.load_ledger(sel)
            cum_l, cum_kzt = savings_mod.cumulative(led)
            n_entries = len(led.get("entries", []))
            if n_entries:
                word = "экономия" if cum_kzt >= 0 else "перерасход к эталону"
                st.metric(f"Счётчик за {n_entries} пер. — {word}",
                          f"{abs(cum_kzt):,.0f} ₸".replace(",", " "),
                          delta=f"{cum_l:+,.0f} л".replace(",", " "))
            else:
                st.caption("Записей пока нет — счётчик пополнится при первом "
                           "отчёте за период ПОСЛЕ baseline-окна.")
        else:
            st.caption("Baseline не заморожен. Выберите эталонный диапазон "
                       "(период «как было», до программы) — ставки посчитаются "
                       "из истории отчётов и зафиксируются.")
        if IS_ADMIN:
            bc1, bc2, bc3 = st.columns([1, 1, 1])
            with bc1:
                b_from = st.date_input("Эталон с", value=date.today().replace(day=1),
                                       key="bl_from")
            with bc2:
                b_to = st.date_input("Эталон по", value=date.today(), key="bl_to")
            with bc3:
                st.write("")
                st.write("")
                if st.button("🧊 Заморозить baseline",
                             help="Пересчитает и перезапишет эталон из истории"):
                    from datetime import datetime as _dt, time as _time, timezone as _tz
                    df = _dt.combine(b_from, _time.min, tzinfo=_tz.utc)
                    dt_ = _dt.combine(b_to, _time.max, tzinfo=_tz.utc)
                    nb = savings_mod.freeze_from_history(sel, df, dt_)
                    if nb:
                        audit.log("baseline_frozen", client=sel,
                                  date_from=str(b_from), date_to=str(b_to),
                                  periods=nb.get("source_periods"))
                        st.rerun()
                    else:
                        st.error("Не заморожен: в истории нет отчётов за диапазон "
                                 "или наработка < 100 моточасов.")

    # Рассылка по email
    st.markdown("**Авторассылка на e-mail**")
    ec1, ec2, ec3 = st.columns([2, 1, 1])
    with ec1:
        email = st.text_input("E-mail получателя", value=cfg.get("email", ""),
                              placeholder="director@client.kz", label_visibility="collapsed")
    with ec2:
        send_report = st.checkbox("Отчёт", value=bool(cfg.get("email")))
    with ec3:
        send_alerts = st.checkbox("Сигналы", value=bool(cfg.get("email")))
    from omnicomm_report import mailer as _mailer
    if email and not _mailer.smtp_configured():
        st.caption("⚠️ SMTP не настроен (SMTP_HOST/USER/PASSWORD в .env) — письма не уйдут.")

    # Расписание авторассылки (встроенный планировщик)
    with st.expander("🗓 Расписание авторассылки (планировщик)"):
        sch = cfg.get("schedule") or {}
        s_en = st.checkbox("Включить авторассылку по расписанию", value=bool(sch.get("enabled")))
        sc1, sc2, sc3 = st.columns(3)
        freq_label = sc1.selectbox("Частота", ["Ежедневно", "Еженедельно", "Ежемесячно"],
                                   index={"daily": 0, "weekly": 1, "monthly": 2}.get(sch.get("freq", "monthly"), 2))
        freq = {"Ежедневно": "daily", "Еженедельно": "weekly", "Ежемесячно": "monthly"}[freq_label]
        s_hour = sc2.number_input("Час (UTC)", 0, 23, int(sch.get("hour", 6)))
        _PRESET_LABELS = {"last-day": "За прошлый день",
                          "last-week": "За прошлую неделю",
                          "last-month": "За прошлый месяц"}
        s_preset = sc3.selectbox(
            "Период отчёта", ["last-day", "last-week", "last-month"],
            index={"last-day": 0, "last-week": 1, "last-month": 2}.get(sch.get("preset", "last-month"), 2),
            format_func=lambda k: _PRESET_LABELS[k])
        s_day = sch.get("day", 1)
        s_wd = sch.get("weekday", 0)
        if freq == "weekly":
            s_wd = st.selectbox("День недели", list(range(7)),
                                format_func=lambda i: ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][i],
                                index=int(sch.get("weekday", 0)))
        elif freq == "monthly":
            s_day = st.number_input("День месяца (1–28)", 1, 28, int(sch.get("day", 1)))
        if st.button("💾 Сохранить расписание"):
            new_sch = {"enabled": s_en, "freq": freq, "hour": int(s_hour),
                       "preset": s_preset, "day": int(s_day), "weekday": int(s_wd),
                       "send_report": True, "send_alerts": True}
            clients.save_client(sel, base_url=omni["base_url"], login=omni["login"],
                                password=omni["password"], service=omni.get("service", ""),
                                fuel_price_kzt=fuel_price, with_track=with_track,
                                email=email, schedule=new_sch)
            audit.log("schedule_saved", client=sel, **new_sch)
            st.success("Расписание сохранено. Планировщик подхватит автоматически.")

    vehicles_filter = st.text_input("ID/госномера ТС через запятую (пусто = все)", value="")
    volume_m3 = st.number_input(
        "Вывезено за период, м³ (по данным полигона; 0 = не считать ₸/м³)",
        min_value=0.0, value=0.0, step=100.0,
        help="Топливная себестоимость вывоза ₸/м³ — для парков ТКО. "
             "Объём берётся из талонов весовой полигона за тот же период.")
    if (err := st.session_state.pop("gen_error_msg", None)):
        st.error(err)
    if _gen_clicked("api"):
        started = monotonic()
        try:
            with st.status("⏳ Формирую отчёт…", expanded=True) as status:
                # Сохранить изменённые настройки клиента (цена/трек/email/фонд).
                if (fuel_price != cfg.get("fuel_price_kzt")
                        or with_track != cfg.get("with_track")
                        or email != cfg.get("email", "")
                        or time_fund != float(cfg.get("time_fund_hours_per_day") or 0)):
                    clients.save_client(sel, base_url=omni["base_url"], login=omni["login"],
                                        password=omni["password"], service=omni.get("service", ""),
                                        fuel_price_kzt=fuel_price, with_track=with_track,
                                        email=email, time_fund_hours_per_day=time_fund)
                    audit.log("client_settings_saved", client=sel, fuel_price_kzt=fuel_price,
                              with_track=with_track, email=email, time_fund=time_fund)
                _stage(status, "Загрузка данных из Omnicomm…", started)
                client = _api_client(omni)
                ids = [x.strip() for x in vehicles_filter.split(",") if x.strip()] or None
                vehicles = data_loader.load_from_api(
                    client, period, ids, with_track=with_track)
                if not vehicles:
                    raise RuntimeError("Нет данных по ТС за выбранный период.")
                _stage(status, f"Загружено ТС: {len(vehicles)}. Проверка и аналитика…", started)
                vehicles = validator.validate(vehicles)
                price_eff, blended = price_history.price_for_period(
                    fuel_price, period.start, period.end)
                if blended:
                    _stage(status, f"Календарь цен: средняя {price_eff:.0f} ₸/л за период", started)
                rep = analytics.analyze(
                    vehicles, period, sel, source="api", fuel_price_kzt=price_eff,
                    previous_kpi=history.load_previous(sel, period),
                    norms=norms.load_norms(sel) or None, season=season,
                    time_fund_hours_per_day=time_fund, haul_volume_m3=volume_m3)
                rep.generated_at = datetime.now(timezone.utc)
                _finalize_and_store(rep, email=email, send_report=send_report,
                                    send_alerts=send_alerts, status=status, started=started)
                status.update(label=f"✅ Отчёт готов за {monotonic() - started:.1f} с",
                              state="complete", expanded=False)
        except Exception as exc:  # noqa: BLE001
            st.session_state["gen_error_msg"] = f"Ошибка: {exc}"
        finally:
            st.session_state["gen_running"] = None
        st.rerun()

    _render_last_report()   # рендер из session_state — переживает «Скачать»/rerun

    # Подсказка для авторассылки по расписанию (cron) с сохранённым e-mail.
    if cfg.get("email"):
        st.caption(
            "Авторассылка по расписанию (cron) — пример ежемесячно 1-го в 06:00:\n"
            f"`0 6 1 * * cd {os.getcwd()} && .venv/bin/python -m omnicomm_report "
            f"--source api --preset last-month --fuel-price {fuel_price:.0f} "
            f"--html --email {cfg['email']} --alert-email {cfg['email']}`"
        )

elif mode == "Отчёт из файла":
    up = st.file_uploader("Excel/CSV выгрузка Omnicomm", type=["xlsx", "xls", "csv"])
    client_name = st.text_input("Название клиента", value="Клиент")
    price = st.number_input("Цена топлива, ₸/л", min_value=0.0,
                            value=float(DEFAULT_FUEL_PRICE_KZT), step=10.0)
    period = _pick_period()
    # Файл нужно прочитать до перезапуска (после rerun загрузка может сброситься).
    up_bytes = up.getbuffer().tobytes() if up is not None else None
    up_name = up.name if up is not None else ""
    if (err := st.session_state.pop("gen_error_msg", None)):
        st.error(err)
    if _gen_clicked("file", disabled=up is None):
        started = monotonic()
        try:
            with st.status("⏳ Формирую отчёт…", expanded=True) as status:
                _stage(status, "Чтение файла…", started)
                with tempfile.TemporaryDirectory() as work:
                    path = os.path.join(work, up_name)
                    with open(path, "wb") as fh:
                        fh.write(up_bytes)
                    source = "csv" if up_name.lower().endswith(".csv") else "excel"
                    vehicles = data_loader.load(source, path=path)
                if not vehicles:
                    raise RuntimeError("В файле нет данных по ТС.")
                _stage(status, f"Прочитано ТС: {len(vehicles)}. Проверка и аналитика…", started)
                vehicles = validator.validate(vehicles)
                price_eff, _bl = price_history.price_for_period(price, period.start, period.end)
                report = analytics.analyze(vehicles, period, client_name, source=source,
                                           fuel_price_kzt=price_eff,
                                           norms=norms.load_norms(client_name) or None)
                report.generated_at = datetime.now(timezone.utc)
                _finalize_and_store(report, status=status, started=started)
                status.update(label=f"✅ Отчёт готов за {monotonic() - started:.1f} с",
                              state="complete", expanded=False)
        except Exception as exc:  # noqa: BLE001
            st.session_state["gen_error_msg"] = f"Ошибка: {exc}"
        finally:
            st.session_state["gen_running"] = None
        st.rerun()

    _render_last_report()   # рендер из session_state — переживает «Скачать»/rerun

elif mode == "Планировщик":
    from datetime import datetime as _dt, timezone as _tz

    from omnicomm_report import scheduler
    st.subheader("Планировщик авторассылки")
    alive = scheduler.heartbeat_alive()
    st.markdown(f"**Статус демона:** {'🟢 активен' if alive else '🔴 не запущен'}")
    if not alive:
        st.caption("Запуск демона на сервере: `python -m omnicomm_report.scheduler` "
                   "(держать процессом/в supervisor). Без него расписание не отрабатывает; "
                   "кнопка «Запустить сейчас» работает вручную в любом случае.")
    _FREQ = {"daily": "ежедневно", "weekly": "еженедельно", "monthly": "ежемесячно"}
    _PRESET = {"last-day": "за прошлый день", "last-week": "за прошлую неделю",
               "last-month": "за прошлый месяц"}
    rows = []
    for nm in clients.list_clients():
        c = clients.load_client(nm) or {}
        sch = c.get("schedule") or {}
        stt = scheduler.load_state(nm)
        rows.append({
            "Клиент": nm,
            "Расписание": (f"{_FREQ.get(sch.get('freq'), '—')} в {sch.get('hour', '—')}:00 UTC"
                           if sch.get("enabled") else "выключено"),
            "Период": _PRESET.get(sch.get("preset"), "—") if sch.get("enabled") else "—",
            "Цена топлива": f"{c.get('fuel_price_kzt', 0):.0f} ₸/л",
            "E-mail": c.get("email", "") or "—",
            "Последний прогон": (_dt.fromtimestamp(stt["last_run_ts"], _tz.utc)
                                 .strftime("%d.%m %H:%M") if stt.get("last_run_ts") else "—"),
            "Статус": stt.get("last_status", "—"),
        })
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info("Нет клиентов с расписанием. Настройте: Отчёты → «Отчёт по клиенту» → Расписание.")
    run_for = st.selectbox("Запустить вручную для клиента", clients.list_clients())
    if st.button("▶️ Запустить сейчас") and run_for:
        with st.spinner(f"Прогон «{run_for}»…"):
            res = scheduler.run_for_client(run_for)
        (st.success if res.get("ok") else st.error)(
            f"{run_for}: {res.get('message')} (период {res.get('period', '—')}, "
            f"сигналов {res.get('alerts', 0)})")

elif mode == "Парк техники":
    st.subheader("Парк техники — паспорта и нормы")
    st.caption("Список ТС подтягивается из Omnicomm. Заполните тип, марку/модель/"
               "двигатель и нормы (л/100 км, л/моточас) — по паспорту или по "
               "контрольным замерам. Сохраняется по клиенту и применяется в отчётах.")
    if not saved:
        st.info("Сначала добавьте клиента в «Новый клиент».")
        st.stop()
    sel = st.selectbox("Клиент", saved)
    fleet_key = f"fleet__{sel}"
    if st.button("🔄 Загрузить парк из Omnicomm"):
        try:
            cl = _api_client(clients.load_client(sel)["omnicomm"])
            st.session_state[fleet_key] = [v.get("name") for v in cl.list_vehicles()
                                           if v.get("name")]
            st.success(f"Загружено ТС: {len(st.session_state[fleet_key])}")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Omnicomm: {exc}")
    names = st.session_state.get(fleet_key)
    if not names:
        st.info("Нажмите «Загрузить парк из Omnicomm» — подтянем список ТС.")
    else:
        profs = vehicle_types.all_profiles()
        type_labels = [p.label for p in profs.values()]
        nrm = norms.load_norms(sel)
        rows = []
        for nm in names:
            d = nrm.get(nm, {})
            rows.append({
                "ТС": nm,
                "Тип": vehicle_types.label(d["type"]) if d.get("type") else "Прочее",
                "Марка": d.get("brand", ""), "Модель": d.get("model", ""),
                "Двигатель": d.get("engine", ""), "Госномер": d.get("reg_number", ""),
                "Норма л/100км": float(d.get("l_100km") or 0),
                "Норма л/мч": float(d.get("l_mh") or 0),
                "Норма по": d.get("source", "паспорт"),
                "Аренда ₸/мч": float(d.get("rate_kzt_per_mh") or 0),
            })
        ed = st.data_editor(
            rows, use_container_width=True, hide_index=True, key="fleet_editor",
            column_config={
                "ТС": st.column_config.TextColumn(disabled=True),
                "Тип": st.column_config.SelectboxColumn(options=type_labels),
                "Норма по": st.column_config.SelectboxColumn(options=["паспорт", "замер"]),
                "Норма л/100км": st.column_config.NumberColumn(min_value=0.0, step=1.0),
                "Норма л/мч": st.column_config.NumberColumn(min_value=0.0, step=0.5),
                "Аренда ₸/мч": st.column_config.NumberColumn(
                    min_value=0.0, step=500.0,
                    help="Ставка аренды для акта наработки (0 = ТС не в аренде)"),
            })
        st.caption(f"ТС в парке: {len(rows)}. Незаполненные нормы — ТС просто без "
                   "оценки перерасхода (не ошибка).")
        if st.button("💾 Сохранить парк"):
            label_to_key = {p.label: k for k, p in profs.items()}
            store = {}
            for r in ed:
                has = (r.get("Норма л/100км") or 0) > 0 or (r.get("Норма л/мч") or 0) > 0 \
                    or (r.get("Аренда ₸/мч") or 0) > 0 \
                    or r.get("Марка") or r.get("Модель") or r.get("Двигатель") \
                    or (r.get("Тип") and r.get("Тип") != "Прочее")
                if not has:
                    continue
                store[r["ТС"]] = {
                    "type": label_to_key.get(r.get("Тип")),
                    "brand": r.get("Марка") or "", "model": r.get("Модель") or "",
                    "engine": r.get("Двигатель") or "", "reg_number": r.get("Госномер") or "",
                    "l_100km": float(r.get("Норма л/100км") or 0) or None,
                    "l_mh": float(r.get("Норма л/мч") or 0) or None,
                    "source": r.get("Норма по") or "паспорт",
                    "rate_kzt_per_mh": float(r.get("Аренда ₸/мч") or 0) or None,
                }
            norms.save_norms(sel, store)
            audit.log("passports_saved", client=sel, vehicles=len(store),
                      via="fleet_editor")
            st.success(f"Сохранено {len(store)} ТС для «{sel}». Применится в отчётах.")

elif mode == "Шаблоны техники":
    st.subheader("Шаблоны типов техники")
    st.caption("Тип задаёт специфику расчёта: основной параметр (л/100 км для "
               "перевозок, л/моточас для работы на месте, «оба» для мусоровоза/"
               "поливомоечной). Правки сохраняются и применяются ко всем отчётам.")
    _METRICS = {"both": "оба (л/100км + л/моточас)", "l_per_mh": "л/моточас",
                "l_per_100km": "л/100 км"}
    profs = vehicle_types.all_profiles()
    trows = [{"Ключ": k, "Название": p.label,
              "Основной параметр": _METRICS.get(p.primary_metric, p.primary_metric),
              "Работа на месте": p.stationary_work, "Описание": p.note}
             for k, p in profs.items()]
    ed = st.data_editor(
        trows, use_container_width=True, hide_index=True, num_rows="dynamic",
        key="templates_editor",
        column_config={
            "Основной параметр": st.column_config.SelectboxColumn(options=list(_METRICS.values())),
            "Работа на месте": st.column_config.CheckboxColumn(),
        })
    if st.button("💾 Сохранить шаблоны"):
        rev = {v: k for k, v in _METRICS.items()}
        out = {}
        for r in ed:
            key = (r.get("Ключ") or "").strip()
            if not key:
                continue
            out[key] = {"label": r.get("Название") or key,
                        "primary_metric": rev.get(r.get("Основной параметр"), "both"),
                        "stationary_work": bool(r.get("Работа на месте")),
                        "note": r.get("Описание") or ""}
        vehicle_types.save_profiles(out)
        audit.log("templates_saved", actor="platform", types=len(out),
                  keys=list(out.keys()))
        st.success(f"Сохранено шаблонов: {len(out)}. Применятся в новых отчётах.")

elif mode == "Журнал действий":
    st.subheader("Журнал действий пользователя")
    st.caption("Аудит изменений (особенно шаблонов/типов/норм), прогонов и рассылок.")
    flt = st.selectbox("Клиент", ["(все)"] + clients.list_clients())
    entries = audit.recent(200, client="" if flt == "(все)" else flt)
    if not entries:
        st.info("Журнал пуст.")
    else:
        view = [{"Время (UTC)": e["ts"].replace("T", " "),
                 "Действие": audit.label(e["action"]),
                 "Клиент": e.get("client", "") or "—",
                 "Кто": e.get("actor", ""),
                 "Детали": ", ".join(f"{k}={v}" for k, v in (e.get("details") or {}).items())[:140]}
                for e in entries]
        st.dataframe(view, use_container_width=True, hide_index=True)

elif mode == "Пользователи":
    st.subheader("Пользователи и доступ")
    st.caption("Менеджер: формирование и просмотр отчётов. Администратор: настройки, "
               "парк, нормы, клиенты, планировщик, пользователи. Все действия логируются.")
    st.table(auth.list_users() or [{"username": "—", "role": "—"}])
    st.markdown("**Добавить / обновить пользователя**")
    uc1, uc2, uc3, uc4 = st.columns([2, 2, 1.4, 1])
    with uc1:
        nu_name = st.text_input("Логин", key="nu_name", autocomplete="off")
    with uc2:
        nu_pass = st.text_input("Пароль", type="password", key="nu_pass", autocomplete="off")
    with uc3:
        nu_role = st.selectbox("Роль", ["manager", "admin"], key="nu_role")
    with uc4:
        st.write("")
        st.write("")
        if st.button("💾 Сохранить", disabled=not (nu_name and nu_pass)):
            if auth.create_user(nu_name, nu_pass, nu_role):
                audit.log("user_created", user=nu_name, role=nu_role)
                st.success(f"Пользователь «{nu_name}» ({nu_role}) сохранён.")
                st.rerun()
    others = [u["username"] for u in auth.list_users() if u["username"] != USER]
    if others:
        dc1, dc2 = st.columns([2, 1])
        with dc1:
            del_user = st.selectbox("Удалить пользователя", others, key="del_user")
        with dc2:
            st.write("")
            st.write("")
            if st.button("🗑 Удалить", key="del_user_btn"):
                auth.delete_user(del_user)
                audit.log("user_deleted", user=del_user)
                st.rerun()


# --- Редактор паспортов и норм (enter-once, по клиенту) ----------------------
ctx = st.session_state.get("passport_ctx")
if IS_ADMIN and ctx and ctx["rows"]:
    st.divider()
    st.subheader(f"Паспорта и нормы — {ctx['client']} (введите один раз)")
    st.caption("Тип техники задаёт специфику расчёта (мусоровоз → л/моточас и площадки, "
               "самосвал → л/100 км). Нормы → авто-расчёт перерасхода/экономии в следующих отчётах.")
    type_labels = [p.label for p in vehicle_types.all_profiles().values()]
    edited = st.data_editor(
        ctx["rows"], use_container_width=True, hide_index=True, key="passport_editor",
        column_config={
            "ТС": st.column_config.TextColumn(disabled=True),
            "Тип": st.column_config.SelectboxColumn(options=type_labels),
            "Факт л/100км": st.column_config.NumberColumn(disabled=True),
            "Факт л/мч": st.column_config.NumberColumn(disabled=True),
            "Норма л/100км": st.column_config.NumberColumn(min_value=0.0, step=1.0),
            "Норма л/мч": st.column_config.NumberColumn(min_value=0.0, step=0.5),
        },
    )
    if st.button("💾 Сохранить паспорта клиента"):
        label_to_key = {p.label: k for k, p in vehicle_types.all_profiles().items()}
        store = {}
        for r in edited:
            has_norm = (r.get("Норма л/100км") or 0) > 0 or (r.get("Норма л/мч") or 0) > 0
            has_passport = r.get("Тип") or r.get("Марка") or r.get("Модель") or r.get("Двигатель")
            if not (has_norm or has_passport):
                continue
            store[r["ТС"]] = {
                "type": label_to_key.get(r.get("Тип"), None),
                "brand": r.get("Марка") or "", "model": r.get("Модель") or "",
                "engine": r.get("Двигатель") or "", "reg_number": r.get("Госномер") or "",
                "l_100km": float(r.get("Норма л/100км") or 0) or None,
                "l_mh": float(r.get("Норма л/мч") or 0) or None,
            }
        norms.save_norms(ctx["client"], store)
        audit.log("passports_saved", client=ctx["client"], vehicles=len(store),
                  items=[{"тс": k, "тип": v["type"], "л100": v["l_100km"], "лмч": v["l_mh"]}
                         for k, v in list(store.items())[:30]])
        st.success(f"Сохранено {len(store)} паспортов для «{ctx['client']}». "
                   "Сформируйте отчёт снова — применятся типы и нормы.")
