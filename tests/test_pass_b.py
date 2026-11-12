"""T07, шаги 5–6: проход B для спорных требований (заглушка LLM)."""

import json

import pytest

from aihr.config import Settings
from aihr.contracts import (
    CandidateProfile,
    DocKind,
    Evidence,
    Modality,
    ReqKind,
    Requirement,
    Status,
    Verdict,
)
from aihr.ingest import load_document
from aihr.llm import LLMClient
from aihr.match.pass_b import MAX_PER_VACANCY, disputed, pass_b
from aihr.normalize import find_terms
from aihr.privacy import PrivacyContext, mask_document
from aihr.retrieve import Retriever
from tests.conftest import FakeOpenAI

RESUME = """Опыт работы
2019 — 2024, ООО «Пример», инженер-конструктор. Проектировал узлы в Автокад и Компас.
Чертил сборочные чертежи по ЕСКД.
Образование
2018, технический университет, машиностроение.
"""


@pytest.fixture
def resume():
    return mask_document(
        load_document(RESUME.encode(), "r.txt", DocKind.resume, "R"), PrivacyContext()
    )


def _req(
    i: int, text: str, modality: Modality = Modality.must, verifiable: bool = True
) -> Requirement:
    return Requirement(
        id=f"V1.req{i}",
        vacancy_id="V1",
        text=text,
        kind=ReqKind.skill,
        modality=modality,
        modality_marker=None,
        modality_reason="",
        canonical_terms=find_terms(text),
        verifiable=verifiable,
        source_fragment_ids=["V1.2"],
    )


def _verdict(rid: str, status: Status, conf: float = 0.9, review: bool = False, ids=()) -> Verdict:
    return Verdict(
        requirement_id=rid,
        status=status,
        comment="проход A",
        confidence=conf,
        decided_by="pass_a",
        needs_review=review,
        evidence=[Evidence(fragment_id=f, quote="") for f in ids],
    )


def test_disputed_selection_and_order() -> None:
    reqs = [
        _req(1, "a"),
        _req(2, "b"),
        _req(3, "c", Modality.nice),
        _req(4, "d"),
        _req(5, "e", verifiable=False),
        _req(6, "f", Modality.nice),
        _req(7, "g"),
    ]
    verdicts = [
        _verdict("V1.req1", Status.match),  # уверенный match — не спорный
        _verdict("V1.req2", Status.partial),
        _verdict("V1.req3", Status.match, conf=0.4),
        _verdict("V1.req4", Status.not_stated),  # обязательное без подтверждения — первым
        _verdict("V1.req5", Status.not_stated),  # непроверяемое — не тратим вызов
        _verdict("V1.req6", Status.not_stated),  # желательное «не указано» — не спорное
        _verdict("V1.req7", Status.match, review=True),
    ]
    order = [r.id for r, _ in disputed(reqs, verdicts)]
    assert order == ["V1.req4", "V1.req7", "V1.req2", "V1.req3"]


def test_disputed_is_capped() -> None:
    reqs = [_req(i, f"t{i}") for i in range(1, 20)]
    verdicts = [_verdict(r.id, Status.not_stated) for r in reqs]
    assert len(disputed(reqs, verdicts)) == MAX_PER_VACANCY


def _llm(*answers: str) -> tuple[LLMClient, FakeOpenAI]:
    fake = FakeOpenAI(list(answers))
    s = Settings(_env_file=None, llm_base_url="http://x/v1", llm_model="m")  # type: ignore[call-arg]
    return LLMClient(s, client=fake), fake


def test_pass_b_overrides_and_flags_disagreement(resume) -> None:
    fid = next(f.id for f in resume.fragments if "Автокад" in f.text)
    req = _req(1, "Знание AutoCAD")
    answer = {
        "requirement_id": "чужой",
        "reasoning": "…",
        "status": "match",
        "evidence_type": "direct",
        "fragment_ids": [fid],
        "comment": "Проектировал в AutoCAD.",
    }
    llm, fake = _llm(json.dumps(answer, ensure_ascii=False))
    out = pass_b(
        [req],
        [_verdict(req.id, Status.not_stated)],
        CandidateProfile(),
        resume,
        Retriever(resume, embeddings=False),
        llm,
    )
    v = out[0]
    assert v.status == Status.match and v.decided_by == "pass_b" and v.needs_review
    assert "проверить вручную" in v.comment
    assert v.evidence[0].quote.startswith("2019 — 2024")  # цитату подставил код
    user = fake.completions.calls[0]["messages"][1]["content"]
    assert (
        f"[{fid}]" in user and "Предварительный вердикт" in user
    )  # поиск нашёл фрагмент «Автокад»


def test_pass_b_same_status_no_review(resume) -> None:
    fid = next(f.id for f in resume.fragments if "Автокад" in f.text)
    req = _req(1, "Знание AutoCAD")
    answer = {
        "requirement_id": req.id,
        "reasoning": "…",
        "status": "partial",
        "evidence_type": "direct",
        "fragment_ids": [fid],
        "missing": "версия не указана",
        "comment": "ок",
    }
    llm, _ = _llm(json.dumps(answer, ensure_ascii=False))
    out = pass_b(
        [req],
        [_verdict(req.id, Status.partial, ids=[fid])],
        CandidateProfile(),
        resume,
        Retriever(resume, embeddings=False),
        llm,
    )
    assert out[0].status == Status.partial and not out[0].needs_review


def test_pass_b_bad_output_keeps_pass_a(resume) -> None:
    req = _req(1, "Знание AutoCAD")
    llm, _ = _llm("не json", "не json", "не json")
    previous = _verdict(req.id, Status.not_stated)
    out = pass_b(
        [req], [previous], CandidateProfile(), resume, Retriever(resume, embeddings=False), llm
    )
    assert out[0] == previous


def test_nothing_found_no_call(resume) -> None:
    req = _req(1, "Пилотирование Boeing 737")
    llm, fake = _llm()
    out = pass_b(
        [req],
        [_verdict(req.id, Status.not_stated)],
        CandidateProfile(),
        resume,
        Retriever(resume, embeddings=False),
        llm,
    )
    assert out[0].status == Status.not_stated and fake.completions.calls == []
