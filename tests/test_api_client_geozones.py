"""Тест пагинации list_geozones: тянуть ВСЕ страницы, а не только первую."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from omnicomm_report.api_client import OmnicommClient  # noqa: E402


def _client() -> OmnicommClient:
    # Без сети: создаём объект в обход __init__, list_geozones использует только _request.
    return OmnicommClient.__new__(OmnicommClient)


def test_list_geozones_paginates_all_pages():
    # 401 геозона, страницами по 200 → 200+200+1.
    total = 401
    all_rows = [{"id": i, "points": [{"latitude": 1, "longitude": 2}]} for i in range(total)]
    calls = []

    def fake_request(method, key, *, params=None, **kw):
        assert key == "geozones_list"
        page = params["page"]; size = params["pageSize"]
        calls.append(page)
        start = (page - 1) * size
        return {"total": total, "page": page, "pageSize": size,
                "rows": all_rows[start:start + size]}

    c = _client()
    c._request = fake_request
    rows = c.list_geozones(page_size=200)        # явно мелкая страница — проверяем ЦИКЛ
    assert len(rows) == 401                      # ВСЕ, не 200
    assert calls == [1, 2, 3]                     # три страницы
    assert len({r["id"] for r in rows}) == 401    # без дублей


def test_list_geozones_dedups_by_id():
    def fake_request(method, key, *, params=None, **kw):
        # обе страницы возвращают пересекающиеся id → дедуп
        page = params["page"]
        rows = ([{"id": 1}, {"id": 2}] if page == 1 else [{"id": 2}, {"id": 3}])
        return {"total": 4, "page": page, "pageSize": 2, "rows": rows}

    c = _client()
    c._request = fake_request
    rows = c.list_geozones()
    assert sorted(r["id"] for r in rows) == [1, 2, 3]   # дубль id=2 схлопнут


def test_list_geozones_default_one_request():
    # 401 геозона при дефолтном page_size=1000 → ОДИН запрос (не 3×200).
    total = 401
    all_rows = [{"id": i} for i in range(total)]
    calls = []

    def fake_request(method, key, *, params=None, **kw):
        page, size = params["page"], params["pageSize"]
        calls.append((page, size))
        start = (page - 1) * size
        return {"total": total, "page": page, "pageSize": size,
                "rows": all_rows[start:start + size]}

    c = _client()
    c._request = fake_request
    rows = c.list_geozones()                      # дефолт 1000
    assert len(rows) == 401
    assert calls == [(1, 1000)]                    # ровно один запрос


def test_list_geozones_single_page():
    def fake_request(method, key, *, params=None, **kw):
        return {"total": 2, "page": 1, "pageSize": 200, "rows": [{"id": 1}, {"id": 2}]}

    c = _client()
    c._request = fake_request
    assert len(c.list_geozones()) == 2
