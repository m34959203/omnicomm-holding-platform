"""Построение графиков matplotlib для клиентского отчёта (ТЗ §5 п.6, §8).

Светлый официальный корпоративный стиль: белый фон, спокойный синий,
тёплый янтарь — только для «зон внимания». Никаких обвинительных
формулировок, тёмных тем и перегруза.

Модуль работает исключительно с единой моделью `FleetReport`
(см. models.py) — про источник данных (API/Excel) ничего не знает.
"""

from __future__ import annotations

# Без дисплея (сервер/CI) рендерим в файлы — backend Agg обязателен
# и должен быть выбран ДО первого импорта pyplot, иначе matplotlib
# попытается открыть GUI-бэкенд и упадёт.
import matplotlib

matplotlib.use("Agg")

import os
from typing import Optional

import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

from . import vehicle_types
from .models import FleetReport, VehicleMetrics

# --- Палитра и стиль (светлый официальный, ТЗ §8) ----------------------------

BG_COLOR = "#FFFFFF"            # белый фон — требование корпоративного стиля
PRIMARY = "#2F5C8F"            # приглушённый корпоративный синий — основной цвет
SECONDARY = "#7E93AB"          # серо-синий — вторичные элементы / «прочее»
ACCENT = "#C8893F"            # тёплый янтарь — только «зоны внимания»
TEXT_COLOR = "#2B2B2B"        # почти чёрный — читаемый текст
GRID_COLOR = "#D9DEE6"        # светлая лёгкая сетка

# --- Пороговые/отображательные константы -------------------------------------

# Порог «высокого расхода» на 100 км (ТЗ §5): выше — выделяем янтарём
# как зону внимания. Не утверждаем перерасход (нет согласованных норм) —
# лишь визуально обращаем внимание.
HIGH_FUEL_PER_100KM = 100.0

# Если ТС больше — показываем топ-N, остальное сворачиваем в подпись «и ещё N»
MAX_BARS = 12

# DejaVu Sans поставляется с matplotlib и содержит кириллицу —
# без явного указания подписи на русском могут стать «квадратами».
plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 12,
        "figure.facecolor": BG_COLOR,
        "axes.facecolor": BG_COLOR,
        "savefig.facecolor": BG_COLOR,
        "text.color": TEXT_COLOR,
        "axes.labelcolor": TEXT_COLOR,
        "axes.edgecolor": GRID_COLOR,
        "xtick.color": TEXT_COLOR,
        "ytick.color": TEXT_COLOR,
        "axes.titlecolor": TEXT_COLOR,
    }
)

_DPI = 150  # минимально требуемое качество для печати/презентации


# --- Вспомогательные функции -------------------------------------------------


def _vehicles_with_data(report: FleetReport) -> list[VehicleMetrics]:
    """Только ТС с данными — графики строятся лишь по ним (ТЗ §5 п.6)."""
    return [v for v in report.vehicles if v.has_data]


def _is_stationary_equipment(v: VehicleMetrics) -> bool:
    """Неподвижная спецтехника: для неё корректна метрика л/моточас, а не л/100км.

    Признак — паспортный тип (primary_metric='l_per_mh': экскаватор/кран/
    погрузчик/трактор) ИЛИ кинематика (мало пробега на моточас, is_stationary).
    """
    if vehicle_types.profile(v.vehicle_type).primary_metric == "l_per_mh":
        return True
    return v.is_stationary


def _safe_ratio(num: float, den: float) -> float:
    """Доля num/den без деления на ноль."""
    return num / den if den else 0.0


def _short_label(name: str, limit: int = 18) -> str:
    """Усечь длинное наименование/госномер, чтобы подпись не ломала макет."""
    name = (name or "").strip()
    if len(name) <= limit:
        return name
    return name[: limit - 1] + "…"


def _style_axes(ax: plt.Axes) -> None:
    """Единый минималистичный вид осей: лёгкая сетка, без лишних рамок."""
    ax.set_axisbelow(True)
    ax.grid(axis="x", color=GRID_COLOR, linewidth=0.8)
    ax.grid(axis="y", visible=False)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID_COLOR)


