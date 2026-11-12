import pytest
from fastapi.testclient import TestClient

from aihr.api.app import app
from aihr.config import get_settings
from aihr.contracts import CONTRACTS_VERSION, MatchResult
from tests.conftest import fixture_file


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_health(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body.pop("retrieval") in ("bm25", "bm25+embeddings")  # D42: режим поиска виден
    assert body == {"status": "ok", "llm": "none", "contracts_version": CONTRACTS_VERSION}


def test_health_llm_configured(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_BASE_URL", "http://llm.invalid/v1")
    monkeypatch.setenv("LLM_MODEL", "m")
    get_settings.cache_clear()
    assert client.get("/health").json()["llm"] == "configured"


def test_match_example_returns_valid_result(client: TestClient) -> None:
    r = client.post("/match/example")
    assert r.status_code == 200, r.text
    result = MatchResult.model_validate(r.json())
    assert result.resume is not None
    assert result.ranking and len(result.ranking.items) == 3
    assert not result.errors


def test_match_example_by_resume_name(client: TestClient) -> None:
    files = client.get("/example/files").json()
    assert len(files["resumes"]) == 4 and len(files["vacancies"]) == 3
    name = files["resumes"][-1]
    r = client.post("/match/example", params={"resume": name[:8]})
    assert r.status_code == 200
    assert MatchResult.model_validate(r.json()).resume.filename == name  # type: ignore[union-attr]
    assert client.post("/match/example", params={"resume": "нет-такого"}).status_code == 404


def test_match_upload(client: TestClient) -> None:
    resume = fixture_file("resume_cook.txt")
    vac1, vac2 = fixture_file("vacancy_cook.txt"), fixture_file("vacancy_welder.txt")
    r = client.post(
        "/match",
        files=[
            ("resume", (resume[1], resume[0], "text/plain")),
            ("vacancies", (vac1[1], vac1[0], "text/plain")),
            ("vacancies", (vac2[1], vac2[0], "text/plain")),
            ("vacancies", ("битая.docx", b"PK\x03\x04junk", "application/octet-stream")),
        ],
    )
    assert r.status_code == 200, r.text
    result = MatchResult.model_validate(r.json())
    assert len(result.vacancies) == 2
    assert result.errors[0].filename == "битая.docx"

    run = client.get(f"/runs/{result.run_id}")
    assert run.status_code == 200 and run.json()["run_id"] == result.run_id
    out = client.get(f"/runs/{result.run_id}/outbound")
    assert out.status_code == 200 and out.json() == {"run_id": result.run_id, "entries": []}


def test_runs_rejects_bad_ids(client: TestClient) -> None:
    assert client.get("/runs/..%2F..%2Fetc/outbound").status_code in (400, 404)
    assert client.get("/runs/not-a-run/outbound").status_code == 400
    assert client.get("/runs/20260101-000000-abcdef/outbound").status_code == 404


def test_match_requires_files(client: TestClient) -> None:
    assert client.post("/match").status_code == 422


def test_match_fixes_cp1251_filename(client: TestClient) -> None:
    resume = fixture_file("resume_cook.txt")
    vac = fixture_file("vacancy_cook.txt")
    # так имя приходит от curl в Windows: байты cp1251, прочитанные как latin-1
    broken = "Вакансия повара.txt".encode("cp1251")
    body = (
        b'--X\r\nContent-Disposition: form-data; name="resume"; filename="r.txt"\r\n\r\n'
        + resume[0]
        + b'\r\n--X\r\nContent-Disposition: form-data; name="vacancies"; filename="'
        + broken
        + b'"\r\n\r\n'
        + vac[0]
        + b"\r\n--X--\r\n"
    )
    r = client.post(
        "/match", content=body, headers={"Content-Type": "multipart/form-data; boundary=X"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["vacancies"][0]["filename"] == "Вакансия повара.txt"
