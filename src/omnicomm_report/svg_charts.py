"""Рукописные инлайн-SVG «геройские» графики для HTML-отчёта (Фаза 2 визуализации).

Только для HTML-отчёта (вектор, печать в PDF, 0 зависимостей). Для .pptx графики
по-прежнему строит matplotlib (`charts.py`). Эти функции возвращают строку SVG,
готовую к встраиванию в HTML; при нехватке данных — пустую строку.

Стиль — «editorial financial dossier»: фирменные синий/янтарь, мягкая глубина через
градиенты, числа крупно (serif), классы-хуки для оркестрованной анимации на загрузке
(CSS в шапке отчёта; print/reduced-motion её отключают).
"""

from __future__ import annotations

from html import escape
from typing import Optional

from .models import FleetKPI, FleetReport

# Фирменная палитра (зеркало report_builder/charts).
PRIMARY = "#2F5C8F"
PRIMARY_D = "#244A73"
ACCENT = "#C8893F"
ACCENT_D = "#A86F2C"
SECONDARY = "#7E93AB"
TEXT = "#2B2B2B"
MUTED = "#8A8A8A"
TRACK = "#EEF1F5"
GRID = "#D9DEE6"

SERIF = "Georgia, 'Iowan Old Style', 'Times New Roman', serif"
SANS = "-apple-system, 'Segoe UI', Roboto, Arial, sans-serif"


def _money(x: float) -> str:
    """Деньги коротко: 3,2 млн ₸ / 558 тыс ₸ / 900 ₸ (неразрывные пробелы)."""
    ax = abs(x)
    if ax >= 1_000_000:
        s = f"{x / 1_000_000:.1f}".replace(".", ",").rstrip("0").rstrip(",")
        return f"{s} млн ₸"
    if ax >= 1_000:
        return f"{x / 1000:.0f} тыс ₸"
    return f"{x:.0f} ₸"


def _annual(value: float, report: FleetReport) -> float:
    """Сумма за период → к году (×365/дней)."""
    p = report.period
    days = max(1.0, (p.end_ts - p.start_ts) / 86400)
    return value * 365.0 / days


def _defs() -> str:
    """Градиенты для мягкой глубины сегментов."""
    return (
        "<defs>"
        f'<linearGradient id="gP" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="#3A6CA3"/><stop offset="1" stop-color="{PRIMARY_D}"/>'
        "</linearGradient>"
        f'<linearGradient id="gA" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="#D69A52"/><stop offset="1" stop-color="{ACCENT_D}"/>'
        "</linearGradient>"
        "</defs>"
    )


def _svg(viewbox: str, body: str) -> str:
    return (
        f'<svg viewBox="{viewbox}" role="img" '
        f'style="width:100%;height:auto;display:block;font-family:{SANS}">'
        f"{_defs()}{body}</svg>"
    )


# --- 1. «Куда уходят деньги» — 100%-полоса с возвратным резервом -------------

