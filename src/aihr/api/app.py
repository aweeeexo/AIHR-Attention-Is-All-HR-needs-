"""HTTP API (FastAPI). Запуск: `uvicorn aihr.api.app:app` или `docker compose up`."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool

from aihr import __version__
from aihr.config import get_settings, setup_logging
from aihr.contracts import CONTRACTS_VERSION, MatchResult
from aihr.inputs import case_files, read_files
from aihr.pipeline import RUN_ID_RE, run

setup_logging()
log = logging.getLogger(__name__)

app = FastAPI(
    title="AIHR",
    version=__version__,
    description="Сопоставление резюме с вакансиями: рейтинг, таблица требований с цитатами, "
    "отчёт рекрутеру.",
)


@app.get("/health")
def health() -> dict[str, Any]:
    s = get_settings()
    return {
        "status": "ok",
        "llm": "configured" if s.llm_configured else "none",
        "contracts_version": CONTRACTS_VERSION,
    }


async def _read(upload: UploadFile, limit: int) -> tuple[bytes, str]:
    # Читаем на байт больше лимита: ingest вернёт E_TOO_LARGE, весь файл в память не берём
    data = await upload.read(limit + 1)
    return data, upload.filename or "без имени"


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
