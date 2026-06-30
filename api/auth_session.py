"""Сессии входа для дашборда: подписанная cookie + чтение «зрителя» из запроса.

Логин проверяется `omnicomm_report.auth.verify` (PBKDF2 из data/users.json).
Сессия — HMAC-подписанный токен в httpOnly-cookie (без внешних зависимостей).
Скоуп доступа (org_id) кладётся в токен; серверная фильтрация — в api/scoping.py.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from typing import Optional

from fastapi import Request, Response

from omnicomm_report import auth

COOKIE = "okp_session"
TTL = 30 * 24 * 3600          # 30 суток
_SECRET_FILE = os.path.join("data", ".session_secret")


def _secret() -> bytes:
    env = os.getenv("SESSION_SECRET")
    if env:
        return env.encode()
    try:
        if os.path.exists(_SECRET_FILE):
            return open(_SECRET_FILE, "rb").read()
        s = secrets.token_bytes(32)
        os.makedirs("data", exist_ok=True)
        with open(_SECRET_FILE, "wb") as f:
            f.write(s)
        os.chmod(_SECRET_FILE, 0o600)
        return s
    except OSError:
        return b"omnicomm-holding-fallback-secret"


def _now() -> int:
    import time
    return int(time.time())


def make_token(username: str, org_id: Optional[str], role: str) -> str:
    payload = f"{username}|{org_id or ''}|{role}|{_now() + TTL}"
    raw = base64.urlsafe_b64encode(payload.encode()).decode()
    sig = hmac.new(_secret(), raw.encode(), hashlib.sha256).hexdigest()
    return f"{raw}.{sig}"


def parse_token(token: Optional[str]) -> Optional[dict]:
    if not token or "." not in token:
        return None
    raw, sig = token.rsplit(".", 1)
    if not hmac.compare_digest(sig, hmac.new(_secret(), raw.encode(), hashlib.sha256).hexdigest()):
        return None
    try:
        username, org_id, role, exp = base64.urlsafe_b64decode(raw).decode().split("|")
    except (ValueError, UnicodeDecodeError):
        return None
    if int(exp) < _now():
        return None
    return {"username": username, "org_id": org_id or None, "role": role}


def viewer(request: Request) -> Optional[dict]:
    """Текущий зритель из cookie (или None — аноним)."""
    return parse_token(request.cookies.get(COOKIE))


def login(response: Response, username: str, password: str) -> Optional[dict]:
    rec = auth.authenticate(username, password)   # {username, role, org_id} | None
    if not rec:
        return None
    token = make_token(rec["username"], rec.get("org_id"), rec.get("role", "manager"))
    response.set_cookie(COOKIE, token, max_age=TTL, httponly=True,
                        samesite="lax", secure=True, path="/")
    return rec


def logout(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/")
