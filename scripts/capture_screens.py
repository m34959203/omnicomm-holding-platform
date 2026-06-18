"""Снять скриншоты платформы и HTML-отчёта для презентации (docs/screenshots).

Запуск: PYTHONPATH=src python3 scripts/capture_screens.py
Требует запущенную платформу на http://localhost:8501.
"""

from __future__ import annotations

import pathlib

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)

def _latest(pattern: str, fallback: str) -> str:
    hits = sorted((ROOT / "output").glob(pattern), key=lambda p: p.stat().st_mtime)
    return (hits[-1] if hits else ROOT / "output" / fallback).as_uri()


DEMO = _latest("demo_deck/client_fleet_report_*.html", "demo_deck/index.html")
LOADING = (ROOT / "output" / "loading_report.html").as_uri()
PLATFORM = "http://localhost:8501"

# (имя файла, h2-заголовок секции) — кроп секции отчёта по подписи.
SECTIONS = [
    ("report_fleet", "Структура парка: подвижная и спецтехника"),
    ("report_fuel", "Топливная эффективность — подвижная техника"),
    ("report_financial", "Финансовая оценка (₸)"),
    ("report_usage", "Использование парка"),
    ("report_recommendations", "Рекомендации и план действий"),
]


def shot_section(page, h2_text: str, path: pathlib.Path) -> None:
    """Скриншот <section>, содержащей заданный <h2>."""
    handle = page.evaluate_handle(
        """(t) => [...document.querySelectorAll('section')]
                 .find(s => s.querySelector('h2') && s.querySelector('h2').textContent.includes(t))""",
        h2_text,
    )
    el = handle.as_element()
    if el:
        el.scroll_into_view_if_needed()
        el.screenshot(path=str(path))
        print("ok", path.name)
    else:
        print("MISS", h2_text)


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 900},
                                  device_scale_factor=2)
        page = ctx.new_page()

        # --- HTML-отчёт: hero + экран руководителя + секции ---
        # Демо-отчёт собирать за месячный период, иначе годовые проекции ×365
        # (1-дневный период по умолчанию) дают абсурдные суммы:
        #   PYTHONPATH=src python3 -m omnicomm_report --source excel \
        #     --input samples/fleet_sample.xlsx --client "Демонстрационный автопарк" \
        #     --from 2026-05-01 --to 2026-05-31 --no-history --html --outdir output/demo_deck
        page.goto(DEMO, wait_until="networkidle")
        page.wait_for_timeout(1800)  # дать доиграть анимации SVG/появления
        # hero + KPI: верх страницы
        page.screenshot(path=str(OUT / "report_hero.png"),
                        clip={"x": 0, "y": 0, "width": 1440, "height": 820})
        print("ok report_hero.png")
        # экран для руководителя (hero-SVG)
        el = page.evaluate_handle("() => document.querySelector('.exec')").as_element()
        if el:
            el.screenshot(path=str(OUT / "report_exec.png"))
            print("ok report_exec.png")
        for fname, h2 in SECTIONS:
            shot_section(page, h2, OUT / f"{fname}.png")

        # --- Секция «Работа на погрузке» из отдельного отчёта ---
        page.goto(LOADING, wait_until="networkidle")
        page.wait_for_timeout(600)
        shot_section(page, "Работа на погрузке", OUT / "report_loading.png")

        # --- Платформа Streamlit ---
        try:
            page.goto(PLATFORM, wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(3500)
            page.screenshot(path=str(OUT / "platform.png"))
            print("ok platform.png")
        except Exception as e:  # noqa: BLE001
            print("platform skip:", e)

        browser.close()


if __name__ == "__main__":
    main()
