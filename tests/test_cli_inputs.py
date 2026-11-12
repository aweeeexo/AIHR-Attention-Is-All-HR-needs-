import json
from pathlib import Path

from typer.testing import CliRunner

from aihr.cli import app
from aihr.inputs import case_files, collect_vacancies, looks_like_resume, natural_key
from tests.conftest import CASE_DIR, FIXTURES

runner = CliRunner()


def test_looks_like_resume() -> None:
    assert looks_like_resume(Path("Иванов Алексей_резюме 1.docx"))
    assert looks_like_resume(Path("john_CV.pdf"))
    assert looks_like_resume(Path("Resume-2026.txt"))
    assert not looks_like_resume(Path("Вакансия 1.docx"))
    assert not looks_like_resume(Path("cvetkov.docx"))


def test_natural_sort() -> None:
    names = ["Вакансия 10.docx", "Вакансия 2.docx", "Вакансия 1.docx"]
    assert sorted(names, key=lambda n: natural_key(Path(n))) == [
        "Вакансия 1.docx",
        "Вакансия 2.docx",
        "Вакансия 10.docx",
    ]


def test_case_files_split() -> None:
    resumes, vacancies = case_files(CASE_DIR)
    assert len(resumes) == 4
    assert [p.name for p in vacancies] == ["Вакансия 1.docx", "Вакансия 2.docx", "Вакансия 3.docx"]


def test_collect_vacancies_skips_resumes_and_unsupported() -> None:
    vacancies = collect_vacancies([CASE_DIR])
    assert all(p.suffix == ".docx" for p in vacancies)  # README.md пропущен
    assert len(vacancies) == 3


def test_cli_match_on_fixtures(tmp_path: Path) -> None:
    out = tmp_path / "result.json"
    result = runner.invoke(
        app,
        [
            "match",
            "--resume",
            str(FIXTURES / "resume_cook.txt"),
            "--vacancies",
            str(FIXTURES / "vacancy_cook.txt"),
            "--vacancies",
            str(FIXTURES / "vacancy_welder.txt"),
            "--out",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Рейтинг вакансий" in result.output
    data = json.loads(out.read_text(encoding="utf-8"))
    assert len(data["ranking"]["items"]) == 2


def test_cli_match_directory_excludes_resume() -> None:
    result = runner.invoke(
        app,
        ["match", "--resume", str(FIXTURES / "resume_cook.txt"), "--vacancies", str(FIXTURES)],
    )
    assert result.exit_code == 0, result.output
    assert "V2" in result.output and "V3" not in result.output


def test_cli_demo_passes() -> None:
    result = runner.invoke(app, ["demo"])
    assert result.exit_code == 0, result.output
    assert "demo: всё в порядке" in result.output
    assert "FAIL" not in result.output


def test_cli_extract_commands() -> None:
    reqs = runner.invoke(app, ["extract-requirements", str(FIXTURES / "vacancy_welder.txt")])
    assert reqs.exit_code == 0, reqs.output
    assert json.loads(reqs.output)[0]["id"] == "V1.req1"
    profile = runner.invoke(app, ["extract-profile", str(FIXTURES / "resume_cook.txt")])
    assert profile.exit_code == 0, profile.output
    assert "positions" in json.loads(profile.output)


def test_cli_extract_reports_ingest_error(tmp_path: Path) -> None:
    bad = tmp_path / "bad.docx"
    bad.write_bytes(b"PK\x03\x04junk")
    result = runner.invoke(app, ["extract-requirements", str(bad)])
    assert result.exit_code == 1
    assert "E_CORRUPTED" in result.output
