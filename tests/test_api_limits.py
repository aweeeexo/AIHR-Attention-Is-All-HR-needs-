"""D62: лимит анализов для публичного стенда."""

import time

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from aihr.api.app import app
from aihr.api.limits import WINDOW_S, AnalysisLimiter, limiter
from aihr.config import get_settings
from tests.conftest import fixture_file


@pytest.fixture
def limits(monkeypatch: pytest.MonkeyPatch):
    def set_limits(total: int = 0, per_ip: int = 0) -> None:
        monkeypatch.setenv("ANALYSIS_LIMIT_PER_HOUR", str(total))
        monkeypatch.setenv("ANALYSIS_LIMIT_PER_IP_HOUR", str(per_ip))
        get_settings.cache_clear()

    limiter.reset()
    yield set_limits
    limiter.reset()


def test_off_by_default() -> None:
    lim = AnalysisLimiter()
    for _ in range(1000):
        lim.charge("1.1.1.1")


def test_per_ip_and_total_with_sliding_window(limits) -> None:
    limits(total=3, per_ip=2)
    lim = AnalysisLimiter()
    lim.charge("a", now=0)
    lim.charge("a", now=1)
    with pytest.raises(HTTPException) as exc:
        lim.charge("a", now=2)
    assert exc.value.status_code == 429 and "с вашего адреса" in exc.value.detail
    lim.charge("b", now=3)
    with pytest.raises(HTTPException) as exc:
        lim.charge("c", now=4)
    assert "на стенде" in exc.value.detail and "Пример из кейса" in exc.value.detail
    lim.charge("a", now=WINDOW_S + 1)  # через час старые анализы выпали из окна


def test_batch_counts_each_resume_and_refusal_charges_nothing(limits) -> None:
    limits(per_ip=3)
    lim = AnalysisLimiter()
    with pytest.raises(HTTPException):
        lim.charge("a", n=4, now=0)
    lim.charge("a", n=3, now=0)  # отказ выше ничего не списал


def test_api_limits_own_files_but_not_the_case_example(limits) -> None:
    limits(per_ip=1)
    client = TestClient(app)
    resume, vac = fixture_file("resume_cook.txt"), fixture_file("vacancy_cook.txt")
    files = [("resume", (resume[1], resume[0])), ("vacancies", (vac[1], vac[0]))]
    headers = {"X-Forwarded-For": "203.0.113.7, 10.0.0.2"}
    first = client.post("/jobs/match", files=files, headers=headers)
    assert first.status_code == 202
    second = client.post("/jobs/match", files=files, headers=headers)
    assert second.status_code == 429 and "Лимит демо-стенда" in second.json()["detail"]
    other = {"X-Forwarded-For": "198.51.100.9"}
    third = client.post("/jobs/match", files=files, headers=other)
    assert third.status_code == 202
    example = client.post("/jobs/match/example", headers=headers)
    assert example.status_code == 202
    _wait_all(client, [r.json()["job_id"] for r in (first, third, example)])


def _wait_all(client: TestClient, job_ids: list[str], timeout: float = 300) -> None:
    deadline = time.monotonic() + timeout
    for job_id in job_ids:
        while client.get(f"/jobs/{job_id}").json()["status"] not in ("done", "failed"):
            assert time.monotonic() < deadline, "задача не завершилась"
            time.sleep(0.2)
