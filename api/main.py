"""FastAPI-мост: Python-движки → быстрый JSON-API для Next.js-фронта.

Контракт:
- `POST /api/sync`            — запустить фоновый синк периода, сразу вернуть job.
- `GET  /api/sync/{id}`       — прогресс задачи (poll).
- `GET  /api/sync/{id}/stream`— прогресс через SSE (живой прогресс-бар).
- `GET  /api/snapshots`       — список готовых снапшотов (выбор периода).
- `GET  /api/dashboard`       — KPI-дерево + экономика (из кэша, мгновенно).
- `GET  /api/geozones`        — фичи геозон для карты.
- `GET  /api/recommendations` — скоростной режим СТ КАП.

Чтения НИКОГДА не ходят в Omnicomm — только синк. Поэтому фронт всегда быстрый.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from omnicomm_report import config

from . import cache, excel, jobs, sync, vehicle

# Загрузить .env в окружение (cron его не сорсит) — иначе Settings.from_env()
# не увидит LOGIN/PASSWORD/SERVICE для live-синка.
config.load_env_file()

app = FastAPI(title="Omnicomm Holding Platform API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    # Dev: любой localhost-порт (порты заняты соседними проектами). Прод-домен —
    # через ENV CORS_ORIGIN (точный origin фронта).
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_origins=[o for o in [os.getenv("CORS_ORIGIN")] if o],
    allow_methods=["*"], allow_headers=["*"],
)

# Период синка по умолчанию. 2 суток: копия КАП (online.omnicomm.ru) медленно
# отдаёт сводный отчёт — за неделю батчи таймаутят, за 2 суток успевают.
DEFAULT_SYNC_SECONDS = 2 * 24 * 3600

# Цена ДТ по умолчанию (₸/л) — чтобы экономика считалась в деньгах без ручного ввода.
DEFAULT_FUEL_PRICE_KZT = 335.0


class SyncRequest(BaseModel):
    demo: bool = False
    start_ts: Optional[int] = None
    end_ts: Optional[int] = None
    fuel_price_kzt: float = 0.0
    workers: int = 6


@app.get("/health")
def health() -> dict:
    return {"ok": True, "snapshots": len(cache.list_snapshots())}


MAX_WORKERS = 8     # потолок параллелизма забора (защита памяти/rate-limit на 2GB VPS)


@app.post("/api/sync")
def start_sync(req: SyncRequest) -> dict:
    """Запустить синк в фоне. Период по умолчанию — последние 7 суток.

    Single-flight: если синк уже идёт — возвращаем его же (не плодим параллельные
    тяжёлые заборы, чтобы не положить сервер по памяти/rate-limit).
    """
    running = jobs.registry.active("sync")
    if running is not None:
        return {**running.to_dict(), "already_running": True}

    end_ts = req.end_ts or int(time.time())
    start_ts = req.start_ts or (end_ts - DEFAULT_SYNC_SECONDS)
    workers = max(1, min(req.workers, MAX_WORKERS))
    fuel = req.fuel_price_kzt or DEFAULT_FUEL_PRICE_KZT

    def target(progress):
        return sync.run_sync(progress, demo=req.demo, start_ts=start_ts,
                             end_ts=end_ts, fuel_price_kzt=fuel,
                             workers=workers)

    job = jobs.registry.start("sync", target)
    return job.to_dict()


@app.get("/api/sync/{job_id}")
def sync_status(job_id: str) -> dict:
    job = jobs.registry.get(job_id)
    if job is None:
        raise HTTPException(404, "Задача не найдена")
    return job.to_dict()


@app.get("/api/sync/{job_id}/stream")
async def sync_stream(job_id: str) -> StreamingResponse:
    """SSE-поток прогресса задачи — живой прогресс-бар без поллинга."""
    if jobs.registry.get(job_id) is None:
        raise HTTPException(404, "Задача не найдена")

    async def events():
        last = None
        while True:
            job = jobs.registry.get(job_id)
            if job is None:
                break
            snap = job.to_dict()
            if snap != last:
                yield f"data: {json.dumps(snap, ensure_ascii=False)}\n\n"
                last = snap
            if job.status in ("done", "error"):
                break
            await asyncio.sleep(0.5)

    return StreamingResponse(events(), media_type="text/event-stream")


@app.get("/api/snapshots")
def snapshots() -> list[dict]:
    return cache.list_snapshots()


def _snapshot(period_key: Optional[str]) -> dict:
    snap = (cache.load_snapshot(period_key) if period_key
            else cache.latest_snapshot())
    if snap is None:
        raise HTTPException(404, "Нет снапшота — запустите синк (POST /api/sync)")
    return snap


@app.get("/api/dashboard")
def dashboard(period_key: Optional[str] = Query(None)) -> dict:
    snap = _snapshot(period_key)
    return {"period": snap.get("period"), "fleet": snap.get("fleet"),
            "orgs": snap.get("orgs"), "economics": snap.get("economics"),
            "meta": snap.get("_meta")}


@app.get("/api/geozones")
def geozones(period_key: Optional[str] = Query(None)) -> dict:
    snap = _snapshot(period_key)
    return {"geozones": snap.get("geozones", []), "meta": snap.get("_meta")}


@app.get("/api/recommendations")
def recommendations(period_key: Optional[str] = Query(None)) -> dict:
    snap = _snapshot(period_key)
    return {"recommendations": snap.get("recommendations", []),
            "vehicle_org": snap.get("vehicle_org", {}), "meta": snap.get("_meta")}


@app.get("/api/sensor-health")
def sensor_health(period_key: Optional[str] = Query(None)) -> dict:
    """Качество данных (R7): светофор терминалов + пропавшие KPI-блоки."""
    snap = _snapshot(period_key)
    return {"sensor_health": snap.get("sensor_health"),
            "vehicle_org": snap.get("vehicle_org", {}), "meta": snap.get("_meta")}


@app.get("/api/maintenance")
def maintenance(period_key: Optional[str] = Query(None)) -> dict:
    """Контроль ТО (R6): наработка и статусы по парку."""
    snap = _snapshot(period_key)
    return {"maintenance": snap.get("maintenance"),
            "vehicle_org": snap.get("vehicle_org", {}), "meta": snap.get("_meta")}


def _veh_window(start_ts, end_ts):
    end = end_ts or int(time.time())
    return (start_ts or (end - 24 * 3600)), end


@app.get("/api/vehicle/{terminal_id}")
def vehicle_card(terminal_id: str,
                 start_ts: Optional[int] = Query(None),
                 end_ts: Optional[int] = Query(None)) -> dict:
    """Карточка ТС (live): трек + ряд скорости. Быстро (~1-2с). По умолчанию — 1 сутки."""
    start, end = _veh_window(start_ts, end_ts)
    try:
        return vehicle.track_detail(terminal_id, start, end)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Omnicomm недоступен: {exc}")


@app.get("/api/vehicle/{terminal_id}/telemetry")
def vehicle_telemetry(terminal_id: str,
                      start_ts: Optional[int] = Query(None),
                      end_ts: Optional[int] = Query(None)) -> dict:
    """Телеметрия ТС из сводного отчёта (медленно ~16с) — грузится лениво."""
    start, end = _veh_window(start_ts, end_ts)
    try:
        return vehicle.telemetry(terminal_id, start, end)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Omnicomm недоступен: {exc}")


@app.get("/api/dashboard.xlsx")
def dashboard_xlsx(period_key: Optional[str] = Query(None)) -> Response:
    """Excel-выгрузка дашборда одной кнопкой (R3.3): все листы из снапшота."""
    snap = _snapshot(period_key)
    data = excel.build_workbook(snap)
    # Имя файла — только ASCII (HTTP-заголовок latin-1); берём period_key (даты).
    pkey = period_key or (snap.get("_meta") or {}).get("period_key") or "report"
    fname = re.sub(r"[^A-Za-z0-9._-]", "_", f"omnicomm-holding-{pkey}.xlsx")
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
