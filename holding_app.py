"""Holding-портал (Streamlit): вход по учётке → пользователь видит ТОЛЬКО свои ДЗО.

Конфиденциальность между ДЗО (docs/holding-architecture.md §8) реализована на входе:
после логина scope доступа = поддерево узла `dim_org`, к которому привязан пользователь
(`auth.user_org` → `org.OrgTree.visible_scope`). admin/руководитель холдинга — весь КАП.
Выбор организации ограничен доступными, и перед рендером доступ перепроверяется
(defense-in-depth: UI-ограничение само по себе не защита).

Источник иерархии — сохранённый реестр (`data/org_registry.json`), который пишет
holding-прогон (`python -m omnicomm_report holding … --registry data/org_registry.json`).
Данные ТС тянутся из Omnicomm по периоду (креды из .env). Демо-режим — синтетика.

Раскладка дашборда (для руководства, IA: docs/IA_dashboard_dzo.md):
шапка-топлайн холдинга → светофор-плитки ДЗО (где теряем) → executive-сводка
выбранного узла (потери / куда уходят / что делать) → детали в экспандерах.

Запуск:  streamlit run holding_app.py
"""

from __future__ import annotations

import copy
import os
import sys
import tempfile
from datetime import date, datetime, time, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

import altair as alt  # noqa: E402
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from omnicomm_report import (  # noqa: E402
    auth, config, dashboard, demo_data, economics, holding, org as org_mod, rollup)
from omnicomm_report.config import Settings, load_env_file  # noqa: E402
from omnicomm_report.models import ReportPeriod  # noqa: E402
from omnicomm_report.org import DEFAULT_ORG_REGISTRY, OrgLevel  # noqa: E402

st.set_page_config(page_title="Holding-портал автопарка", layout="wide")
load_env_file()


# --- Логин --------------------------------------------------------------------

_seed_pw = auth.ensure_admin()
if _seed_pw:
    st.session_state["_admin_seed_pw"] = _seed_pw

if "user" not in st.session_state:
    st.title("Holding-портал автопарка")
    if st.session_state.get("_admin_seed_pw"):
        st.warning(f"Создан админ. Пароль: **{st.session_state['_admin_seed_pw']}** — "
                   "войдите и смените.")
    lu = st.text_input("Логин", autocomplete="off")
    lp = st.text_input("Пароль", type="password", autocomplete="off")
    if st.button("Войти"):
        info = auth.authenticate(lu, lp)
        if info:
            st.session_state["user"] = info["username"]
            st.session_state["role"] = info["role"]
            st.session_state["org_id"] = info["org_id"]
            st.rerun()
        else:
            st.error("Неверный логин или пароль")
    st.stop()

USER = st.session_state["user"]
ROLE = st.session_state["role"]
ORG_ID = st.session_state.get("org_id")
IS_ADMIN = auth.is_admin(ROLE)


# --- Реестр организаций -------------------------------------------------------

@st.cache_data(show_spinner=False)
def _load_registry(path: str, mtime: float):
    """Реестр из JSON. mtime в ключе кэша → подхватывает обновление файла."""
    return org_mod.load_org_registry(path)


# Демо-режим: синтетический холдинг КАП без API (пока нет боевой учётки Omnicomm).
DEMO_MODE = st.sidebar.checkbox(
    "Демо-режим (без API)", value=True,
    help="Синтетический холдинг КАП для показа работы системы. "
         "Снимите галочку, когда подключите боевую учётку Omnicomm.")

if DEMO_MODE:
    registry = demo_data.build_demo_registry()
else:
    # Предпочитаем SQLite-реестр, если он есть; иначе JSON (диспетч в org.load_org_registry).
    _REG_CANDIDATES = [os.path.join("data", "org_registry.db"), DEFAULT_ORG_REGISTRY]
    _reg_path = next((p for p in _REG_CANDIDATES if os.path.exists(p)), None)
    registry = (_load_registry(_reg_path, os.path.getmtime(_reg_path))
                if _reg_path else None)

