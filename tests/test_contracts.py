"""Каждая модель контракта строится из примера и переживает JSON туда и обратно."""

import inspect

import pytest
from pydantic import BaseModel, ValidationError

from aihr import contracts as c


def _examples() -> dict[type[BaseModel], BaseModel]:
    frag_r = c.Fragment(
        id="R3",
        order=3,
        section="Опыт работы",
        section_role="experience",
        source=c.FragmentSource.list_item,
        text="Готовил блюда европейской кухни на пароконвектомате, 2019–2023",
        masked_text="Готовил блюда европейской кухни на пароконвектомате, 2019–2023",
    )
    frag_v = c.Fragment(
        id="V1.2",
        order=2,
        section="Требования",
        section_role="requirements",
        source=c.FragmentSource.table_cell,
        text="Опыт работы поваром от 3 лет",
    )
    ym_start = c.YearMonth(year=2019, month=3)
    ym_end = c.YearMonth(year=2023)
    resume = c.Document(
        id="R",
        content_hash="a3f91c0d22be",
        kind=c.DocKind.resume,
        filename="Резюме.docx",
        fragments=[frag_r],
    )
    vacancy = c.Document(
        id="V1",
        content_hash="0123456789ab",
        kind=c.DocKind.vacancy,
        filename="Вакансия.docx",
        title="Повар",
        fragments=[frag_v],
        warnings=["документ обрезан"],
    )
    threshold = c.Threshold(kind=c.ThresholdKind.years, value="3", subject="работа поваром")
    req = c.Requirement(
        id="V1.req1",
        vacancy_id="V1",
        text="Опыт работы поваром от 3 лет",
        kind=c.ReqKind.experience,
        modality=c.Modality.must,
        modality_marker=None,
        modality_reason="раздел «Требования»",
        threshold=threshold,
        source_fragment_ids=["V1.2"],
    )
    position = c.Position(
        title="Повар",
        organization="ООО «Пример»",
        start=ym_start,
        end=ym_end,
        raw_dates="03.2019 — 2023",
        duration_months=46,
        dates_approximate=True,
        tasks=["приготовление блюд"],
        tools=["пароконвектомат"],
        level=c.TaskLevel.independent,
        fragment_ids=["R3"],
    )
    education = c.Education(
        level=c.EducationLevel.bachelor,
        institution="Университет",
        field="Технология продукции общественного питания",
        year_end=2018,
        fragment_ids=["R3"],
    )
    skill = c.SkillMention(
        name="пароконвектомат",
        canonical="combi_oven",
        mention_type=c.MentionType.evidenced,
        years=3.8,
        last_used_year=2023,
        fragment_ids=["R3"],
    )
    language = c.Language(name="английский", level_raw="B1", cefr="B1", fragment_ids=["R3"])
    fact = c.Fact(text="Санитарная книжка", category="certificate", fragment_ids=["R3"])
    profile = c.CandidateProfile(
        positions=[position],
        education=[education],
        skills=[skill],
        languages=[language],
        certificates=[fact],
        total_experience_months=46,
        gaps_months=[(c.YearMonth(year=2023, month=6), c.YearMonth(year=2024, month=1))],
    )
    evidence = c.Evidence(fragment_id="R3", quote=frag_r.text)
    verdict = c.Verdict(
        requirement_id="V1.req1",
        status=c.Status.partial,
        evidence_type=c.EvidenceType.direct,
        evidence=[evidence],
        missing="не хватает 2 мес. до порога",
        comment="Поваром работал, стаж чуть ниже порога",
        confidence=0.8,
        computed="03.2019–2023 = 3 г. 10 мес.",
        partial_value=0.95,
        decided_by="rule",
    )
    counts = c.StatusCounts(total=1, partial=1)
    score = c.VacancyScore(
        vacancy_id="V1",
        title="Повар",
        score=47.5,
        score_min=47.5,
        score_max=47.5,
        must=counts,
        nice=c.StatusCounts(),
        blocking_gaps=[],
        label=c.FitLabel.fits_with_caveats,
        top_plus=["V1.req1"],
        top_minus=["V1.req1"],
        explanation="Закрыто частично 1 из 1 обязательных.",
    )
    ranking = c.Ranking(
        items=[score], best_vacancy_id="V1", comparison=[], formula="S = 100·Σwv/Σw"
    )
    point = c.Point(text="Опыт работы поваром", requirement_ids=["V1.req1"], fragment_ids=["R3"])
    question = c.Question(
        requirement_id="V1.req1",
        text="Сколько лет вы работаете поваром?",
        kind="factual",
        why="стаж ниже порога",
    )
    row = c.RequirementRow(
        requirement_id="V1.req1",
        requirement=req.text,
        modality=c.Modality.must,
        vacancy_quote=frag_v.text,
        resume_evidence=[evidence],
        status=c.Status.partial,
        status_ru=c.STATUS_RU[c.Status.partial],
        evidence_type=c.EvidenceType.direct,
        comment=verdict.comment,
        computed=verdict.computed,
    )
    stats = c.VerificationStats(
        quotes_total=1,
        quotes_verified=1,
        generated_entities_total=0,
        generated_entities_unverified=0,
    )
    report = c.Report(
        vacancy_id="V1",
        rows=[row],
        strengths=[point],
        gaps=[],
        risks=[],
        questions=[question],
        beyond_requirements=[],
        recruiter_recommendation="Пригласить на интервью",
        candidate_message="Здравствуйте!",
        verification=stats,
    )
    error = c.IngestError(
        code=c.IngestErrorCode.corrupted,
        filename="битый.docx",
        message="Файл повреждён",
        hint="Пересохраните в docx",
    )
    result = c.MatchResult(
        run_id="20261112-120000-abcd",
        mode="llm",
        resume=resume,
        profile=profile,
        vacancies=[vacancy],
        requirements={"V1": [req]},
        verdicts={"V1": [verdict]},
        ranking=ranking,
        reports={"V1": report},
        errors=[error],
        timings_ms={"total": 10},
    )
    items: list[BaseModel] = [
        frag_r,
        error,
        resume,
        threshold,
        req,
        ym_start,
        position,
        education,
        skill,
        language,
        fact,
        profile,
        evidence,
        verdict,
        counts,
        score,
        ranking,
        point,
        question,
        row,
        stats,
        report,
        result,
    ]
    return {type(m): m for m in items}


