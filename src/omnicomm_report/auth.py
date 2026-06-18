"""Учётные записи платформы и роли доступа (P0-безопасность).

Две роли:
  • admin   — полный доступ (настройки, парк, нормы, клиенты, шаблоны, планировщик,
              управление пользователями);
  • manager — операционный доступ: формирование и просмотр отчётов, просмотр парка
              и журнала; БЕЗ редактирования конфигурации. Все действия логируются.

Пароли хранятся в `data/users.json` (gitignored) как PBKDF2-хеш с солью — не base64,
в отличие от sandbox-хранилища паролей Omnicomm-клиентов. Это аутентификация САМОЙ
платформы, не сторонней формы.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from typing import Optional

DEFAULT_USERS_PATH = os.path.join("data", "users.json")
ROLES = ("admin", "manager")
_ITERATIONS = 200_000


def _hash(password: str, salt: str) -> str:
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                             bytes.fromhex(salt), _ITERATIONS)
    return dk.hex()


def _load(path: str = DEFAULT_USERS_PATH) -> dict[str, dict]:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh) or {}
    except (OSError, ValueError):
        return {}


def _save(users: dict[str, dict], path: str = DEFAULT_USERS_PATH) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(users, fh, ensure_ascii=False, indent=1)
    os.chmod(path, 0o600)


def list_users(path: str = DEFAULT_USERS_PATH) -> list[dict]:
    """Список пользователей: [{username, role}] (без хешей)."""
    return [{"username": u, "role": d.get("role", "manager")}
            for u, d in sorted(_load(path).items())]


def create_user(username: str, password: str, role: str = "manager",
                path: str = DEFAULT_USERS_PATH) -> bool:
    """Создать/обновить пользователя. role ∈ ROLES. Возвращает успех."""
    username = (username or "").strip()
    if not username or not password or role not in ROLES:
        return False
    users = _load(path)
    salt = secrets.token_hex(16)
    users[username] = {"role": role, "salt": salt, "hash": _hash(password, salt)}
    _save(users, path)
    return True


def delete_user(username: str, path: str = DEFAULT_USERS_PATH) -> bool:
    users = _load(path)
    if username in users:
        del users[username]
        _save(users, path)
        return True
    return False


def verify(username: str, password: str, path: str = DEFAULT_USERS_PATH) -> Optional[str]:
    """Проверить логин/пароль. Возвращает роль или None."""
    u = _load(path).get((username or "").strip())
    if not u or "salt" not in u or "hash" not in u:
        return None
    if secrets.compare_digest(_hash(password or "", u["salt"]), u["hash"]):
        return u.get("role", "manager")
    return None


def ensure_admin(path: str = DEFAULT_USERS_PATH) -> Optional[str]:
    """Засеять админа при пустом хранилище. Пароль — из env ADMIN_PASSWORD или
    одноразово сгенерированный (возвращается ТОЛЬКО при создании, для показа).
    """
    if _load(path):
        return None
    pw = os.getenv("ADMIN_PASSWORD") or secrets.token_urlsafe(9)
    create_user("admin", pw, "admin", path)
    return pw


def is_admin(role: Optional[str]) -> bool:
    return role == "admin"