with st.sidebar:
    st.markdown(f"**{USER}** · {'админ' if IS_ADMIN else 'ДЗО'}")
    if not IS_ADMIN and ORG_ID:
        node = registry.tree.get(ORG_ID) if registry else None
        st.caption(f"Доступ: {node.name if node else ORG_ID} и подорганизации")
    if st.button("Выйти"):
        for k in ("user", "role", "org_id"):
            st.session_state.pop(k, None)
        st.rerun()

if registry is None:
    st.info("Реестр организаций не найден. Сначала выполните holding-прогон, "
            "сохранив реестр (SQLite или JSON):\n\n"
            "`python -m omnicomm_report holding --demo --preset last-week "
            "--registry data/org_registry.db`")
    st.stop()

tree = registry.tree

# Доступные пользователю организации (только его поддерево; admin — все).
options = dashboard.accessible_orgs(
    tree, org_id=ORG_ID, all_access=IS_ADMIN,
    levels=(OrgLevel.HOLDING, OrgLevel.DZO, OrgLevel.SUB_DZO))
if not options:
    st.warning("Нет доступных организаций для вашей учётной записи.")
    st.stop()


# --- Период (сайдбар) ---------------------------------------------------------
with st.sidebar:
    st.divider()
    st.caption("ПЕРИОД")
    today = date.today()
    d_from = st.date_input("С", value=today - timedelta(days=7))
    d_to = st.date_input("По", value=today - timedelta(days=1))
    fuel_price = st.number_input("Цена топлива, ₸/л", min_value=0.0, value=320.0, step=10.0)

if d_to < d_from:
    st.error("Период задан неверно: «По» раньше «С».")
    st.stop()

period = ReportPeriod(
    start=datetime.combine(d_from, time.min, tzinfo=timezone.utc),
    end=datetime.combine(d_to, time.max, tzinfo=timezone.utc))


# --- Данные -------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def _load_fleet(demo: bool, start_ts: int, end_ts: int, _vehicle_org: dict):
    """Сырой парк за период (кэш по режиму/датам). `_vehicle_org` не влияет на ключ."""
    p = ReportPeriod(start=datetime.fromtimestamp(start_ts, timezone.utc),
                     end=datetime.fromtimestamp(end_ts, timezone.utc))
    if demo:
        veh = demo_data.demo_fleet(p)
    else:
        from omnicomm_report.api_client import OmnicommClient
        client = OmnicommClient(Settings.from_env())
        client.login()
        _, veh = holding.fetch_fleet(client, p)
    org_mod.assign_org_ids(veh, _vehicle_org)
    return veh


with st.spinner("Сборка дашборда…" if DEMO_MODE else "Запрос данных из Omnicomm…"):
    try:
        # deepcopy: analyze/compute_kpi мутируют ТС (фильтр скорости, аномалии),
        # а роллап гоняет их по перекрывающимся поддеревьям — кэш не портим.
        vehicles = copy.deepcopy(
            _load_fleet(DEMO_MODE, period.start_ts, period.end_ts, registry.vehicle_org))
    except Exception as exc:  # noqa: BLE001
        st.error(f"Не удалось получить данные из Omnicomm: {exc}\n\n"
                 "Проверьте креды в .env (LOGIN/PASSWORD/SERVICE) или включите демо-режим.")
        st.stop()
    kpi_tree = rollup.build_org_kpi_tree(
        vehicles, tree, fuel_price_kzt=fuel_price, vehicle_org=registry.vehicle_org)


# --- Выбор узла (drill через session_state) -----------------------------------
_default_org = ORG_ID if (ORG_ID and not IS_ADMIN) else "holding"
if not tree.exists(_default_org):
    _default_org = options[0].org_id
sel_id = st.session_state.setdefault("sel_org", _default_org)
_visible = tree.visible_scope(ORG_ID, all_access=IS_ADMIN)
if sel_id not in _visible or not tree.exists(sel_id):
    sel_id = _default_org
    st.session_state["sel_org"] = sel_id


def _flatten(nodes, acc):
    for n in nodes:
        acc[n.org.org_id] = n
        _flatten(n.children, acc)
    return acc


