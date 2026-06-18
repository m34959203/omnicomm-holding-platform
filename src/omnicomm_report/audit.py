"""Журнал действий пользователя (аудит) — особенно по шаблонам/типам/нормам.

Пишет события в JSONL `data/audit/audit.jsonl` (gitignored): кто, когда, что,
по какому клиенту, детали. Используется платформой и планировщиком.
Без сети/БД — простой append; чтение для панели «Журнал действий».
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

AUDIT_DIR = os.path.join("data", "audit")
AUDIT_PATH = os.path.join(AUDIT_DIR, "audit.jsonl")

# Человекочитаемые подписи действий (для панели).
ACTIONS = {
    "client_created": "Создан клиент",
    "client_settings_saved": "Изменены настройки клиента",
    "fuel_price_substituted": "Подставлена цена поставщика",
    "passports_saved": "Изменены паспорта/типы/нормы по ТС",
    "templates_saved": "Изменены ШАБЛОНЫ типов техники",
    "schedule_saved": "Изменено расписание",
    "report_generated": "Сформирован отчёт (вручную)",
    "scheduled_report": "Авто-отчёт по расписанию",
    "login": "Вход в систему",
    "logout": "Выход из системы",
    "user_created": "Создан пользователь",
    "user_deleted": "Удалён пользователь",
    "fuel_price_calendar_add": "Добавлена цена в календарь ГСМ",
}

# Текущий актор сессии (логин пользователя платформы) — для привязки действий.
_ACTOR = "platform"


def set_actor(name: str) -> None:
    """Задать актора сессии (логин), чтобы log() привязывал действия к нему."""
    global _ACTOR
    _ACTOR = (name or "platform").strip() or "platform"


def log(action: str, client: str = "", actor: str = "", **details) -> None:
    """Записать событие в журнал (не падает при ошибке записи)."""
    rec = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "action": action,
        "client": client,
        "actor": actor or _ACTOR,
        "details": details or {},
    }
    try:
        os.makedirs(AUDIT_DIR, exist_ok=True)
        with open(AUDIT_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


def recent(limit: int = 100, client: str = "") -> list[dict]:
    """Последние записи журнала (свежие сверху), опц. фильтр по клиенту."""
    if not os.path.exists(AUDIT_PATH):
        return []
    out: list[dict] = []
    try:
        with open(AUDIT_PATH, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if client and rec.get("client") != client:
                    continue
                out.append(rec)
    except OSError:
        return []
    return list(reversed(out))[:limit]


def label(action: str) -> str:
    return ACTIONS.get(action, action)
