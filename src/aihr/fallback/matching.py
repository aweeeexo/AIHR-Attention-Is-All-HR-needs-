"""Сопоставление без LLM (T11, шаг 3). Скромно, но честно: неуверенность → «Не указано».

- Доля значимых слов требования в лучшем фрагменте ≥ 0.6: «Соответствует» (опыт — прямое
  доказательство, только список навыков — с пометкой и вопросом).
- 0.34–0.6 и хотя бы два совпавших слова: «Частично», смежное доказательство.
- Пороги (стаж, образование, язык) — через rules.py, как в основном режиме.
- «Не соответствует» ставит только код по порогу. Личные качества не проверяются.
"""

from __future__ import annotations

from aihr.contracts import (
    CandidateProfile,
    Document,
    Evidence,
    EvidenceType,
    ReqKind,
    Requirement,
    Status,
    ThresholdKind,
    Verdict,
)
from aihr.match.rules import apply_rules
from aihr.retrieve import Retriever, roles_for, tokens

MATCH_COVERAGE = 0.6
PARTIAL_COVERAGE = 0.34


def _verdict(req: Requirement, status: Status, comment: str, **kw: object) -> Verdict:
    return Verdict(
        requirement_id=req.id,
        status=status,
        comment=comment[:250],
        decided_by="fallback",
        confidence=kw.pop("confidence", 0.3),  # type: ignore[arg-type]
        **kw,  # type: ignore[arg-type]
    )


def _not_stated(req: Requirement, comment: str) -> Verdict:
    return _verdict(req, Status.not_stated, comment, confidence=0.3)


def _threshold_verdict(
    req: Requirement, profile: CandidateProfile, resume: Document, retriever: Retriever
) -> Verdict:
    """Порог: кандидаты-фрагменты из поиска, дальше решает правило. Не решило — «Не указано»."""
    assert req.threshold is not None
    hits = retriever.search(req.threshold.subject or req.text, req.canonical_terms, k=5,
                            section_roles=roles_for(req.kind))  # fmt: skip
    base = _verdict(
        req,
        Status.not_stated,
        "Без LLM порог проверяется только по датам и уровням в резюме.",
        evidence=[Evidence(fragment_id=fid, quote="") for fid, _ in hits],
    )
    if req.threshold.kind == ThresholdKind.years and req.threshold.subject:
        # Тема порога: места работы, где встречаются слова темы
        topic = set(tokens(req.threshold.subject))
        frag_tokens = {f.id: set(tokens(f.masked_text or f.text)) for f in resume.fragments}
        ids = [
            fid
            for p in profile.positions
            for fid in p.fragment_ids
            if topic and len(topic & frag_tokens.get(fid, set())) >= max(1, len(topic) // 2)
        ]
        base = base.model_copy(
            update={"evidence": [Evidence(fragment_id=f, quote="") for f in ids]}
        )
    ruled = apply_rules(req, base, profile)
    if ruled.status == Status.not_stated:
        return ruled.model_copy(update={"evidence": [], "evidence_type": None})
    return ruled.model_copy(update={"decided_by": "fallback"})


def _term_verdict(req: Requirement, resume: Document, retriever: Retriever) -> Verdict:
    query = set(tokens(req.text)) | {t for term in req.canonical_terms for t in tokens(term)}
    if not query:
        return _not_stated(req, "В требовании нет терминов, которые можно проверить без LLM.")
    by_id = {f.id: f for f in resume.fragments}
    hits = retriever.search(req.text, req.canonical_terms, k=8, section_roles=roles_for(req.kind))
    if not hits:
        return _not_stated(req, "В резюме не найдено упоминаний терминов требования.")
    # Требование с перечислением часто подтверждается соседними строками: покрытие считаем
    # по объединению до трёх лучших фрагментов, в доказательства берём только те, что добавили слова
    found: set[str] = set()
    used: list[str] = []
    for fid, _ in hits[:3]:
        frag = by_id[fid]
        new = (query & set(tokens(frag.masked_text or frag.text))) - found
        if new:
            found |= new
            used.append(fid)
    coverage = len(found) / len(query)
    if not used:
        return _not_stated(req, "В резюме не найдено упоминаний терминов требования.")
    frag = by_id[used[0]]
    missing = sorted(query - found)
    evidence = [Evidence(fragment_id=fid, quote="") for fid in used]
    if coverage >= MATCH_COVERAGE:
        listed_only = all(by_id[f].section_role == "skills" for f in used)
        comment = (
            "Навык есть в списке навыков, но не подтверждён описанием опыта — стоит уточнить."
            if listed_only
            else "Термины требования встречаются в описании опыта."
        )
        return _verdict(
            req,
            Status.match,
            comment,
            evidence=evidence,
            evidence_type=EvidenceType.direct,
            confidence=round(0.4 + 0.3 * coverage, 2),
            needs_review=listed_only,
        )
    if coverage >= PARTIAL_COVERAGE and len(found) >= 2:
        return _verdict(
            req,
            Status.partial,
            "Совпала часть терминов требования; без LLM смысл не проверен.",
            evidence=evidence,
            evidence_type=EvidenceType.adjacent,
            missing="не найдено: " + ", ".join(missing[:6]),
            confidence=round(0.3 + 0.3 * coverage, 2),
        )
    return _not_stated(req, "Явного подтверждения в резюме нет (проверка без LLM).")


def match_vacancy_fallback(
    reqs: list[Requirement],
    profile: CandidateProfile,
    resume: Document,
    retriever: Retriever,
) -> list[Verdict]:
    out = []
    for req in reqs:
        if not req.verifiable or req.kind == ReqKind.soft:
            out.append(_not_stated(req, "Личные качества по тексту резюме не проверяются."))
        elif req.threshold is not None:
            out.append(_threshold_verdict(req, profile, resume, retriever))
        else:
            out.append(_term_verdict(req, resume, retriever))
    return out
