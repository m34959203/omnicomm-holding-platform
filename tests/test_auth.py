"""Тесты учётных записей и ролей платформы."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from omnicomm_report import auth  # noqa: E402


def test_create_and_verify(tmp_path):
    p = str(tmp_path / "users.json")
    assert auth.create_user("mgr", "secret123", "manager", path=p)
    assert auth.verify("mgr", "secret123", path=p) == "manager"
    assert auth.verify("mgr", "wrong", path=p) is None
    assert auth.verify("nouser", "secret123", path=p) is None


def test_role_validation(tmp_path):
    p = str(tmp_path / "users.json")
    assert auth.create_user("a", "p", "admin", path=p)
    assert not auth.create_user("b", "p", "superuser", path=p)   # роль не из ROLES
    assert not auth.create_user("", "p", "manager", path=p)      # пустой логин
    assert auth.is_admin("admin") and not auth.is_admin("manager")


def test_password_not_stored_plaintext(tmp_path):
    p = str(tmp_path / "users.json")
    auth.create_user("u", "MyPlainPass", "manager", path=p)
    raw = open(p, encoding="utf-8").read()
    assert "MyPlainPass" not in raw          # хранится хеш, не пароль
    assert "salt" in raw and "hash" in raw


def test_ensure_admin_seeds_once(tmp_path):
    p = str(tmp_path / "users.json")
    pw = auth.ensure_admin(path=p)
    assert pw and auth.verify("admin", pw, path=p) == "admin"
    assert auth.ensure_admin(path=p) is None  # повторно не пересоздаёт


def test_delete_user(tmp_path):
    p = str(tmp_path / "users.json")
    auth.create_user("tmp", "p", "manager", path=p)
    assert auth.delete_user("tmp", path=p)
    assert auth.verify("tmp", "p", path=p) is None