def _top_sorted(
    items: list[tuple[VehicleMetrics, float]],
) -> tuple[list[tuple[VehicleMetrics, float]], int]:
    """Отсортировать по убыванию значения и оставить топ-MAX_BARS.

    Возвращает (отобранные, число_скрытых) — скрытые показываем подписью.
    """
    items_sorted = sorted(items, key=lambda it: it[1], reverse=True)
    hidden = max(0, len(items_sorted) - MAX_BARS)
    return items_sorted[:MAX_BARS], hidden


def _placeholder(ax: plt.Axes, text: str = "Недостаточно данных") -> None:
    """Аккуратная плашка вместо графика, когда данных нет — не падать."""
    ax.axis("off")
    ax.text(
        0.5,
        0.5,
        text,
        ha="center",
        va="center",
        fontsize=15,
        color=SECONDARY,
        transform=ax.transAxes,
    )


def _money_short(x: float) -> str:
    """Деньги коротко и по-русски: 3,2 млн ₸ / 558 тыс ₸ / 900 ₸ (неразрыв. пробелы)."""
    ax = abs(x)
    if ax >= 1_000_000:
        s = f"{x / 1_000_000:.1f}".replace(".", ",").rstrip("0").rstrip(",")
        return f"{s} млн ₸"
    if ax >= 1_000:
        return f"{x / 1000:.0f} тыс ₸"
    return f"{x:.0f} ₸"


def _money_axis(ax: plt.Axes, which: str = "x") -> None:
    """Форматтер денежной оси — убирает научную нотацию (1e6/1e7) и красит в ₸."""
    fmt = FuncFormatter(lambda v, _pos: _money_short(v))
    (ax.xaxis if which == "x" else ax.yaxis).set_major_formatter(fmt)


def _save(fig: plt.Figure, outdir: str, key: str) -> str:
    """Сохранить фигуру в PNG (для .pptx) и SVG (вектор для HTML), закрыть фигуру.

    Возвращает путь к PNG — это контракт для pptx; HTML-сборщик сам подхватывает
    SVG-сосед того же имени (чёткий вектор, идеальная печать в PDF).
    """
    path = os.path.join(outdir, f"{key}.png")
    fig.savefig(path, dpi=_DPI, bbox_inches="tight")
    try:
        fig.savefig(os.path.join(outdir, f"{key}.svg"), bbox_inches="tight")
    except Exception:  # noqa: BLE001 — SVG необязателен, PNG уже сохранён
        pass
    plt.close(fig)
    return path


def _hbar_with_hidden(ax: plt.Axes, hidden: int) -> None:
    """Подпись «и ещё N» под горизонтальным bar, если часть ТС скрыта."""
    if hidden > 0:
        ax.annotate(
            f"и ещё {hidden} ТС",
            xy=(0.99, -0.04),
            xycoords="axes fraction",
            ha="right",
            va="top",
            fontsize=10,
            color=SECONDARY,
        )


# --- Построители отдельных графиков (приватные) ------------------------------


def _chart_mileage(report: FleetReport, outdir: str) -> Optional[str]:
    """Горизонтальный bar пробега по ТС, км (ТЗ §5)."""
    data = [
        (v, v.mileage_km)
        for v in _vehicles_with_data(report)
        if v.mileage_km is not None and v.mileage_km > 0
    ]
    fig, ax = plt.subplots(figsize=(9, 5.2))
    if not data:
        _placeholder(ax)
        return _save(fig, outdir, "mileage")

    top, hidden = _top_sorted(data)
    # barh рисует снизу вверх — разворачиваем, чтобы максимум был наверху
    top = list(reversed(top))
    labels = [_short_label(v.name) for v, _ in top]
    values = [val for _, val in top]

    ax.barh(labels, values, color=PRIMARY)
    ax.set_title("Пробег по ТС, км", fontweight="bold", pad=12)
    ax.set_xlabel("Километры")
    _style_axes(ax)
    for y, val in enumerate(values):
        ax.text(
            val, y, f" {val:,.0f}".replace(",", " "), va="center", fontsize=10, color=TEXT_COLOR
        )
    _hbar_with_hidden(ax, hidden)
    return _save(fig, outdir, "mileage")


