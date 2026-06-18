"""Holding-слой: дашборд/отчёт на конкретное ДЗО (срез поддерева).

Дашборд ДЗО — это тот же конвейер, что и в single-client режиме
(`analytics.analyze → charts.build_charts → report_builder.build_html/pptx`),
но на ТС **поддерева** узла `dim_org`, с `client_name` = именем организации.
Поэтому весь движок (экономика топлива, типы ТС, чистка, нормы, графики)
переиспользуется без изменений.

Доступ: пользователь рендерит/видит только то, что в его scope — своё
поддерево (`org.OrgTree.visible_scope`); admin/руководитель холдинга — весь КАП.
"""

from __future__ import annotations

import os
import re
from typing import Optional

from . import analytics, charts, report_builder
from .models import FleetReport, ReportPeriod
from .org import OrgLevel, OrgTree


def _slug(s: str) -> str:
    s = re.sub(r"\s+", "_", (s or "org").strip().lower())
    return re.sub(r"[^\w\-]", "", s, flags=re.UNICODE) or "org"


def vehicles_for_org(
    org_id: str,
    vehicles: list,
    tree: OrgTree,
    vehicle_org: Optional[dict[str, str]] = None,
) -> list:
    """ТС поддерева организации (включая под-ДЗО и подрядчиков)."""
    ids = tree.subtree_ids(org_id)
    vehicle_org = vehicle_org or {}
    out = []
    for v in vehicles:
        oid = getattr(v, "org_id", None) or vehicle_org.get(getattr(v, "vehicle_id", None))
        if oid and oid in ids:
            out.append(v)
    return out


def build_org_report(
    org_id: str,
    vehicles: list,
    period: ReportPeriod,
    tree: OrgTree,
    *,
    vehicle_org: Optional[dict[str, str]] = None,
    client_name: Optional[str] = None,
    fuel_price_kzt: float = 0.0,
    source: str = "api",
    season: str = "summer",
    norms: Optional[dict] = None,
    **analyze_kwargs,
) -> FleetReport:
    """Собрать `FleetReport` для ДЗО по ТС его поддерева (переиспользует analyze)."""
    node = tree.get(org_id)
    name = client_name or (node.name if node else org_id)
    subset = vehicles_for_org(org_id, vehicles, tree, vehicle_org)
    return analytics.analyze(
        subset, period, name, source=source, fuel_price_kzt=fuel_price_kzt,
        norms=norms, season=season, **analyze_kwargs,
    )


def render_org_report(
    report: FleetReport,
    out_dir: str,
    *,
    basename: str = "dashboard",
    html: bool = True,
    pptx: bool = False,
) -> dict[str, str]:
    """Отрисовать отчёт ДЗО: графики + HTML и/или PPTX. Возвращает {fmt: path}."""
    os.makedirs(out_dir, exist_ok=True)
    chart_paths = charts.build_charts(report, out_dir)
    out: dict[str, str] = {}
    if html:
        out["html"] = report_builder.build_html(
            report, chart_paths, os.path.join(out_dir, f"{basename}.html"))
    if pptx:
        out["pptx"] = report_builder.build_pptx(
            report, chart_paths, os.path.join(out_dir, f"{basename}.pptx"))
    return out


def render_for_scope(
    viewer_org_id: Optional[str],
    vehicles: list,
    period: ReportPeriod,
    tree: OrgTree,
    out_dir: str,
    *,
    all_access: bool = False,
    levels: Optional[tuple[OrgLevel, ...]] = None,
    vehicle_org: Optional[dict[str, str]] = None,
    html: bool = True,
    pptx: bool = False,
    **report_kwargs,
) -> dict[str, dict[str, str]]:
    """Отрендерить дашборды по всем организациям в scope пользователя.

    Конфиденциальность: рендерим строго в пределах `visible_scope` пользователя —
    чужие ДЗО недоступны. `levels` ограничивает уровни (напр. только `DZO`);
    None → все узлы scope, у которых есть ТС. Узлы без ТС пропускаем.

    Возвращает `{org_id: {fmt: path}}`.
    """
    scope = tree.visible_scope(viewer_org_id, all_access=all_access)
    results: dict[str, dict[str, str]] = {}
    for oid in scope:
        node = tree.get(oid)
        if levels and node and node.level not in levels:
            continue
        report = build_org_report(
            oid, vehicles, period, tree, vehicle_org=vehicle_org, **report_kwargs)
        if not report.vehicles:                       # нет ТС в поддереве — пропуск
            continue
        results[oid] = render_org_report(
            report, os.path.join(out_dir, _slug(node.name if node else oid)),
            html=html, pptx=pptx)
    return results
