"""Holding-портал (Streamlit): вход по учётке → пользователь видит ТОЛЬКО свои ДЗО.

Конфиденциальность между ДЗО (docs/holding-architecture.md §8) реализована на входе:
после логина scope доступа = поддерево узла `dim_org`, к которому привязан пользователь
(`auth.user_org` → `org.OrgTree.visible_scope`). admin/руководитель холдинга — весь КАП.
Выбор организации ограничен доступными, и перед рендером доступ перепроверяется
(defense-in-depth: UI-ограничение само по себе не защита).

Источник иерархии — сохранённый реестр (`data/org_registry.json`), который пишет
holding-прогон (`python -m omnicomm_report holding … --registry data/org_registry.json`).
Данные ТС тянутся из Omnicomm по периоду (креды из .env).

Запуск:  streamlit run holding_app.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import date, datetime, time, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

import streamlit as st  # noqa: E402

from omnicomm_report import auth, dashboard, holding, org as org_mod  # noqa: E402
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


registry = None
if os.path.exists(DEFAULT_ORG_REGISTRY):
    registry = _load_registry(DEFAULT_ORG_REGISTRY, os.path.getmtime(DEFAULT_ORG_REGISTRY))

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
            "сохранив реестр:\n\n"
            "`python -m omnicomm_report holding --demo --preset last-week "
            "--registry data/org_registry.json`")
    st.stop()

tree = registry.tree

# Доступные пользователю организации (только его поддерево; admin — все).
options = dashboard.accessible_orgs(
    tree, org_id=ORG_ID, all_access=IS_ADMIN,
    levels=(OrgLevel.HOLDING, OrgLevel.DZO, OrgLevel.SUB_DZO))
if not options:
    st.warning("Нет доступных организаций для вашей учётной записи.")
    st.stop()


# --- Выбор и параметры --------------------------------------------------------

st.title("Дашборд автопарка по организации")

label_by_id = {o.org_id: f"{o.name}  ·  {o.level.value}" for o in options}
sel_id = st.selectbox("Организация", options=[o.org_id for o in options],
                      format_func=lambda i: label_by_id.get(i, i))

c1, c2, c3 = st.columns(3)
today = date.today()
d_from = c1.date_input("С", value=today - timedelta(days=7))
d_to = c2.date_input("По", value=today - timedelta(days=1))
fuel_price = c3.number_input("Цена топлива, ₸/л", min_value=0.0, value=320.0, step=10.0)

if st.button("Сформировать дашборд", type="primary"):
    # Defense-in-depth: перепроверяем доступ, не полагаясь на ограничение списка.
    if not (IS_ADMIN or (ORG_ID and tree.can_view(ORG_ID, sel_id))):
        st.error("Нет доступа к этой организации.")
        st.stop()

    period = ReportPeriod(
        start=datetime.combine(d_from, time.min, tzinfo=timezone.utc),
        end=datetime.combine(d_to, time.max, tzinfo=timezone.utc))

    with st.spinner("Запрос данных из Omnicomm и сборка дашборда…"):
        try:
            from omnicomm_report.api_client import OmnicommClient
            client = OmnicommClient(Settings.from_env())
            client.login()
            _, vehicles = holding.fetch_fleet(client, period)
        except Exception as exc:  # noqa: BLE001
            st.error(f"Не удалось получить данные из Omnicomm: {exc}\n\n"
                     "Проверьте креды в .env (LOGIN/PASSWORD/SERVICE).")
            st.stop()

        org_mod.assign_org_ids(vehicles, registry.vehicle_org)
        report = dashboard.build_org_report(
            sel_id, vehicles, period, tree, vehicle_org=registry.vehicle_org,
            fuel_price_kzt=fuel_price)

        if not report.vehicles:
            st.warning("По этой организации нет ТС с данными за период.")
            st.stop()

        with tempfile.TemporaryDirectory() as tmp:
            out = dashboard.render_org_report(report, tmp)
            html = open(out["html"], encoding="utf-8").read()

    st.success(f"«{report.client_name}» — {report.kpi.vehicles_total} ТС за период")
    st.components.v1.html(html, height=800, scrolling=True)
    st.download_button("Скачать HTML", data=html.encode("utf-8"),
                       file_name=f"dashboard_{sel_id}.html", mime="text/html")