def _chart_fuel_per_100km(report: FleetReport, outdir: str) -> Optional[str]:
    """Bar расхода на 100 км — ТОЛЬКО подвижная техника; выше порога — янтарём.

    Неподвижную спецтехнику (экскаватор/кран/погрузчик) сюда не берём: для неё
    л/100 км некорректен (околонулевой пробег раздувает цифру). Её расход — в
    отдельном графике л/моточас.
    """
    data = [
        (v, v.fuel_per_100km_calc)
        for v in _vehicles_with_data(report)
        if v.fuel_per_100km_calc is not None and v.fuel_per_100km_calc > 0
        and not _is_stationary_equipment(v)
    ]
    fig, ax = plt.subplots(figsize=(9, 5.2))
    if not data:
        _placeholder(ax, "Нет подвижной техники с данными о пробеге")
        return _save(fig, outdir, "fuel_per_100km")

    top, hidden = _top_sorted(data)
    top = list(reversed(top))
    labels = [_short_label(v.name) for v, _ in top]
    values = [val for _, val in top]
    # Янтарь — только для значений выше порога высокого расхода
    colors = [ACCENT if val > HIGH_FUEL_PER_100KM else PRIMARY for val in values]

    ax.barh(labels, values, color=colors)
    ax.set_title("Расход на 100 км — подвижная техника, л", fontweight="bold", pad=12)
    ax.set_xlabel("Литры на 100 км")
    # Опорная линия порога — визуальный ориентир «зоны внимания»
    ax.axvline(HIGH_FUEL_PER_100KM, color=ACCENT, linestyle="--", linewidth=1, alpha=0.7)
    _style_axes(ax)
    for y, val in enumerate(values):
        ax.text(val, y, f" {val:.1f}", va="center", fontsize=10, color=TEXT_COLOR)
    _hbar_with_hidden(ax, hidden)
    return _save(fig, outdir, "fuel_per_100km")


def _chart_fuel_per_mh(report: FleetReport, outdir: str) -> Optional[str]:
    """Bar расхода л/моточас — ТОЛЬКО неподвижная спецтехника.

    Корректная метрика для техники, работающей на месте (экскаватор/кран/
    погрузчик/трактор и пр.): расход на моточас, а не на пробег.
    """
    data = [
        (v, v.fuel_per_motorhour)
        for v in _vehicles_with_data(report)
        if v.fuel_per_motorhour is not None and v.fuel_per_motorhour > 0
        and _is_stationary_equipment(v)
    ]
    fig, ax = plt.subplots(figsize=(9, 5.2))
    if not data:
        _placeholder(ax, "Неподвижная спецтехника не выявлена")
        return _save(fig, outdir, "fuel_per_mh")

    top, hidden = _top_sorted(data)
    top = list(reversed(top))
    labels = [_short_label(v.name) for v, _ in top]
    values = [val for _, val in top]
    ax.barh(labels, values, color=PRIMARY)
    ax.set_title("Расход на моточас — спецтехника, л/мч", fontweight="bold", pad=12)
    ax.set_xlabel("Литры на моточас")
    _style_axes(ax)
    for y, val in enumerate(values):
        ax.text(val, y, f" {val:.1f}", va="center", fontsize=10, color=TEXT_COLOR)
    _hbar_with_hidden(ax, hidden)
    return _save(fig, outdir, "fuel_per_mh")


