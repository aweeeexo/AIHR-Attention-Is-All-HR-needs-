import json

import pytest

from aihr import pipeline
from aihr.config import get_settings
from aihr.contracts import IngestErrorCode, LLMUnavailable, MatchResult, Status
from aihr.llm import LLMClient
from tests.conftest import EchoRequirementsLLM, FakeOpenAI, fixture_file


def _run(*vacancies: tuple[bytes, str], **kw: object) -> MatchResult:
    return pipeline.run(fixture_file("resume_cook.txt"), list(vacancies), **kw)  # type: ignore[arg-type]


def test_end_to_end_without_llm() -> None:
    r = _run(fixture_file("vacancy_cook.txt"), fixture_file("vacancy_welder.txt"))
    assert r.mode == "fallback"  # LLM не настроена
    assert [v.id for v in r.vacancies] == ["V1", "V2"]
    assert r.ranking and len(r.ranking.items) == 2
    assert set(r.reports) == {"V1", "V2"}
    for verdicts in r.verdicts.values():
        assert verdicts  # режим без LLM (T11): правила и совпадение терминов
        assert all(v.computed for v in verdicts if v.status == Status.mismatch)
        assert all(v.decided_by == "fallback" for v in verdicts)
    assert {"ingest", "mask", "match", "score", "report", "total"} <= set(r.timings_ms)


def test_result_saved_to_runs_dir() -> None:
    r = _run(fixture_file("vacancy_cook.txt"))
    path = get_settings().runs_dir / r.run_id / "result.json"
    assert pipeline.RUN_ID_RE.match(r.run_id)
    saved = MatchResult.model_validate_json(path.read_text(encoding="utf-8"))
    assert saved == r


def test_broken_vacancy_does_not_break_run() -> None:
    r = _run(
        (b"", "пустая.docx"),
        fixture_file("vacancy_cook.txt"),
        (b"PK\x03\x04junk", "битая.docx"),
    )
    assert [e.code for e in r.errors] == [IngestErrorCode.empty_file, IngestErrorCode.corrupted]
    assert r.ranking and [s.vacancy_id for s in r.ranking.items] == ["V2"]  # id по порядку загрузки


def test_broken_resume_gives_error_not_crash() -> None:
    r = pipeline.run((b"", "резюме.docx"), [fixture_file("vacancy_cook.txt")])
    assert r.resume is None and r.profile is None and r.ranking is None
    assert r.errors[0].code == IngestErrorCode.empty_file
    assert len(r.vacancies) == 1


def test_failure_in_one_vacancy_is_isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    real = pipeline.score_vacancy

    def flaky(vacancy, reqs, verdicts):
        if vacancy.id == "V1":
            raise RuntimeError("boom")
        return real(vacancy, reqs, verdicts)

    monkeypatch.setattr(pipeline, "score_vacancy", flaky)
    r = _run(fixture_file("vacancy_cook.txt"), fixture_file("vacancy_welder.txt"))
    assert r.ranking and [s.vacancy_id for s in r.ranking.items] == ["V2"]
    assert any("vacancy_cook.txt" in w and "score" in w for w in r.warnings)


def test_no_requirements_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline.fallback, "extract_requirements_fallback", lambda v: [])
    r = _run(fixture_file("vacancy_cook.txt"))
    assert r.errors[0].code == IngestErrorCode.no_requirements
    assert r.ranking and r.ranking.items == []


def test_llm_unavailable_switches_to_fallback(
    monkeypatch: pytest.MonkeyPatch, llm_settings
) -> None:
    def down(*args, **kwargs):
        raise LLMUnavailable("сеть недоступна")

    monkeypatch.setattr(pipeline.extract, "extract_profile", down)
    llm = LLMClient(llm_settings, client=FakeOpenAI([]))
    r = _run(fixture_file("vacancy_cook.txt"), settings=llm_settings, llm=llm)
    assert r.mode == "fallback"
    assert any("LLM недоступна" in w for w in r.warnings)
    assert r.ranking and len(r.ranking.items) == 1


def test_llm_mode_when_configured(llm_settings) -> None:
    llm = LLMClient(llm_settings, client=EchoRequirementsLLM())
    r = _run(fixture_file("vacancy_cook.txt"), settings=llm_settings, llm=llm, save=False)
    assert r.mode == "llm" and not r.warnings
    assert all(v.decided_by == "pass_a" for v in r.verdicts["V1"])


def test_result_json_has_no_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "sk-should-not-leak")
    get_settings.cache_clear()
    r = _run(fixture_file("vacancy_cook.txt"))
    assert "sk-should-not-leak" not in json.dumps(r.model_dump(mode="json"), ensure_ascii=False)
