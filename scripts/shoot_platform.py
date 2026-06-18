"""Скрины экранов Streamlit-платформы для ТЗ (docs/screenshots/platform_*.png)."""
import os
import time
from playwright.sync_api import sync_playwright

URL = "http://localhost:8533/"
OUT = "docs/screenshots"
os.makedirs(OUT, exist_ok=True)


def settle(page, ms=2200):
    page.wait_for_timeout(ms)
    # дождаться, пока Streamlit перестанет показывать "Running..."
    for _ in range(20):
        try:
            running = page.locator("text=Running").count()
        except Exception:
            running = 0
        if not running:
            break
        page.wait_for_timeout(300)


def shot(page, name):
    path = os.path.join(OUT, f"platform_{name}.png")
    page.screenshot(path=path, full_page=True)
    print("saved", path)


def click_radio(page, label):
    """Клик по radio-опции в сайдбаре по тексту метки."""
    page.get_by_text(label, exact=True).first.click()
    settle(page)


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1280, "height": 1600},
                            device_scale_factor=2)
    page.goto(URL, wait_until="networkidle")
    settle(page, 2500)

    # 1) Экран входа
    shot(page, "01_login")

    # Логин
    page.get_by_label("Логин").fill("admin")
    page.get_by_label("Пароль").fill("demo12345")
    page.get_by_role("button", name="Войти").click()
    settle(page, 3000)

    # 2) Отчёты → Отчёт по клиенту (главный экран)
    shot(page, "02_report_client")

    # 3) Отчёты → Отчёт из файла
    click_radio(page, "Отчёт из файла")
    shot(page, "03_report_file")

    # Раздел: Парк и клиенты
    click_radio(page, "🚛 Парк и клиенты")
    # 4) Парк техники (паспорта/нормы)
    click_radio(page, "Парк техники")
    shot(page, "04_fleet_norms")

    # 5) Шаблоны техники
    click_radio(page, "Шаблоны техники")
    shot(page, "05_vehicle_types")

    # 6) Новый клиент
    click_radio(page, "Новый клиент")
    shot(page, "06_new_client")

    # 7) Пользователи
    click_radio(page, "Пользователи")
    shot(page, "07_users")

    # Раздел: Автоматизация
    click_radio(page, "⏱ Автоматизация")
    # 8) Планировщик
    click_radio(page, "Планировщик")
    shot(page, "08_scheduler")

    # 9) Журнал действий
    click_radio(page, "Журнал действий")
    shot(page, "09_audit_log")

    browser.close()
    print("DONE")