def _chart_fleet_class(report: FleetReport, outdir: str) -> Optional[str]:
    """Пончик: структура парка — подвижная техника vs неподвижная спецтехника."""
    active = _vehicles_with_data(report)
    fig, ax = plt.subplots(figsize=(6.5, 5.2))
    if not active:
        _placeholder(ax, "Недостаточно данных по парку")
        return _save(fig, outdir, "fleet_class")

    stat = sum(1 for v in active if _is_stationary_equipment(v))
    mob = len(active) - stat
    if mob == 0 and stat == 0:
        _placeholder(ax, "Недостаточно данных по парку")
        return _save(fig, outdir, "fleet_class")

    wedges, _ = ax.pie(
        [mob, stat], colors=[PRIMARY, ACCENT], startangle=90, counterclock=False,
        wedgeprops={"width": 0.42, "edgecolor": BG_COLOR, "linewidth": 2},
    )
    ax.text(0, 0.05, str(len(active)), ha="center", va="center",
            fontsize=26, fontweight="bold", color=PRIMARY)
    ax.text(0, -0.2, "ТС с данными", ha="center", va="center", fontsize=11, color=SECONDARY)
    ax.set_title("Структура парка по типу метрики", fontweight="bold", pad=12)
    ax.legend(wedges,
              [f"Подвижная (л/100км) — {mob}", f"Спецтехника (л/моточас) — {stat}"],
              loc="lower center", bbox_to_anchor=(0.5, -0.16), ncol=1, frameon=False,
              fontsize=10)
    return _save(fig, outdir, "fleet_class")


def _chart_money(report: FleetReport, outdir: str) -> Optional[str]:
    """Стэк: стоимость топлива = в движении + на простое; подпись потерь в ₸.

    Визуализирует финансовый блок: сколько денег «сгорело» на простое и
    сколько можно вернуть (потенциальная экономия).
    """
    kpi = report.kpi
    fig, ax = plt.subplots(figsize=(9, 3.4))
    if not kpi.total_fuel_cost or kpi.total_fuel_cost <= 0:
        _placeholder(ax, "Цена топлива не задана — денежная оценка недоступна")
        return _save(fig, outdir, "money")

    idle = max(0.0, kpi.idle_fuel_cost)
    moving = max(0.0, kpi.total_fuel_cost - idle)

    def _t(x: float) -> str:
        return f"{x:,.0f} ₸".replace(",", " ")

    ax.barh([0], [moving], color=PRIMARY, label="Топливо в движении")
    ax.barh([0], [idle], left=[moving], color=ACCENT, label="Топливо на простое")
    if moving > 0:
        ax.text(moving / 2, 0, _t(moving), ha="center", va="center",
                color="white", fontsize=11, fontweight="bold")
    if idle > 0:
        ax.text(moving + idle / 2, 0, _t(idle), ha="center", va="center",
                color="white", fontsize=11, fontweight="bold")
    ax.set_yticks([])
    ax.set_xticks([])  # суммы подписаны на сегментах — ось с 1e7 не нужна
    share = (idle / kpi.total_fuel_cost * 100) if kpi.total_fuel_cost else 0
    title = f"Стоимость топлива: {_t(kpi.total_fuel_cost)} · на простое {share:.0f}%"
    ax.set_title(title, fontweight="bold", pad=12)
    _style_axes(ax)
    ax.grid(axis="x", visible=False)
    leg_lines = []
    if kpi.potential_savings and kpi.potential_savings > 0:
        leg_lines.append(f"Потенциальная экономия: {_t(kpi.potential_savings)}/период")
    ax.legend(loc="upper right", frameon=False, fontsize=10)
    if leg_lines:
        ax.annotate(leg_lines[0], xy=(0.0, -0.5), xycoords="axes fraction",
                    ha="left", va="top", fontsize=11, color=ACCENT, fontweight="bold")
    return _save(fig, outdir, "money")


