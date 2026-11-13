"""HTTP API (FastAPI). Запуск: `uvicorn aihr.api.app:app` или `docker compose up`."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, File, HTTPException, Query, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware

from aihr import __version__
from aihr.batch import run_batch
from aihr.config import get_settings, setup_logging
from aihr.contracts import CONTRACTS_VERSION, BatchResult, MatchResult
from aihr.ingest import fix_filename
from aihr.inputs import case_files, read_files
from aihr.jobs import JobStatus, registry
from aihr.pipeline import RUN_ID_RE, run
from aihr.retrieve import default_encoder

setup_logging()
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Модель эмбеддингов грузим при старте (~10 с), а не на первом запросе пользователя
    encoder, _e5 = await run_in_threadpool(default_encoder)
    log.info("поиск доказательств: %s", "BM25 + эмбеддинги" if encoder else "только BM25")
    s = get_settings()
    if s.warm_on_start and s.llm_configured:
        resumes, vacancies = case_files(s.case_dir)
        if resumes and vacancies:
            job = _jobs().submit(
                "batch",
                lambda p: run_batch(read_files(resumes), read_files(vacancies), progress=p),
            )
            _state["warm_job"] = job.job_id
            log.info("прогрев кэша на примере кейса: задача %s", job.job_id)
    yield


app = FastAPI(
    lifespan=lifespan,
    title="AIHR",
    version=__version__,
    description="Сопоставление резюме с вакансиями: рейтинг, таблица требований с цитатами, "
    "отчёт рекрутеру.",
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],  # имя файла DOCX-отчёта
)


_state: dict[str, str] = {}
JOB_ID_RE = re.compile(r"^[0-9a-f]{16}$")


def _jobs():
    return registry(get_settings().jobs_workers)


def _warmup() -> str:
    job_id = _state.get("warm_job")
    job = _jobs().get(job_id) if job_id else None
    return job.status if job else "off"


@app.get("/health")
def health() -> dict[str, Any]:
    s = get_settings()
    return {
        "warmup": _warmup(),
        "status": "ok",
        "llm": "configured" if s.llm_configured else "none",
        "retrieval": "bm25+embeddings" if default_encoder()[0] is not None else "bm25",
        "contracts_version": CONTRACTS_VERSION,
    }


async def _read(upload: UploadFile, limit: int) -> tuple[bytes, str]:
    # Читаем на байт больше лимита: ingest вернёт E_TOO_LARGE, весь файл в память не берём
    data = await upload.read(limit + 1)
    return data, fix_filename(upload.filename or "без имени")


@app.post("/match", response_model=MatchResult)
async def match(
    resume: Annotated[UploadFile, File(description="Резюме: docx, pdf или txt")],
    vacancies: Annotated[list[UploadFile], File(description="Одна или несколько вакансий")],
) -> MatchResult:
    limit = get_settings().max_file_bytes
    resume_file = await _read(resume, limit)
    vacancy_files = [await _read(v, limit) for v in vacancies]
    return await run_in_threadpool(run, resume_file, vacancy_files)


@app.post("/match/example", response_model=MatchResult)
async def match_example(
    resume: Annotated[
        str | None,
        Query(description="Часть имени файла резюме из примера; по умолчанию первое резюме"),
    ] = None,
) -> MatchResult:
    s = get_settings()
    resumes, vacancies = case_files(s.case_dir)
    if not resumes or not vacancies:
        raise HTTPException(404, f"В {s.case_dir} нет резюме или вакансий примера")
    if resume:
        resumes = [p for p in resumes if resume.lower() in p.name.lower()]
        if not resumes:
            raise HTTPException(404, "Резюме с таким именем в примере нет")
    resume_file = read_files(resumes[:1])[0]
    return await run_in_threadpool(run, resume_file, read_files(vacancies))


BATCH_ID_RE = re.compile(r"^b\d{8}-\d{6}-[0-9a-f]{6}$")


@app.post("/match/batch", response_model=BatchResult)
async def match_batch(
    resumes: Annotated[list[UploadFile], File(description="Несколько резюме: docx, pdf или txt")],
    vacancies: Annotated[list[UploadFile], File(description="Одна или несколько вакансий")],
) -> BatchResult:
    """Пакет (D38): каждое резюме против всех вакансий, матрица и лучшие кандидаты."""
    s = get_settings()
    if len(resumes) > s.max_batch_resumes:
        raise HTTPException(
            413, f"В пакете не больше {s.max_batch_resumes} резюме (MAX_BATCH_RESUMES)"
        )
    resume_files = [await _read(r, s.max_file_bytes) for r in resumes]
    vacancy_files = [await _read(v, s.max_file_bytes) for v in vacancies]
    return await run_in_threadpool(run_batch, resume_files, vacancy_files)


@app.post("/match/batch/example", response_model=BatchResult)
async def match_batch_example() -> BatchResult:
    """Все резюме примера против всех его вакансий."""
    s = get_settings()
    resumes, vacancies = case_files(s.case_dir)
    if not resumes or not vacancies:
        raise HTTPException(404, f"В {s.case_dir} нет резюме или вакансий примера")
    return await run_in_threadpool(run_batch, read_files(resumes), read_files(vacancies))


@app.get("/batches/{batch_id}", response_model=BatchResult)
def get_batch(batch_id: str) -> BatchResult:
    if not BATCH_ID_RE.match(batch_id):
        raise HTTPException(400, "Неверный batch_id")
    path = get_settings().runs_dir / "batches" / f"{batch_id}.json"
    if not path.is_file():
        raise HTTPException(404, "Пакет не найден")
    return BatchResult.model_validate_json(path.read_text(encoding="utf-8"))


# ---------- асинхронные задачи: этап и процент вместо долгого молчания ----------


async def _batch_files(resumes: list[UploadFile], vacancies: list[UploadFile]):
    s = get_settings()
    if len(resumes) > s.max_batch_resumes:
        raise HTTPException(
            413, f"В пакете не больше {s.max_batch_resumes} резюме (MAX_BATCH_RESUMES)"
        )
    limit = s.max_file_bytes
    return [await _read(r, limit) for r in resumes], [await _read(v, limit) for v in vacancies]


def _example(resume: str | None = None) -> tuple[list[Path], list[Path]]:
    s = get_settings()
    resumes, vacancies = case_files(s.case_dir)
    if not resumes or not vacancies:
        raise HTTPException(404, f"В {s.case_dir} нет резюме или вакансий примера")
    if resume:
        resumes = [p for p in resumes if resume.lower() in p.name.lower()]
        if not resumes:
            raise HTTPException(404, "Резюме с таким именем в примере нет")
    return resumes, vacancies


@app.post("/jobs/match", response_model=JobStatus, status_code=202)
async def job_match(
    resume: Annotated[UploadFile, File(description="Резюме: docx, pdf или txt")],
    vacancies: Annotated[list[UploadFile], File(description="Одна или несколько вакансий")],
) -> JobStatus:
    """То же, что POST /match, но сразу возвращает задачу; результат — по GET /jobs/{id}."""
    limit = get_settings().max_file_bytes
    resume_file = await _read(resume, limit)
    vacancy_files = [await _read(v, limit) for v in vacancies]
    return _jobs().submit("match", lambda p: run(resume_file, vacancy_files, progress=p))


@app.post("/jobs/match/example", response_model=JobStatus, status_code=202)
def job_match_example(
    resume: Annotated[str | None, Query(description="Часть имени файла резюме")] = None,
) -> JobStatus:
    resumes, vacancies = _example(resume)
    files = read_files(resumes[:1])[0], read_files(vacancies)
    return _jobs().submit("match", lambda p: run(files[0], files[1], progress=p))


@app.post("/jobs/batch", response_model=JobStatus, status_code=202)
async def job_batch(
    resumes: Annotated[list[UploadFile], File(description="Несколько резюме")],
    vacancies: Annotated[list[UploadFile], File(description="Одна или несколько вакансий")],
) -> JobStatus:
    resume_files, vacancy_files = await _batch_files(resumes, vacancies)
    return _jobs().submit("batch", lambda p: run_batch(resume_files, vacancy_files, progress=p))


@app.post("/jobs/batch/example", response_model=JobStatus, status_code=202)
def job_batch_example() -> JobStatus:
    resumes, vacancies = _example()
    files = read_files(resumes), read_files(vacancies)
    return _jobs().submit("batch", lambda p: run_batch(files[0], files[1], progress=p))


@app.get("/jobs/{job_id}", response_model=JobStatus)
def get_job(job_id: str) -> JobStatus:
    if not JOB_ID_RE.match(job_id):
        raise HTTPException(400, "Неверный job_id")
    job = _jobs().get(job_id)
    if job is None:
        raise HTTPException(404, "Задача не найдена (после перезапуска API задачи не хранятся)")
    return job


@app.get("/example/files")
def example_files() -> dict[str, list[str]]:
    resumes, vacancies = case_files(get_settings().case_dir)
    return {"resumes": [p.name for p in resumes], "vacancies": [p.name for p in vacancies]}


def _run_dir(run_id: str) -> Path:
    if not RUN_ID_RE.match(run_id):
        raise HTTPException(400, "Неверный run_id")
    run_dir = get_settings().runs_dir / run_id
    if not run_dir.is_dir():
        raise HTTPException(404, "Прогон не найден")
    return run_dir


@app.get("/runs/{run_id}", response_model=MatchResult)
def get_run(run_id: str) -> MatchResult:
    path = _run_dir(run_id) / "result.json"
    if not path.is_file():
        raise HTTPException(404, "Результат прогона не найден")
    return MatchResult.model_validate_json(path.read_text(encoding="utf-8"))


@app.get("/runs/{run_id}/report/{vacancy_id}.docx")
def get_report_docx(run_id: str, vacancy_id: str) -> Response:
    """Отчёт по вакансии файлом DOCX — для отправки заказчику (D37)."""
    from aihr.report.export import report_docx

    path = _run_dir(run_id) / "result.json"
    if not path.is_file():
        raise HTTPException(404, "Результат прогона не найден")
    result = MatchResult.model_validate_json(path.read_text(encoding="utf-8"))
    if vacancy_id not in result.reports:
        raise HTTPException(404, "Отчёта по этой вакансии нет")
    filename = f"aihr_{run_id}_{vacancy_id}.docx"
    return Response(
        report_docx(result, vacancy_id),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/runs/{run_id}/outbound")
def get_outbound(run_id: str) -> dict[str, Any]:
    """Журнал исходящих запросов к LLM. До T02 он не ведётся, список пуст."""
    path = _run_dir(run_id) / "outbound.jsonl"
    entries: list[Any] = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                entries.append(json.loads(line))
    return {"run_id": run_id, "entries": entries}
