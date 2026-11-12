"""Отчёт рекрутеру (T09): сначала доказательства, потом текст.

Таблицу, сильные стороны, пробелы, риски, рекомендацию и письмо собирает код из проверенных
вердиктов. LLM пишет только вопросы кандидату и «сверх требований» — по проверенным фактам и
с проверкой сущностей; непроверенное заменяется шаблоном (принцип 6).
"""

from __future__ import annotations

from aihr.config import get_settings
from aihr.contracts import (
    CandidateProfile,
    Document,
    Ranking,
    Report,
    Requirement,
    VacancyScore,
    Verdict,
    VerificationStats,
)
from aihr.llm import LLMClient
from aihr.report import generated, sections, texts
from aihr.report.texts import LABEL_RU

__all__ = ["LABEL_RU", "build_report"]


def build_report(
    vacancy: Document,
    reqs: list[Requirement],
    verdicts: list[Verdict],
    score: VacancyScore,
    profile: CandidateProfile,
    resume: Document,
    llm: LLMClient | None,
    ranking: Ranking | None = None,
) -> Report:
    by_req = {v.requirement_id: v for v in verdicts}
    rows = sections.rows(vacancy, reqs, by_req)

    resume_text = {f.id: f.text for f in resume.fragments}
    vacancy_ids = {f.id for f in vacancy.fragments}
    quotes_total = sum(len(r.resume_evidence) for r in rows) + sum(
        len(req.source_fragment_ids) for req in reqs
    )
    quotes_verified = sum(
        1 for r in rows for e in r.resume_evidence if resume_text.get(e.fragment_id) == e.quote
    ) + sum(1 for req in reqs for fid in req.source_fragment_ids if fid in vacancy_ids)

    stats = generated.EntityStats()
    questions = generated.questions(reqs, by_req, generated.listed_only_terms(profile), llm, stats)
    beyond = generated.beyond_requirements(reqs, by_req, resume, llm, stats)

    return Report(
        vacancy_id=vacancy.id,
        rows=rows,
        strengths=sections.strengths(reqs, by_req, profile),
        gaps=sections.gaps(reqs, by_req),
        risks=sections.risks(reqs, by_req, profile, get_settings().today_ym()),
        questions=questions,
        beyond_requirements=beyond,
        recruiter_recommendation=texts.recommendation(score, reqs, by_req, questions, ranking),
        candidate_message=texts.candidate_message(score, reqs, by_req, questions, ranking),
        verification=VerificationStats(
            quotes_total=quotes_total,
            quotes_verified=quotes_verified,
            generated_entities_total=stats.total,
            generated_entities_unverified=stats.unverified,
        ),
    )