def _chart_overrun(report: FleetReport, outdir: str) -> Optional[str]:
    """Дивергентный bar: перерасход (янтарь) и экономия (синий) к норме, ₸/ТС.

    Строится только если у ТС заданы нормы (overrun_cost_kzt не None).
    """
    data = [
        (v, v.overrun_cost_kzt)
        for v in _vehicles_with_data(report)
        if v.overrun_cost_kzt is not None and abs(v.overrun_cost_kzt) > 0
    ]
    fig, ax = plt.subplots(figsize=(9, 5.2))
    if not data:
        _placeholder(ax, "Нормы расхода не заданы — отклонения не рассчитаны")
        return _save(fig, outdir, "overrun")

    # Сортируем по величине отклонения, крупнейшее сверху.
    data.sort(key=lambda t: t[1])
    data = data[:MAX_BARS] if len(data) > MAX_BARS else data
    labels = [_short_label(v.name) for v, _ in data]
    values = [val for _, val in data]
    colors = [ACCENT if val > 0 else PRIMARY for val in values]

    ax.barh(labels, values, color=colors)
    ax.axvline(0, color=GRID_COLOR, linewidth=1)
    ax.set_title("Отклонение от нормы расхода по ТС, ₸", fontweight="bold", pad=12)
    ax.set_xlabel("← экономия    ₸    перерасход →")
    _money_axis(ax, "x")
    _style_axes(ax)
    ax.grid(axis="x", visible=False)
    for y, val in enumerate(values):
        ax.text(val, y, " " + _money_short(val),
                va="center", ha="left" if val >= 0 else "right",
                fontsize=9, color=TEXT_COLOR)
    return _save(fig, outdir, "overrun")


def _chart_fuel_idle(report: FleetReport, outdir: str) -> Optional[str]:
    """Пончик: доля топлива без движения vs остальное (kpi.fuel_idle_share)."""
    share = report.kpi.fuel_idle_share
    fig, ax = plt.subplots(figsize=(6.5, 5.2))
    # Доля валидна только в диапазоне (0..1]; иначе данных по простою нет
    if share is None or share <= 0 or share > 1:
        _placeholder(ax, "Недостаточно данных о работе без движения")
        return _save(fig, outdir, "fuel_idle")

    idle = share
    moving = 1.0 - share
    wedges, _ = ax.pie(
        [idle, moving],
        colors=[ACCENT, PRIMARY],
        startangle=90,
        counterclock=False,
        wedgeprops={"width": 0.42, "edgecolor": BG_COLOR, "linewidth": 2},
    )
    # Подпись доли в центре пончика — сразу читается главный показатель
    ax.text(0, 0, f"{idle * 100:.0f}%", ha="center", va="center", fontsize=26, fontweight="bold", color=ACCENT)
    ax.text(0, -0.22, "без движения", ha="center", va="center", fontsize=11, color=SECONDARY)
    ax.set_title("Доля топлива, израсходованного без движения", fontweight="bold", pad=12)
    ax.legend(
        wedges,
        ["Без движения", "В движении"],
        loc="lower center",
        bbox_to_anchor=(0.5, -0.12),
        ncol=2,
        frameon=False,
        fontsize=10,
    )
    ax.set_aspect("equal")
    return _save(fig, outdir, "fuel_idle")


def _chart_speeding(report: FleetReport, outdir: str) -> Optional[str]:
    """Bar числа превышений по ТС; плашка, если данных нет нигде."""
    data = [
        (v, float(v.speeding_count))
        for v in _vehicles_with_data(report)
        if v.speeding_count is not None and v.speeding_count > 0
    ]
    fig, ax = plt.subplots(figsize=(9, 5.2))
    # Если ни у одного ТС нет данных по превышениям — честная заглушка
    has_any = any(v.speeding_count is not None for v in _vehicles_with_data(report))
    if not data:
        _placeholder(ax, "Нет данных по превышениям" if not has_any else "Превышений не зафиксировано")
        return _save(fig, outdir, "speeding")

    top, hidden = _top_sorted(data)
    top = list(reversed(top))
    labels = [_short_label(v.name) for v, _ in top]
    values = [val for _, val in top]
    # Превышения — зона внимания, поэтому весь ряд в янтаре
    ax.barh(labels, values, color=ACCENT)
    ax.set_title("Число превышений скорости по ТС", fontweight="bold", pad=12)
    ax.set_xlabel("Количество превышений")
    _style_axes(ax)
    for y, val in enumerate(values):
        ax.text(val, y, f" {val:.0f}", va="center", fontsize=10, color=TEXT_COLOR)
    _hbar_with_hidden(ax, hidden)
    return _save(fig, outdir, "speeding")


