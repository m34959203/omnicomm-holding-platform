"""Тесты FastAPI-моста: кэш, фоновые задачи, demo-синк end-to-end (без сети)."""

import time

import pytest

from api import cache, jobs, sync


@pytest.fixture
def cache_path(tmp_path):
    return str(tmp_path / "snap.db")


# --- cache --------------------------------------------------------------------

def test_cache_upsert_and_load(cache_path):
    cache.save_snapshot({"a": 1}, period_key="p1", label="L", path=cache_path,
                        synced_at=100)
    cache.save_snapshot({"a": 2}, period_key="p1", path=cache_path, synced_at=200)
    snap = cache.load_snapshot("p1", path=cache_path)
    assert snap["a"] == 2                       # upsert, не дубль
    assert snap["_meta"]["synced_at"] == 200
    assert len(cache.list_snapshots(path=cache_path)) == 1


def test_cache_latest_picks_newest(cache_path):
    cache.save_snapshot({"v": "old"}, period_key="p1", path=cache_path, synced_at=100)
    cache.save_snapshot({"v": "new"}, period_key="p2", path=cache_path, synced_at=300)
    assert cache.latest_snapshot(path=cache_path)["v"] == "new"


def test_cache_missing_returns_none(cache_path):
    assert cache.load_snapshot("nope", path=cache_path) is None
    assert cache.latest_snapshot(path=cache_path) is None


# --- jobs ---------------------------------------------------------------------

def test_job_runs_and_reports_progress():
    reg = jobs.JobRegistry()
    seen = []

    def target(progress):
        progress(50, "half")
        seen.append("ran")
        return {"ok": True}

    job = reg.start("t", target)
    for _ in range(100):
        if reg.get(job.id).status in ("done", "error"):
            break
        time.sleep(0.02)
    final = reg.get(job.id)
    assert final.status == "done" and final.pct == 100.0
    assert final.result == {"ok": True} and seen == ["ran"]


def test_active_finds_running_job():
    import threading
    reg = jobs.JobRegistry()
    gate = threading.Event()

    def target(progress):
        gate.wait(timeout=2)
        return {}

    job = reg.start("sync", target)
    assert reg.active("sync") is not None        # идёт → single-flight сработает
    assert reg.active("other") is None
    gate.set()
    for _ in range(100):
        if reg.get(job.id).status == "done":
            break
        time.sleep(0.02)
    assert reg.active("sync") is None            # завершилась → слот свободен


def test_job_captures_error():
    reg = jobs.JobRegistry()

    def boom(progress):
        raise ValueError("nope")

    job = reg.start("t", boom)
    for _ in range(100):
        if reg.get(job.id).status in ("done", "error"):
            break
        time.sleep(0.02)
    final = reg.get(job.id)
    assert final.status == "error" and "nope" in final.error


# --- demo sync end-to-end (без сети) ------------------------------------------

def test_parallel_fetch_covers_all_chunks():
    from api import fetch

    class FakeClient:
        def get_consolidated_report(self, ids, period):
            return [{"vehicle_id": v} for v in ids]

    ids = [str(i) for i in range(127)]  # 3 батча по 50
    out = fetch.fetch_consolidated_parallel(lambda: FakeClient(), ids, None, workers=4)
    assert sorted(int(r["vehicle_id"]) for r in out) == list(range(127))


def test_demo_sync_builds_snapshot(cache_path):
    msgs = []
    end_ts = 1_700_000_000
    start_ts = end_ts - 7 * 24 * 3600
    result = sync.run_sync(lambda p, m: msgs.append((p, m)), demo=True,
                           start_ts=start_ts, end_ts=end_ts, cache_path=cache_path)
    import re
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}_\d{4}-\d{2}-\d{2}", result["period_key"])
    assert result["vehicles"] > 0

    snap = cache.load_snapshot(result["period_key"], path=cache_path)
    assert snap["orgs"] and snap["orgs"][0]["children"]          # дерево организаций
    assert "kpi" in snap["orgs"][0]                              # KPI узла
    assert snap["economics"] is not None                        # экономика холдинга
    assert isinstance(snap["recommendations"], list)            # рекомендации СТ КАП
    assert snap["vehicle_org"]                                  # маппинг ТС→орг
    assert msgs and msgs[-1][0] == 100                          # прогресс дошёл до 100
