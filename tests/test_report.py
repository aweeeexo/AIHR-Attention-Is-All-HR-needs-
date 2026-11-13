"""T09: отчёт рекрутеру — разделы кодом, вопросы и «сверх требований» с проверкой сущностей."""

import json

import pytest

from aihr.config import Settings
from aihr.contracts import (
    CandidateProfile,
    DocKind,
    Evidence,
    EvidenceType,
    FitLabel,
    Modality,
    Position,
    Ranking,
    ReqKind,
    Requirement,
    Status,
    Threshold,
    ThresholdKind,
    Verdict,
    YearMonth,
)
from aihr.ingest import load_document
from aihr.llm import LLMClient
from aihr.normalize import enrich_profile, find_terms
from aihr.privacy import PrivacyContext, mask_document
from aihr.report import build_report
from aihr.report.entities import has_stop_phrase, unverified
from aihr.score import rank, score_vacancy
from tests.conftest import FakeOpenAI

RESUME = """Опыт работы
2015 — 2024, ООО «Север», логист. Составлял маршруты доставки в SAP, сократил простой на 15%.
Навыки: Excel, Power BI.
"""
VACANCY = """Логист
Требования:
Опыт работы логистом от 3 лет.
Знание SAP.
Высшее образование.
Английский не ниже B2.
Стрессоустойчивость.
Будет плюсом: Power BI.
"""


@pytest.fixture
def docs():
    ctx = PrivacyContext()
    vac = mask_document(load_document(VACANCY.encode(), "v.txt", DocKind.vacancy, "V1"), ctx)
    res = mask_document(load_document(RESUME.encode(), "r.txt", DocKind.resume, "R"), ctx)
    return vac, res


def _frag(doc, start: str) -> str:
    return next(f.id for f in doc.fragments if f.text.startswith(start))


def _setup(vac, res):
    exp = _frag(res, "2015")
    skills = _frag(res, "Навыки")
    reqs = [
        Requirement(
            id=f"V1.req{i}",
            vacancy_id="V1",
            text=text,
            kind=kind,
            modality=mod,
            modality_marker=None,
            modality_reason="",
            threshold=th,
            verifiable=ver,
            canonical_terms=find_terms(text),
            source_fragment_ids=[_frag(vac, src)],
        )
        for i, (text, kind, mod, th, ver, src) in enumerate(
            [
                (
                    "Опыт работы логистом от 3 лет",
                    ReqKind.experience,
                    Modality.must,
                    Threshold(kind=ThresholdKind.years, value="3", subject="логистика"),
                    True,
                    "Опыт",
                ),
                ("Знание SAP", ReqKind.skill, Modality.must, None, True, "Знание"),
                ("Высшее образование", ReqKind.education, Modality.must, None, True, "Высшее"),
                (
                    "Английский не ниже B2",
                    ReqKind.language,
                    Modality.must,
                    None,
                    True,
                    "Английский",
                ),
                ("Стрессоустойчивость", ReqKind.soft, Modality.must, None, False, "Стресс"),
                ("Power BI", ReqKind.skill, Modality.nice, None, True, "Будет"),
            ],
            1,
        )
    ]

    def v(i: int, status: Status, ids: list[str], **kw) -> Verdict:
        return Verdict(
            requirement_id=f"V1.req{i}",
            status=status,
            comment="коммент",
            confidence=0.8,
            decided_by="pass_a",
            evidence=[
                Evidence(fragment_id=f, quote=next(x.text for x in res.fragments if x.id == f))
                for f in ids
            ],
            **kw,
        )

    verdicts = [
        v(
            1,
            Status.match,
            [exp],
            evidence_type=EvidenceType.direct,
            computed="по теме: 2015–2024 = ≈ 9 г. ≥ 3 лет",
        ),
        v(2, Status.match, [exp], evidence_type=EvidenceType.direct),
        v(3, Status.not_stated, []),
        v(
            4,
            Status.partial,
            [skills],
            evidence_type=EvidenceType.adjacent,
            missing="уровень не указан",
        ),
        v(5, Status.not_stated, []),
        v(6, Status.match, [skills], evidence_type=EvidenceType.direct),
    ]
    position = Position(
        title="логист",
        organization="ООО «Север»",
        start=None,
        end=None,
        raw_dates="2015 — 2024",
        achievements=["сократил простой на 15%"],
        fragment_ids=[exp],
    )
    from aihr.contracts import MentionType, SkillMention

    profile = enrich_profile(
        CandidateProfile(
            positions=[position],
            skills=[
                SkillMention(
                    name="Power BI",
                    canonical="power_bi",
                    mention_type=MentionType.listed_only,
                    fragment_ids=[skills],
                )
            ],
        ),
        YearMonth(year=2026, month=11),
    )
    return reqs, verdicts, profile


def _llm(*answers: dict) -> LLMClient:
    s = Settings(_env_file=None, llm_base_url="http://x/v1", llm_model="m")  # type: ignore[call-arg]
    return LLMClient(s, client=FakeOpenAI([json.dumps(a, ensure_ascii=False) for a in answers]))


