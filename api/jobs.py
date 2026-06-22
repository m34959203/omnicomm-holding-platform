"""Фоновые задачи с прогрессом: синк не блокирует запрос.

Корень жалобы «висел 5 минут и не дождался» — синк шёл в HTTP-потоке.
Здесь задача запускается в демон-потоке, эндпоинт сразу отдаёт `job_id`,
а фронт опрашивает прогресс (`GET /sync/{job_id}`) или слушает SSE.

In-process реестр (одна реплика). Для нескольких реплик/перезапусков —
вынести в Redis/БД; контракт `to_dict` тогда не меняется.
"""

from __future__ import annotations

import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Callable, Optional

# Прогресс-колбэк, который получает целевая функция: progress(pct, message).
ProgressCb = Callable[[float, str], None]


@dataclass
class Job:
    id: str
    kind: str
    status: str = "pending"           # pending | running | done | error
    pct: float = 0.0                  # 0..100
    message: str = ""
    error: Optional[str] = None
    result: Optional[dict] = None     # напр. {"period_key": ...}
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id, "kind": self.kind, "status": self.status,
            "pct": round(self.pct, 1), "message": self.message,
            "error": self.error, "result": self.result,
            "started_at": int(self.started_at),
            "finished_at": int(self.finished_at) if self.finished_at else None,
            "elapsed_s": round((self.finished_at or time.time()) - self.started_at, 1),
        }


class JobRegistry:
    """Потокобезопасный реестр фоновых задач."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list[Job]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda j: j.started_at, reverse=True)

    def active(self, kind: str) -> Optional[Job]:
        """Идущая задача данного вида (pending/running) — для single-flight."""
        with self._lock:
            for job in self._jobs.values():
                if job.kind == kind and job.status in ("pending", "running"):
                    return job
        return None

    def _update(self, job_id: str, **fields) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                for k, v in fields.items():
                    setattr(job, k, v)

    def start(self, kind: str, target: Callable[[ProgressCb], dict]) -> Job:
        """Запустить `target(progress)` в фоне. Возвращает Job сразу (pending)."""
        job = Job(id=uuid.uuid4().hex[:12], kind=kind)
        with self._lock:
            self._jobs[job.id] = job

        def progress(pct: float, message: str) -> None:
            self._update(job.id, pct=max(0.0, min(100.0, pct)), message=message,
                         status="running")

        def run() -> None:
            try:
                result = target(progress)
                self._update(job.id, status="done", pct=100.0,
                             result=result, finished_at=time.time(),
                             message="Готово")
            except Exception as exc:  # noqa: BLE001 — фейл задачи не валит сервер
                self._update(job.id, status="error", error=str(exc),
                             finished_at=time.time(),
                             message=f"Ошибка: {exc}")
                traceback.print_exc()

        threading.Thread(target=run, daemon=True, name=f"job-{job.id}").start()
        return job


# Глобальный реестр процесса.
registry = JobRegistry()
