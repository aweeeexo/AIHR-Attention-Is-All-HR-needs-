"""Асинхронные задачи API и колбэк прогресса пайплайна (быстрое демо)."""

import time

from fastapi.testclient import TestClient

from aihr.api.app import app
from aihr.batch import run_batch
from aihr.config import get_settings
from aihr.pipeline import run
from tests.conftest import fixture_file


def _wait(client: TestClient, job_id: str, timeout: float = 120) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get(f"/jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.2)
    raise AssertionError("задача не завершилась")


def test_pipeline_progress_is_monotonic_and_ends_at_one() -> None:
    seen: list[tuple[str, float]] = []
    run(
        fixture_file("resume_cook.txt"),
        [fixture_file("vacancy_cook.txt"), fixture_file("vacancy_welder.txt")],
        save=False,
        progress=lambda stage, f: seen.append((stage, f)),
    )
    fractions = [f for _, f in seen]
    assert fractions == sorted(fractions) and fractions[-1] == 1.0
    stages = [s for s, _ in seen]
    assert "Профиль кандидата" in stages and "Сопоставление: 2 из 2 вакансий" in stages


def test_batch_progress_names_candidates() -> None:
    seen: list[str] = []
    run_batch(
        [fixture_file("resume_cook.txt"), fixture_file("resume_cook.txt")],
        [fixture_file("vacancy_cook.txt")],
        save=False,
        progress=lambda stage, f: seen.append(stage),
    )
    assert any(s.startswith("Кандидат 2 из 2:") for s in seen)


def test_progress_callback_errors_do_not_break_run() -> None:
    def boom(stage: str, f: float) -> None:
        raise RuntimeError("UI упал")

    r = run(fixture_file("resume_cook.txt"), [fixture_file("vacancy_cook.txt")], save=False,
            progress=boom)  # fmt: skip
    assert r.ranking is not None


def test_job_match_flow() -> None:
    client = TestClient(app)
    resume, vac = fixture_file("resume_cook.txt"), fixture_file("vacancy_cook.txt")
    r = client.post(
        "/jobs/match", files=[("resume", (resume[1], resume[0])), ("vacancies", (vac[1], vac[0]))]
    )
    assert r.status_code == 202 and r.json()["kind"] == "match"
    job = _wait(client, r.json()["job_id"])
    assert job["status"] == "done" and job["progress"] == 1.0 and job["stage"] == "Готово"
    assert client.get(f"/runs/{job['run_id']}").status_code == 200
    get_settings.cache_clear()


def test_job_batch_example_and_errors() -> None:
    client = TestClient(app)
    job = _wait(client, client.post("/jobs/batch/example").json()["job_id"], timeout=300)
    assert job["status"] == "done" and job["batch_id"]
    assert client.get(f"/batches/{job['batch_id']}").status_code == 200
    assert client.get("/jobs/not-a-job").status_code == 400
    assert client.get("/jobs/0123456789abcdef").status_code == 404
    get_settings.cache_clear()


def test_job_own_resume_against_case_vacancies() -> None:
    client = TestClient(app)
    data, name = fixture_file("resume_cook.txt")
    r = client.post("/jobs/match/case", files=[("resume", (name, data))])
    assert r.status_code == 202
    job = _wait(client, r.json()["job_id"])
    assert job["status"] == "done"
    result = client.get(f"/runs/{job['run_id']}").json()
    assert len(result["vacancies"]) == 3  # три вакансии кейса
    get_settings.cache_clear()