def money_split(kpi: FleetKPI, report: FleetReport) -> str:
    """Стоимость топлива = в движении + на простое; кадр «сколько можно вернуть»."""
    total = kpi.total_fuel_cost or 0.0
    if total <= 0:
        return ""
    idle = max(0.0, min(total, kpi.idle_fuel_cost or 0.0))
    moving = max(0.0, total - idle)
    share = idle / total * 100 if total else 0
    x0, w, y, h = 30.0, 700.0, 96.0, 56.0
    mw = w * (moving / total) if total else 0
    iw = w - mw
    annual_idle = _annual(idle, report)
    sav = kpi.potential_savings or 0.0
    annual_sav = _annual(sav, report) if sav else 0.0

    body = [
        f'<text x="{x0}" y="40" font-size="23" font-weight="700" '
        f'fill="{TEXT}" font-family="{SERIF}">На простое — {_money(idle)} ({share:.0f}%)</text>',
        f'<text x="{x0}" y="66" font-size="13.5" fill="{MUTED}">'
        f'из {_money(total)} за период · ≈ {_money(annual_idle)}/год без движения</text>',
    ]
    # сегменты
    body.append(
        f'<rect class="grow" x="{x0}" y="{y}" width="{mw:.1f}" height="{h}" rx="5" '
        f'fill="url(#gP)"/>')
    body.append(
        f'<rect class="grow grow2" x="{x0 + mw:.1f}" y="{y}" width="{iw:.1f}" height="{h}" rx="5" '
        f'fill="url(#gA)"/>')
    # подписи на сегментах (если влезают)
    if mw > 120:
        body.append(
            f'<text x="{x0 + mw / 2:.1f}" y="{y + 26}" font-size="15" font-weight="700" '
            f'fill="#fff" text-anchor="middle" font-family="{SERIF}">{_money(moving)}</text>')
        body.append(
            f'<text x="{x0 + mw / 2:.1f}" y="{y + 44}" font-size="11" '
            f'fill="#DCE6F2" text-anchor="middle">в движении</text>')
    if iw > 110:
        body.append(
            f'<text x="{x0 + mw + iw / 2:.1f}" y="{y + 26}" font-size="15" font-weight="700" '
            f'fill="#fff" text-anchor="middle" font-family="{SERIF}">{_money(idle)}</text>')
        body.append(
            f'<text x="{x0 + mw + iw / 2:.1f}" y="{y + 44}" font-size="11" '
            f'fill="#F6E7D2" text-anchor="middle">на простое</text>')
    # пилюля возврата
    if annual_sav > 0:
        body.append(
            f'<rect x="{x0}" y="172" width="320" height="26" rx="13" fill="#FBF3E8"/>')
        body.append(
            f'<text x="{x0 + 14}" y="190" font-size="13" font-weight="700" fill="{ACCENT_D}">'
            f'▲ возврат до {_money(annual_sav)}/год при простое −30%</text>')
    return _svg("0 0 760 210", "".join(body))


# --- 2. Холостой ход против цели — bullet ------------------------------------

def idle_bullet(kpi: FleetKPI, worst: list[tuple[str, float, float]],
                avg: Optional[float] = None, target: float = 0.05) -> str:
    """Bullet: факт доли холостого хода vs цель и среднее по паркам, с худшими ТС."""
    fact = kpi.idle_hours_share or 0.0
    if fact <= 0:
        return ""
    x0, w, y, h = 30.0, 700.0, 92.0, 30.0
    scale = max(fact, avg or 0, target, 0.6) * 1.05  # запас справа
    def px(frac: float) -> float:
        return x0 + w * min(1.0, frac / scale)

    cost = kpi.idle_fuel_cost or 0.0
    body = [
        f'<text x="{x0}" y="40" font-size="23" font-weight="700" fill="{TEXT}" '
        f'font-family="{SERIF}">Холостой ход: {fact * 100:.0f}% моточасов</text>',
        f'<text x="{x0}" y="66" font-size="13.5" fill="{MUTED}">'
        f'цель ≤ {target * 100:.0f}%'
        + (f' · среднее по паркам {avg * 100:.0f}%' if avg else '')
        + (f' · ≈ {_money(cost)} за период' if cost else '') + '</text>',
        # дорожка
        f'<rect x="{x0}" y="{y}" width="{w}" height="{h}" rx="6" fill="{TRACK}"/>',
        # факт
        f'<rect class="grow" x="{x0}" y="{y}" width="{px(fact) - x0:.1f}" height="{h}" rx="6" '
        f'fill="url(#gA)"/>',
        f'<text x="{px(fact) - 10:.1f}" y="{y + 20}" font-size="14" font-weight="700" '
        f'fill="#fff" text-anchor="end" font-family="{SERIF}">{fact * 100:.0f}%</text>',
        # маркер цели
        f'<line x1="{px(target):.1f}" y1="{y - 8}" x2="{px(target):.1f}" y2="{y + h + 8}" '
        f'stroke="{PRIMARY}" stroke-width="2"/>',
        f'<text x="{px(target):.1f}" y="{y + h + 24}" font-size="11" fill="{PRIMARY}" '
        f'text-anchor="middle">цель {target * 100:.0f}%</text>',
    ]
    if avg:
        body.append(
            f'<line x1="{px(avg):.1f}" y1="{y - 8}" x2="{px(avg):.1f}" y2="{y + h + 8}" '
            f'stroke="{SECONDARY}" stroke-width="2" stroke-dasharray="4 3"/>')
        body.append(
            f'<text x="{px(avg):.1f}" y="{y + h + 24}" font-size="11" fill="{SECONDARY}" '
            f'text-anchor="middle">среднее {avg * 100:.0f}%</text>')
    worst_txt = " · ".join(f"{escape(n)} {s * 100:.0f}%" for n, s, _ in worst[:3] if s)
    if worst_txt:
        body.append(
            f'<text x="{x0 + w}" y="{y + h + 50}" font-size="12" fill="{MUTED}" '
            f'text-anchor="end">внимание: {worst_txt}</text>')
    return _svg("0 0 760 180", "".join(body))


