"""Тесты реестра клиентов платформы."""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from omnicomm_report import clients  # noqa: E402


def test_save_load_roundtrip(tmp_path):
    d = str(tmp_path)
    clients.save_client("Горкомтранс", base_url="https://kz.omnicomm.online",
                        login="demo_login", password="secret123", service="omnicomm",
                        fuel_price_kzt=320, with_track=True,
                        email="director@example.kz", clients_dir=d)
    c = clients.load_client("Горкомтранс", clients_dir=d)
    assert c["name"] == "Горкомтранс"
    assert c["omnicomm"]["login"] == "demo_login"
    assert c["omnicomm"]["password"] == "secret123"   # расшифровался
    assert c["fuel_price_kzt"] == 320
    assert c["with_track"] is True
    assert c["email"] == "director@example.kz"


def test_password_not_plaintext_on_disk(tmp_path):
    d = str(tmp_path)
    clients.save_client("Client", base_url="x", login="l", password="topsecret",
                        clients_dir=d)
    fn = next(f for f in os.listdir(d) if f.endswith(".json"))
    raw = open(os.path.join(d, fn), encoding="utf-8").read()
    assert "topsecret" not in raw          # пароль не лежит открытым текстом
    assert json.loads(raw)["omnicomm"]["password"]  # но он там (обфусцирован)


def test_list_and_delete(tmp_path):
    d = str(tmp_path)
    clients.save_client("A", base_url="x", login="a", password="p", clients_dir=d)
    clients.save_client("Б", base_url="x", login="b", password="p", clients_dir=d)
    assert set(clients.list_clients(clients_dir=d)) == {"A", "Б"}
    assert clients.delete_client("A", clients_dir=d) is True
    assert clients.list_clients(clients_dir=d) == ["Б"]
    assert clients.load_client("A", clients_dir=d) is None


def test_owner_isolation(tmp_path):
    """Менеджер видит только свои записи; admin — все; чужой load → None."""
    d = str(tmp_path)
    clients.save_client("A", base_url="x", login="l", password="p",
                        owner="alice", clients_dir=d)
    clients.save_client("B", base_url="x", login="l", password="p",
                        owner="bob", clients_dir=d)
    assert clients.list_clients(d, user="alice", role="manager") == ["A"]
    assert clients.list_clients(d, user="bob", role="manager") == ["B"]
    assert sorted(clients.list_clients(d, user="root", role="admin")) == ["A", "B"]
    # чужого не загрузить, даже зная имя
    assert clients.load_client("B", clients_dir=d, user="alice", role="manager") is None
    assert clients.load_client("A", clients_dir=d, user="alice", role="manager")["name"] == "A"


def test_legacy_unowned_visible_only_to_admin(tmp_path):
    """Запись без owner (legacy) — только админу."""
    d = str(tmp_path)
    clients.save_client("Old", base_url="x", login="l", password="p", clients_dir=d)
    assert clients.list_clients(d, user="m", role="manager") == []
    assert clients.list_clients(d, user="a", role="admin") == ["Old"]


def test_legacy_base64_password_still_decrypts(tmp_path):
    """Старый base64-пароль читается (бесшовная миграция)."""
    import base64
    d = str(tmp_path)
    os.makedirs(d, exist_ok=True)
    legacy = {"name": "Leg", "omnicomm": {
        "base_url": "x", "login": "l",
        "password": base64.b64encode("oldpass".encode()).decode(), "service": ""}}
    open(os.path.join(d, "leg.json"), "w", encoding="utf-8").write(
        json.dumps(legacy, ensure_ascii=False))
    c = clients.load_client("Leg", clients_dir=d)
    assert c["omnicomm"]["password"] == "oldpass"


def test_owner_preserved_on_edit(tmp_path):
    """Правка без owner не сбрасывает владельца."""
    d = str(tmp_path)
    clients.save_client("C", base_url="x", login="l", password="p",
                        owner="alice", clients_dir=d)
    clients.save_client("C", base_url="x2", login="l", password="p",
                        clients_dir=d)              # owner не передан
    assert clients.client_owner("C", clients_dir=d) == "alice"