EXAMPLES = _examples()


def _contract_models() -> list[type[BaseModel]]:
    return [
        obj
        for _, obj in inspect.getmembers(c, inspect.isclass)
        if issubclass(obj, BaseModel) and obj is not BaseModel and obj.__module__ == c.__name__
    ]


def test_every_model_has_example() -> None:
    missing = [m.__name__ for m in _contract_models() if m not in EXAMPLES]
    assert not missing, f"нет примера для: {missing}"


@pytest.mark.parametrize("model", list(EXAMPLES), ids=lambda m: m.__name__)
def test_roundtrip(model: type[BaseModel]) -> None:
    obj = EXAMPLES[model]
    restored = model.model_validate_json(obj.model_dump_json())
    assert restored == obj


def test_status_ru_covers_all_statuses() -> None:
    assert set(c.STATUS_RU) == set(c.Status)


def test_requirement_needs_source_fragment() -> None:
    with pytest.raises(ValidationError):
        c.Requirement(
            id="V1.req1",
            vacancy_id="V1",
            text="x",
            kind=c.ReqKind.skill,
            modality=c.Modality.nice,
            modality_marker=None,
            modality_reason="",
            source_fragment_ids=[],
        )


def test_ingest_failure_carries_error() -> None:
    err = EXAMPLES[c.IngestError]
    exc = c.IngestFailure(err)  # type: ignore[arg-type]
    assert exc.error is err
    assert "E_CORRUPTED" in str(exc)
