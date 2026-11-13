"""Профиль кандидата (T05-A): LLM извлекает, код проверяет ссылки и решает тип упоминания навыка.

Даты модель только переписывает (raw_dates); длительность, стаж и уровни считает normalize
(T05-B) в enrich_profile — модель арифметику не делает (D13).
"""

from __future__ import annotations

import logging
import re

from aihr.contracts import (
    CandidateProfile,
    Document,
    Education,
    EducationLevel,
    Fact,
    Fragment,
    Language,
    MentionType,
    Position,
    SkillMention,
)
from aihr.extract.schemas import ExtractedProfile
from aihr.llm import LLMClient
from aihr.normalize import canonicalize
from aihr.normalize.levels import education_from_text
from aihr.retrieve import tokens

log = logging.getLogger(__name__)

PROMPT_ID = "extract/profile"

ROLE_RU = {
    "experience": "Опыт работы",
    "education": "Образование",
    "skills": "Навыки",
    "about": "О себе",
    "contacts": "Контакты",
    "other": "Прочее",
}
_CERT_CATEGORIES = {"certificate", "license", "licence", "сертификат", "удостоверение"}


def _for_prompt(fragments: list[Fragment]) -> list[Fragment]:
    out = []
    for f in fragments:
        role = ROLE_RU.get(f.section_role or "", "без раздела")
        out.append(f.model_copy(update={"masked_text": f"{{{role}}} {f.masked_text}"}))
    return out


def _valid(ids: list[str], known: set[str], what: str) -> list[str]:
    good = [fid for fid in dict.fromkeys(ids) if fid in known]
    if len(good) < len(set(ids)):
        log.info("профиль: у «%s» отброшены несуществующие фрагменты", what)
    return good


def _mentioned(name: str, text_tokens: set[str]) -> bool:
    want = set(tokens(name))
    return bool(want) and want <= text_tokens


def build_profile(resume: Document, extracted: ExtractedProfile) -> CandidateProfile:
    by_id = {f.id: f for f in resume.fragments}
    known = set(by_id)

    positions: list[Position] = []
    for p in extracted.positions:
        ids = _valid(p.fragment_ids, known, "место работы")
        if not ids:
            log.warning("профиль: место работы без существующих фрагментов отброшено")
            continue
        positions.append(
            Position(
                title=p.title.strip() or "должность не указана",
                organization=(p.organization or "").strip() or None,
                start=None,
                end=None,
                raw_dates=(p.raw_dates or "").strip() or None,
                tasks=[t for t in p.tasks if t.strip()],
                achievements=[a for a in p.achievements if a.strip()],
                tools=[t for t in p.tools if t.strip()],
                level=p.level,
                scale=(p.scale or "").strip() or None,
                fragment_ids=ids,
            )
        )

    education: list[Education] = []
    for e in extracted.education:
        ids = _valid(e.fragment_ids, known, "образование")
        if not ids:
            continue
        level = e.level
        if level is None:
            level = education_from_text(" ".join(by_id[f].text for f in ids))
        education.append(
            Education(
                level=level,
                institution=e.institution,
                field=e.field,
                year_end=e.year_end,
                fragment_ids=ids,
            )
        )

    # Тип упоминания навыка решает код: навык есть во фрагментах места работы → подтверждён опытом
    position_fragments = {fid for p in positions for fid in p.fragment_ids}
    experience_tokens = {
        fid: set(tokens(by_id[fid].masked_text or by_id[fid].text)) for fid in position_fragments
    }
    skills: list[SkillMention] = []
    seen: set[str] = set()
    for s in extracted.skills:
        name = s.name.strip()
        key = name.lower()
        if not name or key in seen:
            continue
        ids = _valid(s.fragment_ids, known, name)
        evidence = [fid for fid, toks in experience_tokens.items() if _mentioned(name, toks)]
        ids = list(dict.fromkeys(ids + evidence))
        if not ids:
            continue
        seen.add(key)
        evidenced = bool(set(ids) & position_fragments)
        skills.append(
            SkillMention(
                name=name,
                canonical=canonicalize(name),
                mention_type=MentionType.evidenced if evidenced else MentionType.listed_only,
                fragment_ids=ids,
            )
        )

    languages = [
        Language(name=lang.name.strip(), level_raw=lang.level_raw, fragment_ids=ids)
        for lang in extracted.languages
        if (ids := _valid(lang.fragment_ids, known, lang.name))
    ]

    certificates: list[Fact] = []
    other: list[Fact] = []
    for fact in extracted.facts:
        ids = _valid(fact.fragment_ids, known, fact.text[:30])
        if not ids:
            continue
        item = Fact(
            text=fact.text.strip(),
            category=fact.category.strip().lower() or "other",
            fragment_ids=ids,
        )
        if item.category in _CERT_CATEGORIES:
            certificates.append(item)
        elif item.category == "course":
            education.append(
                Education(
                    level=EducationLevel.course,
                    institution=None,
                    field=item.text,
                    year_end=_year(item.text),
                    fragment_ids=ids,
                )
            )
        else:
            other.append(item)

    return CandidateProfile(
        positions=positions,
        education=education,
        skills=skills,
        languages=languages,
        certificates=certificates,
        other=other,
    )


def _year(text: str) -> int | None:
    m = re.search(r"\b(?:19|20)\d{2}\b", text)
    return int(m.group(0)) if m else None


def extract_profile(resume: Document, llm: LLMClient) -> CandidateProfile:
    extracted = llm.structured(
        PROMPT_ID, {"fragments": _for_prompt(resume.fragments)}, ExtractedProfile
    )
    return build_profile(resume, extracted)