# --- 3. Перерасход/экономия к норме — сальдо + рейтинг -----------------------

def norm_rating(report: FleetReport) -> str:
    """Сальдо-бэйдж (перерасход vs экономия) + рейтинг топ-перерасхода по ТС."""
    kpi = report.kpi
    if kpi.vehicles_with_norm <= 0:
        return ""
    over = kpi.total_overrun_cost or 0.0
    eco = kpi.total_economy_cost or 0.0
    net = over - eco
    x0, w = 30.0, 700.0
    tot = (over + eco) or 1.0
    ow = w * over / tot
    body = [
        f'<text x="{x0}" y="34" font-size="18" font-weight="700" fill="{TEXT}" '
        f'font-family="{SERIF}">Сальдо по парку: {"+" if net >= 0 else ""}{_money(net)}</text>',
        f'<rect class="grow" x="{x0}" y="46" width="{ow:.1f}" height="22" rx="4" fill="url(#gA)"/>',
        f'<rect class="grow grow2" x="{x0 + ow:.1f}" y="46" width="{w - ow:.1f}" height="22" rx="4" '
        f'fill="url(#gP)"/>',
        f'<text x="{x0 + 8}" y="62" font-size="11" font-weight="700" fill="#fff">'
        f'перерасход {_money(over)} ({kpi.vehicles_over_norm} ТС)</text>',
        f'<text x="{x0 + w - 8}" y="62" font-size="11" font-weight="700" fill="#fff" '
        f'text-anchor="end">экономия {_money(eco)}</text>',
    ]
    # рейтинг топ-перерасхода
    rows = sorted(
        ((v.name, v.overrun_cost_kzt) for v in report.vehicles
         if v.has_data and v.overrun_cost_kzt and v.overrun_cost_kzt > 0),
        key=lambda x: x[1], reverse=True)[:6]
    if rows:
        body.append(
            f'<text x="{x0}" y="104" font-size="13" font-weight="700" fill="{MUTED}">'
            f'Топ перерасхода — адресный разбор:</text>')
        mx = rows[0][1]
        bx, bw = 210.0, 360.0
        for i, (name, val) in enumerate(rows):
            yy = 128 + i * 26
            bar = bw * (val / mx) if mx else 0
            shade = ACCENT if i < 3 else "#D8A765"
            body.append(
                f'<text x="{x0}" y="{yy}" font-size="12.5" fill="{TEXT}">{escape(name)}</text>')
            body.append(
                f'<rect class="grow" x="{bx}" y="{yy - 10}" width="{bar:.1f}" height="14" rx="3" '
                f'fill="{shade}"/>')
            body.append(
                f'<text x="{bx + bar + 8:.1f}" y="{yy}" font-size="12" font-weight="700" '
                f'fill="{ACCENT_D}">{_money(val)}</text>')
        h = 128 + len(rows) * 26 + 8
    else:
        h = 90
    return _svg(f"0 0 760 {h:.0f}", "".join(body))
