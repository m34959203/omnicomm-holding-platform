"""Реестр клиентов платформы: учётка Omnicomm + настройки (enter-once).

Каждый клиент — JSON в `data/clients/<slug>.json`:
  {name, owner, omnicomm:{base_url,login,password,service}, fuel_price_kzt, ...}.

БЕЗОПАСНОСТЬ (P0):
  • Пароль Omnicomm-клиента **шифруется Fernet** (AES-128-CBC + HMAC) ключом из
    окружения: `APP_CRYPTO_KEY` (готовый Fernet-ключ) или PBKDF2 из `APP_SECRET`.
    Без ключа — деградация в base64 с предупреждением (только dev). Чтение
    понимает и старый base64, и Fernet → бесшовная миграция (при сохранении
    перешифровывается в Fernet).
  • `owner` — владелец записи (пользователь платформы). `list_clients`/
    `load_client` фильтруют по владельцу: менеджер видит только свои записи,
    admin — все. Изоляция данных арендаторов.

Паспорта и нормы клиента ведутся отдельно — в `norms` (output/norms/<slug>.json).
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from typing import Optional

from .config import DEFAULT_FUEL_PRICE_KZT

log = logging.getLogger(__name__)

DEFAULT_CLIENTS_DIR = os.path.join("data", "clients")


def _slug(name: str) -> str:
    s = re.sub(r"\s+", "_", (name or "client").strip().lower())
    return re.sub(r"[^\w\-]", "", s, flags=re.UNICODE) or "client"


# --- Шифрование кредов клиентов ----------------------------------------------

_FERNET = None
_FERNET_READY = False


def _fernet():
    """Ленивая инициализация Fernet из ENV. None → ключа нет (dev base64)."""
    global _FERNET, _FERNET_READY
    if _FERNET_READY:
        return _FERNET
    _FERNET_READY = True
    try:
        from cryptography.fernet import Fernet
        key = os.getenv("APP_CRYPTO_KEY", "").strip()
        if not key:
            secret = os.getenv("APP_SECRET", "").strip()
            if secret:
                import hashlib
                digest = hashlib.pbkdf2_hmac(
                    "sha256", secret.encode("utf-8"),
                    b"omnicomm-fleet-report/clients", 200_000)
                key = base64.urlsafe_b64encode(digest).decode("ascii")
        if key:
            _FERNET = Fernet(key.encode("ascii") if isinstance(key, str) else key)
        else:
            log.warning("APP_CRYPTO_KEY/APP_SECRET не заданы — креды клиентов "
                        "в base64 (НЕ шифрование). Только для dev.")
    except Exception as exc:  # noqa: BLE001
        log.warning("Fernet недоступен (%s) — деградация в base64.", exc)
    return _FERNET


def _encrypt(s: str) -> str:
    """Зашифровать секрет. С ключом → Fernet-токен; иначе base64 (dev)."""
    f = _fernet()
    if f is not None:
        return f.encrypt((s or "").encode("utf-8")).decode("ascii")
    return base64.b64encode((s or "").encode("utf-8")).decode("ascii")


def _decrypt(s: str) -> str:
    """Расшифровать секрет: понимает и Fernet-токен, и старый base64 (миграция)."""
    if not s:
        return ""
    f = _fernet()
    if f is not None:
        try:
            return f.decrypt(s.encode("ascii")).decode("utf-8")
        except Exception:  # noqa: BLE001 — не Fernet → пробуем base64-легаси
            pass
    try:
        return base64.b64decode(s.encode("ascii")).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return ""


# --- Доступ/владение ----------------------------------------------------------

def _can_see(meta_owner: Optional[str], user: Optional[str],
             role: Optional[str]) -> bool:
    """Видит ли пользователь запись. admin/без-фильтра → все; менеджер — только
    свои; записи без владельца (legacy) — только admin."""
    if user is None or role == "admin":
        return True
    if not meta_owner:
        return False
    return meta_owner == user


def list_clients(clients_dir: str = DEFAULT_CLIENTS_DIR, *,
                 user: Optional[str] = None,
                 role: Optional[str] = None) -> list[str]:
    """Имена клиентов, видимых пользователю. Без user → все (system/scheduler)."""
    if not os.path.isdir(clients_dir):
        return []
    names = []
    for fn in sorted(os.listdir(clients_dir)):
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(clients_dir, fn), encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        if _can_see(data.get("owner"), user, role):
            names.append(data.get("name", fn[:-5]))
    return names


def client_owner(name: str, clients_dir: str = DEFAULT_CLIENTS_DIR) -> Optional[str]:
    path = os.path.join(clients_dir, f"{_slug(name)}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh).get("owner")
    except (OSError, ValueError):
        return None


def load_client(name: str, clients_dir: str = DEFAULT_CLIENTS_DIR, *,
                user: Optional[str] = None,
                role: Optional[str] = None) -> Optional[dict]:
    """Конфиг клиента (с расшифрованным паролем) или None.

    Если переданы user/role — проверяется доступ: чужой клиент вернёт None
    (изоляция арендаторов), даже если имя угадано.
    """
    path = os.path.join(clients_dir, f"{_slug(name)}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if (user is not None or role is not None) and not _can_see(
            data.get("owner"), user, role):
        return None
    omni = data.get("omnicomm", {})
    omni["password"] = _decrypt(omni.get("password", ""))
    data["omnicomm"] = omni
    return data


def save_client(
    name: str,
    *,
    base_url: str,
    login: str,
    password: str,
    service: str = "",
    fuel_price_kzt: float = DEFAULT_FUEL_PRICE_KZT,
    with_track: bool = False,
    email: str = "",
    schedule: Optional[dict] = None,
    time_fund_hours_per_day: Optional[float] = None,
    owner: Optional[str] = None,
    clients_dir: str = DEFAULT_CLIENTS_DIR,
) -> str:
    """Сохранить/обновить клиента. Пароль шифруется (Fernet), записывается owner.

    `schedule`/`time_fund`/`owner` при правке сохраняются из существующей записи,
    если новые не переданы (правки цены/email не сбрасывают владельца и расписание).
    """
    os.makedirs(clients_dir, exist_ok=True)
    path = os.path.join(clients_dir, f"{_slug(name)}.json")
    # сохранить существующие расписание/фонд/владельца, если новые не передали
    if ((schedule is None or time_fund_hours_per_day is None or owner is None)
            and os.path.exists(path)):
        try:
            with open(path, encoding="utf-8") as fh:
                old = json.load(fh)
            if schedule is None:
                schedule = old.get("schedule")
            if time_fund_hours_per_day is None:
                time_fund_hours_per_day = old.get("time_fund_hours_per_day")
            if owner is None:
                owner = old.get("owner")
        except (OSError, ValueError):
            pass
    payload = {
        "name": name,
        "owner": owner,
        "omnicomm": {
            "base_url": base_url.strip(),
            "login": login.strip(),
            "password": _encrypt(password),
            "service": service.strip(),
        },
        "fuel_price_kzt": float(fuel_price_kzt or 0),
        "with_track": bool(with_track),
        "email": (email or "").strip(),
        "schedule": schedule or {},
        # Нормативный фонд времени, ч/сутки на ТС (ТЗ C1; 0 = не задан).
        "time_fund_hours_per_day": float(time_fund_hours_per_day or 0),
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
    os.chmod(path, 0o600)
    return path


def delete_client(name: str, clients_dir: str = DEFAULT_CLIENTS_DIR) -> bool:
    path = os.path.join(clients_dir, f"{_slug(name)}.json")
    if os.path.exists(path):
        os.remove(path)
        return True
    return False