def _report(docs, llm=None, label_ranking=None):
    vac, res = docs
    reqs, verdicts, profile = _setup(vac, res)
    score = score_vacancy(vac, reqs, verdicts)
    return (
        build_report(vac, reqs, verdicts, score, profile, res, llm, label_ranking),
        reqs,
        res,
        score,
    )


def test_rows_order_and_quotes(docs) -> None:
    report, _reqs, _res, _ = _report(docs)
    order = [(r.modality.value, r.status.value) for r in report.rows]
    assert order[:4] == [
        ("must", "partial"),
        ("must", "not_stated"),
        ("must", "not_stated"),
        ("must", "match"),
    ]
    assert order[-1] == ("nice", "match")
    assert all(r.vacancy_quote for r in report.rows)
    v = report.verification
    assert v.quotes_total == v.quotes_verified > 0


def test_sections_by_code(docs) -> None:
    report, reqs, res, _ = _report(docs)
    strengths = [p.text for p in report.strengths]
    assert any(t.startswith("Опыт с запасом: ≈ 9 г.") for t in strengths)  # 9 лет ≥ 1.5 × 3
    assert any("15%" in t for t in strengths)  # достижение с числом
    assert any("закрывается обучением" in p.text for p in report.gaps)  # смежный навык
    risk_texts = " ".join(p.text for p in report.risks)
    assert "Высшее образование" in risk_texts  # обязательное «не указано»
    assert "только в списке навыков" in risk_texts
    assert "Стрессоустойчивость" not in risk_texts  # непроверяемое — не риск, а вопрос
    ids = {r.id for r in reqs}
    frags = {f.id for f in res.fragments}
    for p in [*report.strengths, *report.gaps, *report.risks]:
        assert set(p.requirement_ids) <= ids and set(p.fragment_ids) <= frags
    for text in [p.text for p in report.risks] + [
        report.recruiter_recommendation,
        report.candidate_message,
    ]:
        assert not has_stop_phrase(text)


def test_template_questions_without_llm(docs) -> None:
    report, reqs, _, _ = _report(docs)
    qs = {q.requirement_id: q for q in report.questions}
    assert set(qs) <= {r.id for r in reqs}
    assert qs["V1.req5"].kind == "behavioral"  # личное качество
    assert qs["V1.req3"].why == "в резюме нет сведений"
    assert report.verification.generated_entities_unverified == 0


def test_invented_fact_in_questions_is_caught(docs) -> None:
    bad = {
        "questions": [
            {
                "requirement_id": "V1.req3",
                "text": "Где вы получили высшее образование в МГУ в 2010 году?",
                "kind": "factual",
                "why": "x",
            },
            {
                "requirement_id": "V1.req4",
                "text": "Какой у вас уровень английского?",
                "kind": "factual",
                "why": "уровень",
            },
        ]
    }
    report, _, _, _ = _report(docs, _llm(bad, bad, {"items": []}))
    qs = {q.requirement_id: q.text for q in report.questions}
    assert "МГУ" not in qs["V1.req3"] and "2010" not in qs["V1.req3"]  # заменён шаблоном
    assert qs["V1.req4"] == "Какой у вас уровень английского?"  # проверенный вопрос остался
    assert report.verification.generated_entities_unverified == 0


def test_beyond_requirements_checked(docs) -> None:
    _vac, res = docs
    exp = _frag(res, "2015")
    answer = {
        "items": [
            {"text": "Сократил простой на 15%", "fragment_ids": [exp]},
            {"text": "Руководил командой из 20 человек", "fragment_ids": [exp]},  # нет в фрагменте
            {"text": "Что-то", "fragment_ids": ["R999"]},
        ]
    }
    report, _, _, _ = _report(docs, _llm({"questions": []}, answer))
    assert [p.text for p in report.beyond_requirements] == ["Сократил простой на 15%"]


def test_letter_and_recommendation_have_only_known_facts(docs) -> None:
    report, reqs, res, score = _report(docs)
    facts = " ".join(
        [
            *(r.text for r in reqs),
            *(q.text for q in report.questions),
            score.title or "",
            *(f.text for f in res.fragments),
        ]
    )
    for text in (report.recruiter_recommendation, report.candidate_message):
        assert not [e for e in unverified(text, facts) if not e.replace(".", "").isdigit()]
    assert "Следующий шаг" in report.recruiter_recommendation


def test_not_fit_offers_better_vacancy(docs) -> None:
    vac, res = docs
    reqs, verdicts, profile = _setup(vac, res)
    bad = [
        x.model_copy(
            update={
                "status": Status.mismatch,
                "evidence_type": EvidenceType.direct,
                "evidence": x.evidence or verdicts[0].evidence,
            }
        )
        for x in verdicts
    ]
    low = score_vacancy(vac, reqs, bad)
    other_doc = vac.model_copy(update={"id": "V2", "title": "Диспетчер"})
    high = score_vacancy(other_doc, reqs, verdicts).model_copy(update={"label": FitLabel.fits})
    ranking: Ranking = rank([low, high])
    report = build_report(vac, reqs, bad, low, profile, res, None, ranking)
    assert low.label == FitLabel.not_fit
    assert "«Диспетчер»" in report.recruiter_recommendation
    assert (
        "«Диспетчер»" in report.candidate_message
        and "Спасибо за интерес" in report.candidate_message
    )
