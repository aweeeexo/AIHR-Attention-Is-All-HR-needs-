"""Отчёт рекрутеру (T09). T00 — шаблонный отчёт из проверенных вердиктов, без LLM.

Таблицу, цитаты и счётчики проверки собирает код. Тексты LLM с проверкой сущностей — T09.
"""

from __future__ import annotations

from aihr.contracts import (
    STATUS_RU,
    CandidateProfile,
    Document,
    FitLabel,
    Modality,
    Point,
    Question,
    Report,
    Requirement,
    RequirementRow,
    Status,
    VacancyScore,
    Verdict,
    VerificationStats,
)
from aihr.llm import LLMClient

LABEL_RU = {
    FitLabel.fits: "подходит",
    FitLabel.fits_with_caveats: "подходит с оговорками",
    FitLabel.not_fit: "не подходит",
}


def _quote(doc: Document, fragment_ids: list[str]) -> str:
    by_id = {f.id: f.text for f in doc.fragments}
    return " … ".join(by_id[fid] for fid in fragment_ids if fid in by_id)


def build_report(
    vacancy: Document,
    reqs: list[Requirement],
    verdicts: list[Verdict],
    score: VacancyScore,
    profile: CandidateProfile,
    resume: Document,
    llm: LLMClient,
) -> Report:
    by_req = {v.requirement_id: v for v in verdicts}
    resume_text = {f.id: f.text for f in resume.fragments}
    rows: list[RequirementRow] = []
    strengths: list[Point] = []
    gaps: list[Point] = []
    risks: list[Point] = []
    questions: list[Question] = []
    quotes_total = quotes_verified = 0

    for req in reqs:
        v = by_req.get(req.id)
        status = v.status if v else Status.not_stated
        evidence = v.evidence if v else []
        quotes_total += len(evidence)
        quotes_verified += sum(1 for e in evidence if resume_text.get(e.fragment_id) == e.quote)
        rows.append(
            RequirementRow(
                requirement_id=req.id,
                requirement=req.text,
                modality=req.modality,
                vacancy_quote=_quote(vacancy, req.source_fragment_ids),
                resume_evidence=evidence,
                status=status,
                status_ru=STATUS_RU[status],
                evidence_type=v.evidence_type if v else None,
                comment=v.comment if v else "Вердикт не получен.",
                computed=v.computed if v else None,
            )
        )
        point = Point(
            text=req.text,
            requirement_ids=[req.id],
            fragment_ids=[e.fragment_id for e in evidence],
        )
        if status == Status.match:
            strengths.append(point)
        elif status in (Status.partial, Status.mismatch):
            gaps.append(point)
        elif status == Status.not_stated:
            if req.modality == Modality.must:
                risks.append(point)
            questions.append(
                Question(
                    requirement_id=req.id,
                    text=f"Расскажите, пожалуйста, о вашем опыте: {req.text}",
                    kind="factual",
                    why="в резюме нет сведений по этому требованию",
                )
            )

    recommendation = (
        f"Метка: {LABEL_RU[score.label]}. Балл {score.score:g} "
        f"(от {score.score_min:g} до {score.score_max:g}). {score.explanation}"
    )
    return Report(
        vacancy_id=vacancy.id,
        rows=rows,
        strengths=strengths,
        gaps=gaps,
        risks=risks,
        questions=questions,
        beyond_requirements=[],
        recruiter_recommendation=recommendation,
        candidate_message="Здравствуйте! Спасибо за отклик. Мы изучили резюме и хотим уточнить "
        "несколько деталей.",
        verification=VerificationStats(
            quotes_total=quotes_total,
            quotes_verified=quotes_verified,
            generated_entities_total=0,
            generated_entities_unverified=0,
        ),
    )
