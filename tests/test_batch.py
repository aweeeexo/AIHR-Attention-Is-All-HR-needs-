"""D38: пакет резюме × вакансии — матрица, порядок кандидатов, ошибки, API, CLI."""

from pathlib import Path

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from aihr.api.app import app
from aihr.batch import run_batch
from aihr.cli import app as cli_app
from aihr.config import get_settings
from aihr.contracts import CONTRACTS_VERSION, BatchResult, IngestErrorCode
from tests.conftest import fixture_file

WELDER_RESUME = """Сварщик
Опыт работы
2015 — 2024, ООО «Металл», электрогазосварщик 5 разряда. Сварка трубопроводов, РД и МАДП.
Образование
2014, техникум, сварочное производство.
"""


def _resumes():
    return [fixture_file("resume_cook.txt"), (WELDER_RESUME.encode(), "резюме сварщика.txt")]


def _vacancies():
    return [fixture_file("vacancy_cook.txt"), fixture_file("vacancy_welder.txt")]


def test_batch_matrix_and_order() -> None:
    batch = run_batch(_resumes(), _vacancies())
    assert batch.contracts_version == CONTRACTS_VERSION == 3
    assert [r.resume_id for r in batch.resumes] == ["C1", "C2"]
    assert all(r.run_id and r.error is None for r in batch.resumes)
    assert len(batch.cells) == 4  # 2 кандидата × 2 вакансии
    by = {(c.resume_id, c.vacancy_id): c.score for c in batch.cells}
    for vac in batch.vacancies:
        scores = [by[(rid, vac.vacancy_id)] for rid in vac.candidates]
        assert scores == sorted(scores, reverse=True)  # лучшие первыми — порядок кода
        assert vac.summary
    cook, welder = batch.vacancies
    assert cook.candidates[0] == "C1" and welder.candidates[0] == "C2"
    assert batch.resumes[0].best_vacancy_id == "V1"
    saved = get_settings().runs_dir / "batches" / f"{batch.batch_id}.json"
    assert BatchResult.model_validate_json(saved.read_text(encoding="utf-8")) == batch


def test_broken_resume_does_not_break_batch() -> None:
    batch = run_batch([*_resumes(), (b"\x00\x01garbage", "битое.docx")], _vacancies())
    broken = batch.resumes[2]
    assert broken.error is not None and broken.error.code in set(IngestErrorCode)
    assert all(c.resume_id != "C3" for c in batch.cells)
    assert "Обработано резюме: 2 из 3" in batch.summary


def test_vacancy_error_reported_once() -> None:
    batch = run_batch(_resumes(), [*_vacancies(), (b"", "пустая.txt")])
    assert [e.filename for e in batch.errors] == ["пустая.txt"]


def test_batch_api_and_get() -> None:
    client = TestClient(app)
    files = [("resumes", (n, d)) for d, n in _resumes()]
    files += [("vacancies", (n, d)) for d, n in _vacancies()]
    r = client.post("/match/batch", files=files)
    assert r.status_code == 200, r.text
    batch = BatchResult.model_validate(r.json())
    assert client.get(f"/batches/{batch.batch_id}").json() == r.json()
    run_id = batch.resumes[0].run_id
    assert client.get(f"/runs/{run_id}").status_code == 200  # отчёт кандидата из пакета
    assert client.get("/batches/../etc").status_code in (400, 404)
    assert client.get("/batches/b20260101-000000-abcdef").status_code == 404
    get_settings.cache_clear()


def test_batch_limit(monkeypatch) -> None:
    monkeypatch.setenv("MAX_BATCH_RESUMES", "1")
    get_settings.cache_clear()
    client = TestClient(app)
    files = [("resumes", (n, d)) for d, n in _resumes()]
    files += [("vacancies", (n, d)) for d, n in _vacancies()]
    assert client.post("/match/batch", files=files).status_code == 413
    get_settings.cache_clear()


def test_batch_cli(tmp_path: Path) -> None:
    (tmp_path / "резюме повара.txt").write_bytes(fixture_file("resume_cook.txt")[0])
    (tmp_path / "резюме сварщика.txt").write_text(WELDER_RESUME, encoding="utf-8")
    vac = tmp_path / "вакансии"
    vac.mkdir()
    for data, name in _vacancies():
        (vac / name).write_bytes(data)
    out = CliRunner().invoke(
        cli_app, ["batch", "--resumes", str(tmp_path), "--vacancies", str(vac)]
    )
    assert out.exit_code == 0, out.output
    assert "Обработано резюме: 2 из 2" in out.output