kpi_by_id = _flatten(kpi_tree, {})
_root_id = "holding" if (IS_ADMIN or not ORG_ID) else ORG_ID
root_node = kpi_by_id.get(_root_id) or (kpi_tree[0] if kpi_tree else None)
sel_node = kpi_by_id.get(sel_id)


# --- Форматтеры и помощники ---------------------------------------------------
def _money(v: float) -> str:
    return f"{round(v or 0):,.0f}".replace(",", " ") + " ₸"


def _money_short(v: float) -> str:
    """Деньги для руководства: 8.0 млн ₸ / 810 тыс ₸."""
    v = v or 0
    if abs(v) >= 1_000_000:
        return f"{v / 1_000_000:.1f} млн ₸"
    if abs(v) >= 1_000:
        return f"{v / 1_000:.0f} тыс ₸"
    return f"{round(v)} ₸"


def _num(v: float, nd: int = 1) -> str:
    return f"{(v or 0):,.{nd}f}".replace(",", " ")


_LEVEL_ICON = {"holding": "🏢", "dzo": "🏭", "sub_dzo": "📍", "contractor": "🔧"}

# Отчёт+экономика на узел (мемо в пределах прогона; deepcopy — analyze/compute_kpi
# мутируют ТС, а узлы делят перекрывающиеся поддеревья).
_report_cache: dict = {}


def _report_for(oid: str):
    if oid not in _report_cache:
        rep = dashboard.build_org_report(
            oid, copy.deepcopy(vehicles), period, tree,
            vehicle_org=registry.vehicle_org, fuel_price_kzt=fuel_price)
        _report_cache[oid] = (rep, economics.build_economics(rep))
    return _report_cache[oid]


def _actions(rep, eco) -> list[str]:
    """Что делать — рекомендации отчёта, иначе вывод из данных."""
    if rep.recommendations:
        return rep.recommendations[:3]
    out = []
    big = [v for v in rep.vehicles if v.has_data and (v.overrun_cost_kzt or 0) >= 100_000]
    if big:
        out.append(f"{len(big)} машин с перерасходом >100 тыс ₸ — разобрать режим/нормы.")
    if rep.kpi.idle_hours_share > 0.25 and eco.total_potential_kzt > 0:
        out.append(f"Холостой ход {rep.kpi.idle_hours_share * 100:.0f}% → цель 20%: "
                   f"потенциал {_money_short(eco.total_potential_kzt)}.")
    if not out:
        out.append("Критичных отклонений за период нет — держать режим.")
    return out


def _tile_emoji(pos: int, total: int) -> str:
    """Светофор по рангу потерь среди соседей: верхняя треть 🔴, нижняя 🟢."""
    if total <= 2:
        return ["🔴", "🟢"][min(pos, 1)]
    if pos < total / 3:
        return "🔴"
    if pos < 2 * total / 3:
        return "🟠"
    return "🟢"


