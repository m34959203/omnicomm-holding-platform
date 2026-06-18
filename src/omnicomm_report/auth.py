"""Учётные записи платформы и роли доступа (P0-безопасность).

Две роли:
  • admin   — полный доступ (настройки, парк, нормы, клиенты, шаблоны, планировщик,
              управление пользователями);
  • manager — операционный доступ: формирование и просмотр отчётов, просмотр парка
              и журнала; БЕЗ редактирования конфигурации. Все действия логируются.

Пароли хранятся в `data/users.json` (gitignored) как PBKDF2-хеш с солью — не base64,
в отличие от sandbox-хранилища паролей Omnicomm-клиентов. Это аутентификация САМОЙ
платформы, не сторонней формы.

Holding-слой: у пользователя есть `org_id` — узел `dim_org`, к которому он привязан.
Доступ к данным считается по поддереву этого узла (см. `org.OrgTree.visible_scope`):
руководитель ДЗО видит свою ДЗО + под-ДЗО + подрядчиков, но не соседей. admin —
весь холдинг (org_id может быть пустым; доступ через all_access по роли).
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
    """Список пользователей: [{username, role, org_id}] (без хешей)."""
    return [{"username": u, "role": d.get("role", "manager"),
             "org_id": d.get("org_id")}
            for u, d in sorted(_load(path).items())]


def create_user(username: str, password: str, role: str = "manager",
                org_id: Optional[str] = None,
                path: str = DEFAULT_USERS_PATH) -> bool:
    """Создать/обновить пользователя. role ∈ ROLES. `org_id` — узел `dim_org`,
    к которому привязан пользователь (None для admin/руководителя холдинга).
    При обновлении без нового org_id прежняя привязка сохраняется. Успех → True.
    """
    username = (username or "").strip()
    if not username or not password or role not in ROLES:
        return False
    users = _load(path)
    salt = secrets.token_hex(16)
    rec = {"role": role, "salt": salt, "hash": _hash(password, salt)}
    if org_id:
        rec["org_id"] = org_id
    elif username in users and users[username].get("org_id"):
        rec["org_id"] = users[username]["org_id"]   # сохранить привязку при смене пароля
    users[username] = rec
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


def get_user(username: str, path: str = DEFAULT_USERS_PATH) -> Optional[dict]:
    """{username, role, org_id} или None. Без пароля/хеша."""
    u = _load(path).get((username or "").strip())
    if not u:
        return None
    return {"username": (username or "").strip(),
            "role": u.get("role", "manager"), "org_id": u.get("org_id")}


def user_org(username: str, path: str = DEFAULT_USERS_PATH) -> Optional[str]:
    """org_id, к которому привязан пользователь (None — нет привязки/admin)."""
    u = _load(path).get((username or "").strip())
    return u.get("org_id") if u else None


def authenticate(username: str, password: str,
                 path: str = DEFAULT_USERS_PATH) -> Optional[dict]:
    """Проверить креды и вернуть {username, role, org_id} или None.

    Удобная обёртка над `verify` для holding-входа: сразу отдаёт привязку к узлу,
    чтобы вызывающий построил scope доступа (`org.OrgTree.visible_scope`).
    """
    role = verify(username, password, path)
    if role is None:
        return None
    return {"username": (username or "").strip(), "role": role,
            "org_id": user_org(username, path)}


def ensure_admin(path: str = DEFAULT_USERS_PATH) -> Optional[str]:
    """Засеять админа при пустом хранилище. Пароль — из env ADMIN_PASSWORD или
    одноразово сгенерированный (возвращается ТОЛЬКО при создании, для показа).
    """
    if _load(path):
        return None
    pw = os.getenv("ADMIN_PASSWORD") or secrets.token_urlsafe(9)
    create_user("admin", pw, "admin", path=path)
    return pw


def is_admin(role: Optional[str]) -> bool:
    return role == "admin"
