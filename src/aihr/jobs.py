"""Асинхронные задачи API: прогон идёт в фоне, интерфейс опрашивает этап и процент.

С внешней LLM одно резюме считается 1–2 минуты. Синхронный запрос всё это время молчит, а
задача показывает этап («Сопоставление: 2 из 3 вакансий») и долю готовности. Результат
сохраняется как обычно — в data/runs/ — и читается по run_id или batch_id.

Реестр живёт в памяти процесса API: после перезапуска задачи пропадают, результаты — нет.
"""

from __future__ import annotations

import logging
import secrets
import threading
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from aihr.contracts import BatchResult, MatchResult

log = logging.getLogger(__name__)

MAX_JOBS = 200  # сколько последних задач помним


class JobStatus(BaseModel):
    job_id: str
    kind: Literal["match", "batch"]
    status: Literal["queued", "running", "done", "failed"]
    stage: str = "В очереди"
    progress: float = 0.0  # 0..1
    run_id: str | None = None  # для kind=match: GET /runs/{run_id}
    batch_id: str | None = None  # для kind=batch: GET /batches/{batch_id}
    error: str | None = None
    created_at: str


Work = Callable[[Callable[[str, float], None]], MatchResult | BatchResult]


class JobRegistry:
    def __init__(self, workers: int = 2) -> None:
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="job")
        self._jobs: OrderedDict[str, JobStatus] = OrderedDict()
        self._lock = threading.Lock()

    def submit(self, kind: Literal["match", "batch"], work: Work) -> JobStatus:
        job = JobStatus(
            job_id=secrets.token_hex(8),
            kind=kind,
            status="queued",
            created_at=datetime.now().isoformat(timespec="seconds"),
        )
        with self._lock:
            self._jobs[job.job_id] = job
            while len(self._jobs) > MAX_JOBS:
                self._jobs.popitem(last=False)
        self._pool.submit(self._run, job.job_id, work)
        return job

    def get(self, job_id: str) -> JobStatus | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return job.model_copy() if job else None

    def _update(self, job_id: str, **fields: object) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                self._jobs[job_id] = job.model_copy(update=fields)

    def _run(self, job_id: str, work: Work) -> None:
        self._update(job_id, status="running", stage="Начинаем")

        def progress(stage: str, fraction: float) -> None:
            self._update(job_id, stage=stage, progress=round(fraction, 3))

        try:
            result = work(progress)
        except Exception as exc:  # причина — тип ошибки, без текста документов
            log.exception("задача %s упала", job_id)
            self._update(job_id, status="failed", stage="Ошибка", error=type(exc).__name__)
            return
        ids = (
            {"run_id": result.run_id}
            if isinstance(result, MatchResult)
            else {"batch_id": result.batch_id}
        )
        self._update(job_id, status="done", stage="Готово", progress=1.0, **ids)


_registry: JobRegistry | None = None
_registry_lock = threading.Lock()


def registry(workers: int = 2) -> JobRegistry:
    global _registry
    with _registry_lock:
        if _registry is None:
            _registry = JobRegistry(workers)
        return _registry