def _chart_utilization(report: FleetReport, outdir: str) -> Optional[str]:
    """Stacked-bar моточасов по ТС: движение (синий) + холостой ход (янтарь)."""
    data = [
        (v, (v.engine_hours or 0.0), (v.engine_idle_hours or 0.0))
        for v in _vehicles_with_data(report)
        if v.engine_hours and v.engine_hours > 0
    ]
    fig, ax = plt.subplots(figsize=(9, 5.2))
    if not data:
        _placeholder(ax, "Недостаточно данных о моточасах")
        return _save(fig, outdir, "utilization")

    # сортируем по доле холостого хода (где простой больше — выше)
    data.sort(key=lambda t: _safe_ratio(t[2], t[1]), reverse=True)
    data = list(reversed(data[:MAX_BARS]))
    labels = [_short_label(v.name) for v, _, _ in data]
    idle = [ih for _, _, ih in data]
    move = [max(0.0, eh - ih) for _, eh, ih in data]

    ax.barh(labels, move, color=PRIMARY, label="В движении")
    ax.barh(labels, idle, left=move, color=ACCENT, label="Холостой ход")
    ax.set_title("Моточасы: движение и холостой ход по ТС", fontweight="bold", pad=12)
    ax.set_xlabel("Моточасы")
    _style_axes(ax)
    ax.legend(loc="lower right", frameon=False, fontsize=10)
    return _save(fig, outdir, "utilization")


def _chart_cost(report: FleetReport, outdir: str) -> Optional[str]:
    """Bar стоимости топлива по ТС, ₸ (строится только при заданной цене)."""
    price = report.kpi.fuel_price_kzt
    fig, ax = plt.subplots(figsize=(9, 5.2))
    if not price or price <= 0:
        _placeholder(ax, "Цена топлива не задана")
        return _save(fig, outdir, "cost")

    data = [
        (v, (v.fuel_l or 0.0) * price)
        for v in _vehicles_with_data(report)
        if v.fuel_l and v.fuel_l > 0
    ]
    if not data:
        _placeholder(ax)
        return _save(fig, outdir, "cost")

    top, hidden = _top_sorted(data)
    top = list(reversed(top))
    labels = [_short_label(v.name) for v, _ in top]
    values = [val for _, val in top]
    # Топ-1 «жжёт больше всех» — янтарём как зона внимания, остальные — синие.
    colors = [ACCENT if i == 0 else PRIMARY for i in range(len(values))]
    colors = list(reversed(colors))  # данные перевёрнуты для barh снизу-вверх
    ax.barh(labels, values, color=colors)
    leader = max(values) if values else 0
    ax.set_title(f"Топливо: лидер расхода — {_money_short(leader)}/период",
                 fontweight="bold", pad=12)
    _money_axis(ax, "x")
    _style_axes(ax)
    for y, val in enumerate(values):
        ax.text(val, y, " " + _money_short(val), va="center", fontsize=10, color=TEXT_COLOR)
    _hbar_with_hidden(ax, hidden)
    return _save(fig, outdir, "cost")


