"""Тест HTML-отчёта: самодостаточность и бизнес-инварианты (§8, §9)."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from omnicomm_report import analytics, charts, data_loader, report_builder, validator  # noqa: E402
from omnicomm_report.models import ReportPeriod  # noqa: E402

SAMPLE = os.path.join(os.path.dirname(__file__), "..", "samples", "fleet_sample.xlsx")
FORBIDDEN = ("слив", "слива", "сливы", "воровств", "кража")


def _report(fuel_price=0.0):
    if not os.path.exists(SAMPLE):
        from samples.generate_sample import main as gen  # type: ignore
        gen()
    vehicles = validator.validate(data_loader.load_from_excel(SAMPLE))
    period = ReportPeriod(
        start=datetime(2026, 5, 1, tzinfo=timezone.utc),
        end=datetime(2026, 5, 31, tzinfo=timezone.utc),
    )
    report = analytics.analyze(vehicles, period, "ООО Тест", source="excel",
                               fuel_price_kzt=fuel_price)
    report.generated_at = datetime(2026, 6, 6, tzinfo=timezone.utc)
    return report


def test_html_builds_self_contained(tmp_path):
    report = _report()
    chart_paths = charts.build_charts(report, str(tmp_path))
    out = report_builder.build_html(report, chart_paths, str(tmp_path / "r.html"))
    assert os.path.exists(out)
    html = open(out, encoding="utf-8").read()
    # графики встроены: инлайн-вектор SVG (или base64-PNG как fallback) —
    # никаких внешних ссылок на файлы
    assert ("<svg" in html) or ("data:image/png;base64," in html)
    assert "src=\"output" not in html and ".png\"" not in html
    # титул + основные разделы (без денег): выводы, профиль, пробег,
    # эффективность, использование, без движения, отклонения, рекомендации
    assert html.count("<h1>") == 1
    assert html.count("<h2>") >= 8
    assert "Использование парка" in html
    # таблица профиля присутствует
    assert "table" in html


def test_html_money_section_in_tenge(tmp_path):
    """С ценой топлива появляется финансовый раздел в тенге (₸)."""
    report = _report(fuel_price=320.0)
    chart_paths = charts.build_charts(report, str(tmp_path))
    out = report_builder.build_html(report, chart_paths, str(tmp_path / "r.html"))
    html = open(out, encoding="utf-8").read()
    assert "Финансовая оценка" in html
    assert "₸" in html
    # без цены — финансового раздела нет
    report0 = _report(fuel_price=0.0)
    out0 = report_builder.build_html(report0, chart_paths, str(tmp_path / "r0.html"))
    assert "Финансовая оценка" not in open(out0, encoding="utf-8").read()


def test_html_no_forbidden_words(tmp_path):
    report = _report()
    chart_paths = charts.build_charts(report, str(tmp_path))
    out = report_builder.build_html(report, chart_paths, str(tmp_path / "r.html"))
    html = open(out, encoding="utf-8").read().lower()
    for word in FORBIDDEN:
        assert word not in html, f"запретное слово в HTML: {word}"


def test_html_handles_missing_chart(tmp_path):
    """Отсутствующий график → плашка, не падение."""
    report = _report()
    out = report_builder.build_html(report, {}, str(tmp_path / "r.html"))
    html = open(out, encoding="utf-8").read()
    assert "chart-missing" in html