def _render_summary(node):
    """Executive-сводка узла: 3 числа → куда уходят → что делать → детали."""
    if node is None:
        st.info("Выберите организацию.")
        return
    oid = node.org.org_id
    rep, eco = _report_for(oid)
    k = rep.kpi

    crumbs = " › ".join([a.name for a in tree.ancestors(oid)] + [node.org.name])
    c1, c2 = st.columns([4, 1])
    c1.markdown(f"#### {crumbs}")
    if root_node and oid != root_node.org.org_id:
        if c2.button("↑ Ко всему холдингу", width="stretch"):
            st.session_state["sel_org"] = root_node.org.org_id
            st.rerun()
    st.caption(f"{rep.period.human()} · {node.vehicle_count} ТС "
               f"(с данными {k.vehicles_with_data}/{k.vehicles_total} · "
               f"мобильные {k.mobile_count} / спецтехника {k.stationary_count})")
    if k.vehicles_with_data == 0:
        st.warning("Нет ТС с данными за период.")
        return

    s = st.columns(3)
    s[0].metric("Потери, на кот. можно влиять", _money_short(eco.total_existing_kzt))
    s[1].metric("Холостой ход", f"{k.idle_hours_share * 100:.0f}%")
    s[2].metric("Перерасход к нормам", _money_short(k.total_overrun_cost))

    g1, g2 = st.columns(2)
    with g1:
        st.markdown("**Куда уходят деньги**")
        if k.fuel_price_kzt and eco.buckets:
            for bk in sorted(eco.buckets, key=lambda b: b.existing_kzt, reverse=True)[:4]:
                tag = " ≈" if bk.is_estimate else ""
                st.markdown(f"- {bk.label}{tag} — **{_money_short(bk.existing_kzt)}**")
        else:
            st.caption("Цена топлива не задана — деньги не считаются.")
    with g2:
        st.markdown("**Что делать**")
        for act in _actions(rep, eco):
            st.markdown(f"- {act}")

    # Безопасность · скоростной режим (для КАП — ключевое, как в их Power BI)
    st.markdown("**🚦 Безопасность · скоростной режим**")
    sc = st.columns(3)
    sc[0].metric("Пробег с превышением", f"{k.speeding_mileage_share * 100:.0f}%")
    sc[1].metric("Макс. скорость", f"{k.max_speed_kmh:.0f} км/ч")
    spd = sorted(
        (v for v in rep.vehicles if v.has_data and v.mileage_km
         and (v.speeding_mileage_km or 0) / (v.mileage_km or 1) >= config.ALERT_SPEEDING_SHARE),
        key=lambda v: (v.speeding_mileage_km or 0) / (v.mileage_km or 1), reverse=True)
    sc[2].metric("ТС с превышениями", f"{len(spd)}")
    if spd:
        st.caption("Чаще превышают: " + " · ".join(
            f"{v.name} ({(v.speeding_mileage_km / v.mileage_km) * 100:.0f}%)"
            for v in spd[:3]))
    else:
        st.caption("ТС с превышением >10% пробега за период нет.")

    # --- Детали (свёрнуто) ---
    st.divider()
    active = [v for v in rep.vehicles if v.has_data and (v.fuel_l or 0) > 0]

    with st.expander("🚛 Первоочередные ТС"):
        if eco.worst_vehicles:
            st.dataframe(pd.DataFrame(
                [{"ТС": nm, "Потенциал экономии, ₸": round(val)}
                 for nm, val in eco.worst_vehicles]),
                hide_index=True, width="stretch")
        else:
            st.caption("Нет ТС с заметным потенциалом экономии за период.")

    with st.expander("📈 Телеметрия и расход по ТС"):
        t = st.columns(3)
        t[0].markdown("**⛽ Топливо**")
        t[0].metric("Всего, л", _num(k.total_fuel_l))
        t[0].metric("Мобильные, л/100км", _num(k.mobile_fuel_per_100km))
        t[0].metric("Удельно, ₸/км", _num(k.fuel_cost_per_km))
        t[1].markdown("**⚙️ Двигатель / моточасы**")
        t[1].metric("Моточасы", _num(k.total_engine_hours))
        t[1].metric("Холостой ход, ч", _num(k.total_idle_hours))
        t[1].metric("Спец., л/моточас", _num(k.weighted_fuel_per_motorhour))
        t[2].markdown("**📊 Использование**")
        t[2].metric("Календарное", f"{k.utilization_calendar * 100:.0f}%")
        t[2].metric("Парк: моб./спец.", f"{k.mobile_count} / {k.stationary_count}")
        if active:
            top = sorted(active, key=lambda v: v.fuel_l or 0, reverse=True)[:10]
            cdf = pd.DataFrame([{
                "ТС": (v.name or v.vehicle_id)[:30],
                "Топливо, л": round(v.fuel_l or 0, 1),
                "Класс": "Спецтехника" if v.is_stationary else "Мобильный",
            } for v in top])
            st.altair_chart(alt.Chart(cdf).mark_bar().encode(
                x=alt.X("Топливо, л:Q"),
                y=alt.Y("ТС:N", sort="-x", title=None),
                color=alt.Color("Класс:N", scale=alt.Scale(
                    domain=["Мобильный", "Спецтехника"],
                    range=["#2563eb", "#f59e0b"])),
                tooltip=["ТС", "Топливо, л", "Класс"]).properties(height=300),
                width="stretch")

    with st.expander(f"⚠ Сигналы ({len(rep.alerts)})"):
        if rep.alerts:
            for al in rep.alerts:
                st.warning(al, icon="⚠️")
        else:
            st.success("Сигналов за период нет.", icon="✅")

    if node.children:
        with st.expander("🏭 Раскладка по под-организациям"):
            for ch in node.children:
                _, ceco = _report_for(ch.org.org_id)
                row = st.columns([3, 1, 2, 1, 1])
                row[0].write(f"{_LEVEL_ICON.get(ch.org.level.value, '•')} {ch.org.name}")
                row[1].write(f"{ch.vehicle_count} ТС")
                row[2].write(_money_short(ceco.total_existing_kzt))
                row[3].write(f"{ch.kpi.idle_hours_share * 100:.0f}%")
                if row[4].button("Открыть", key=f"drill-{ch.org.org_id}"):
                    st.session_state["sel_org"] = ch.org.org_id
                    st.rerun()

    with st.expander("📄 Полный отчёт и экспорт"):
        with tempfile.TemporaryDirectory() as tmp:
            out = dashboard.render_org_report(rep, tmp)
            html = open(out["html"], encoding="utf-8").read()
        st.download_button("Скачать HTML", data=html.encode("utf-8"),
                           file_name=f"dashboard_{oid}.html", mime="text/html")
        st.components.v1.html(html, height=600, scrolling=True)