def _chart_loading_split(report: FleetReport, outdir: str) -> Optional[str]:
    """Раскладка работы стоя по ТС: погрузка vs непродуктивный простой, ч.

    Оценочные (метод 'rpm') — со штриховкой. ТС без сигнала ('none') не рисуем.
    """
    data = [
        v for v in _vehicles_with_data(report)
        if v.loading_hours is not None and (v.work_no_move_hours or 0) > 0
    ]
    fig, ax = plt.subplots(figsize=(9, 5.4))
    if not data:
        _placeholder(ax, "Нет ТС с сигналом погрузки")
        return _save(fig, outdir, "loading_split")

    data.sort(key=lambda v: v.loading_hours or 0)
    data = data[-MAX_BARS:]
    labels = [_short_label(v.name) for v in data]
    load = [v.loading_hours or 0 for v in data]
    idle = [v.unproductive_idle_hours or 0 for v in data]
    hatch = ["//" if v.loading_is_estimate else None for v in data]

    for y, (lo, hatch_y) in enumerate(zip(load, hatch)):
        ax.barh(y, lo, color=PRIMARY, hatch=hatch_y, edgecolor=BG_COLOR)
    ax.barh(range(len(idle)), idle, left=load, color=ACCENT)
    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels(labels)
    ax.set_title("Работа на стоянке: погрузка и простой, ч", fontweight="bold", pad=12)
    ax.set_xlabel("Моточасы (стоя)")
    _style_axes(ax)
    # легенда вручную (две категории + пометка оценки)
    from matplotlib.patches import Patch
    leg = [Patch(facecolor=PRIMARY, label="Погрузка (полезно)"),
           Patch(facecolor=ACCENT, label="Непродуктивный простой"),
           Patch(facecolor=PRIMARY, hatch="//", label="оценка по оборотам ≈")]
    ax.legend(handles=leg, loc="lower right", frameon=False, fontsize=9)
    return _save(fig, outdir, "loading_split")


def _chart_savings(report: FleetReport, outdir: str):
    """Накопленная экономия против baseline по периодам программы (₸).

    Ступенчатая линия по леджеру savings; заливка — накопленный результат,
    отрицательные участки (перерасход к эталону) честно показываются янтарём.
    Строится только при ≥1 записи леджера (baseline заморожен).
    """
    series = (report.savings or {}).get("series") or []
    if not series:
        return None
    from datetime import datetime, timezone

    fig, ax = plt.subplots(figsize=(10.6, 4.6))
    xs = list(range(1, len(series) + 1))
    ys = [kzt for _, kzt in series]
    labels = [datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%d.%m")
              for ts, _ in series]

    ax.step(xs, ys, where="mid", color=PRIMARY, linewidth=2.2)
    ax.fill_between(xs, ys, step="mid",
                    where=[y >= 0 for y in ys], color=PRIMARY, alpha=0.18)
    ax.fill_between(xs, ys, step="mid",
                    where=[y < 0 for y in ys], color=ACCENT, alpha=0.25)
    ax.axhline(0, color=GRID_COLOR, linewidth=1)
    ax.scatter(xs[-1:], ys[-1:], color=PRIMARY, zorder=3)
    ax.annotate(_money_short(ys[-1]) + " ₸",
                (xs[-1], ys[-1]), textcoords="offset points", xytext=(6, 8),
                fontsize=13, fontweight="bold",
                color=PRIMARY if ys[-1] >= 0 else ACCENT)
    ax.set_xticks(xs)
    ax.set_xticklabels(labels, fontsize=10)
    ax.set_xlabel("Период программы (дата конца)")
    _money_axis(ax, "y")
    ax.set_title("Накопленная экономия против baseline, ₸")
    return _save(fig, outdir, "savings")


# --- Оркестратор -------------------------------------------------------------


def build_charts(report: FleetReport, outdir: str) -> dict[str, str]:
    """Построить весь набор графиков отчёта и вернуть {ключ: путь к PNG}.

    Создаёт `outdir` при необходимости. Устойчив к пустым данным —
    каждый построитель сам рисует плашку «Недостаточно данных» вместо
    падения. Возвращаются только успешно сохранённые графики.
    """
    os.makedirs(outdir, exist_ok=True)

    builders = {
        "mileage": _chart_mileage,
        "fleet_class": _chart_fleet_class,
        "fuel_per_100km": _chart_fuel_per_100km,
        "fuel_per_mh": _chart_fuel_per_mh,
        "utilization": _chart_utilization,
        "fuel_idle": _chart_fuel_idle,
        "cost": _chart_cost,
        "money": _chart_money,
        "overrun": _chart_overrun,
        "speeding": _chart_speeding,
        "loading_split": _chart_loading_split,
        "savings": _chart_savings,
    }

    result: dict[str, str] = {}
    for key, builder in builders.items():
        path = builder(report, outdir)
        if path:
            result[key] = path
    return result