# --- Раскладка: обзор холдинга сверху → сводка выбранного ----------------------
st.title("Автопарк холдинга" + ("  ·  ДЕМО" if DEMO_MODE else ""))

if root_node is None:
    st.warning("Нет данных по доступным организациям за период.")
    st.stop()

# Шапка: топлайн корня (весь доступный холдинг)
_root_rep, _root_eco = _report_for(root_node.org.org_id)
_rk = _root_rep.kpi
hcol = st.columns([2, 1, 1])
hcol[0].markdown(f"### {root_node.org.name}")
hcol[0].caption(f"{period.human()} · {root_node.vehicle_count} ТС")
hcol[1].metric("Топливо за период", _money_short(_rk.total_fuel_cost))
_share = _root_eco.total_existing_kzt / max(1.0, _rk.total_fuel_cost) * 100
hcol[2].metric("Потери, на кот. можно влиять",
               _money_short(_root_eco.total_existing_kzt),
               f"{_share:.0f}% бюджета топлива", delta_color="off")

# Светофор по организациям (дети корня) — где теряем, клик → детали
if root_node.children:
    st.markdown("##### Где теряем — по организациям · клик открывает детали")
    _kids = root_node.children
    _kid_eco = {c.org.org_id: _report_for(c.org.org_id)[1] for c in _kids}
    _order = sorted(range(len(_kids)),
                    key=lambda i: _kid_eco[_kids[i].org.org_id].total_existing_kzt,
                    reverse=True)
    _rank = {idx: pos for pos, idx in enumerate(_order)}
    _per_row = 4
    for _start in range(0, len(_kids), _per_row):
        cols = st.columns(_per_row)
        for _j in range(_per_row):
            _i = _start + _j
            if _i >= len(_kids):
                continue
            ch = _kids[_i]
            ceco = _kid_eco[ch.org.org_id]
            emoji = _tile_emoji(_rank[_i], len(_kids))
            with cols[_j].container(border=True):
                mark = "● " if ch.org.org_id == sel_id else ""
                st.markdown(f"{emoji} **{mark}{ch.org.name}**")
                st.markdown(f"### {_money_short(ceco.total_existing_kzt)}")
                st.caption(f"потери · хол.ход {ch.kpi.idle_hours_share * 100:.0f}% "
                           f"· превыш {ch.kpi.speeding_mileage_share * 100:.0f}% "
                           f"· {ch.vehicle_count} ТС")
                if st.button("Открыть", key=f"tile-{ch.org.org_id}", width="stretch"):
                    st.session_state["sel_org"] = ch.org.org_id
                    st.rerun()

st.divider()
_render_summary(sel_node)
