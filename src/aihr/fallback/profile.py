"""Профиль кандидата без LLM (T11, шаг 2): места работы по датам, образование, навыки, языки.

Даты и стаж дальше считает normalize (enrich_profile), как и в основном режиме.
"""

from __future__ import annotations

import re

from aihr.contracts import (
    CandidateProfile,
    Document,
    Education,
    Fact,
    Fragment,
    Language,
    MentionType,
    Position,
    SkillMention,
)
from aihr.normalize import canonicalize
from aihr.normalize.levels import education_from_text
from aihr.retrieve import tokens

_MONTH = (
    r"(?:январ\w*|феврал\w*|март\w*|апрел\w*|ма[йя]|июн\w*|июл\w*|август\w*|сентябр\w*"
    r"|октябр\w*|ноябр\w*|декабр\w*|jan\w*|feb\w*|mar\w*|apr\w*|may|jun\w*|jul\w*|aug\w*"
    r"|sep\w*|oct\w*|nov\w*|dec\w*)"
)
_POINT = (
    rf"(?:(?:0?[1-9]|1[0-2])[./](?:19|20)\d{{2}}|{_MONTH}\.?\s+(?:19|20)\d{{2}}|(?:19|20)\d{{2}})"
)
_END = (
    r"(?:по\s*н\.?\s*в\.?|н\.\s*в\.?|по\s+настоящ\w*\s+\w+|настоящ\w*\s+время|сейчас"
    r"|present|now|current)"
)
DATE_RANGE = re.compile(
    rf"(?i)(?:с\s+)?{_POINT}\s*(?:г\.?)?\s*(?:—|–|-|‐|по|to)\s*(?:{_POINT}|{_END})"
    rf"|(?i:с\s+){_POINT}"
)
_ORG = re.compile(
    r"(?:\b(?:ООО|ОАО|ЗАО|ПАО|АО|ИП|НКО|ГБУ|ГУП|ФГУП|ФГБУ|МУП|LLC|Ltd|Inc|GmbH|Corp)\b[^,;]{0,60}"
    r"|«[^»]{2,60}»)"
)
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_INSTITUTION = re.compile(
    r"(?i)университет|институт|академи|колледж|техникум|училищ|лицей|школ|консерватори"
    r"|university|institute|college|academy|school|\b[А-ЯЁ]{2,6}У\b|\bМГУ\b"
)
_LANG = re.compile(
    r"(?i)(английск\w*|немецк\w*|французск\w*|испанск\w*|итальянск\w*|китайск\w*|японск\w*"
    r"|корейск\w*|арабск\w*|турецк\w*|русск\w*|english|german|french|spanish|chinese|russian)"
)
_CERT = re.compile(
    r"(?i)сертификат|удостоверени|аккредитац|лицензи|свидетельств|certificat|license"
)
_SKILL_SPLIT = re.compile(r"\s*(?:,|;|•|·|\||/|\s—\s|\s-\s)\s*")


def _text(f: Fragment) -> str:
    return f.masked_text or f.text


def _positions(resume: Document) -> list[Position]:
    exp = [f for f in resume.fragments if f.section_role == "experience"]
    blocks: list[tuple[str, list[Fragment]]] = []
    for frag in exp:
        m = DATE_RANGE.search(frag.text)
        if m:
            blocks.append((m.group(0), [frag]))
        elif blocks:
            blocks[-1][1].append(frag)
    positions = []
    for raw_dates, frags in blocks:
        first = frags[0].text
        title = DATE_RANGE.sub("", first).strip(" ,.:—–-()")
        if len(title) < 3 and len(frags) > 1:
            title = frags[1].text
        org = None
        for f in frags[:4]:
            m = _ORG.search(f.text)
            if m:
                org = m.group(0).strip(" ,.")
                break
        positions.append(
            Position(
                title=title[:150] or "должность не распознана",
                organization=org,
                start=None,
                end=None,
                raw_dates=raw_dates,
                tasks=[f.text for f in frags[1:8]],
                fragment_ids=[f.id for f in frags],
            )
        )
    return positions


def _education(resume: Document) -> list[Education]:
    edu = [f for f in resume.fragments if f.section_role == "education" and not _is_heading(f)]
    out: list[Education] = []
    current: list[Fragment] = []

    def flush() -> None:
        if not current:
            return
        text = " ".join(f.text for f in current)
        years = [int(y) for y in _YEAR.findall(text)]
        inst = next((f.text for f in current if _INSTITUTION.search(f.text)), None)
        out.append(
            Education(
                level=education_from_text(text),
                institution=inst[:150] if inst else None,
                field=None,
                year_end=max(years) if years else None,
                fragment_ids=[f.id for f in current],
            )
        )

    for frag in edu:
        starts_new = bool(_YEAR.search(frag.text) or _INSTITUTION.search(frag.text))
        if starts_new and current and (_YEAR.search(" ".join(f.text for f in current))):
            flush()
            current = []
        current.append(frag)
    flush()
    return out


def _is_heading(frag: Fragment) -> bool:
    return bool(frag.section) and frag.text.rstrip(":").strip() == (frag.section or "").strip()


def _skills(resume: Document, positions: list[Position]) -> list[SkillMention]:
    exp_frags = [f for f in resume.fragments if f.section_role == "experience"]
    exp_tokens = {f.id: set(tokens(_text(f))) for f in exp_frags}
    seen: set[str] = set()
    out: list[SkillMention] = []
    for frag in resume.fragments:
        if frag.section_role != "skills" or _is_heading(frag) or _LANG.search(frag.text):
            continue
        body = frag.text.split(":", 1)[1] if ":" in frag.text[:40] else frag.text
        for item in _SKILL_SPLIT.split(body):
            name = item.strip(" .")
            if not 1 < len(name) <= 40 or name.lower() in seen:
                continue
            seen.add(name.lower())
            item_tokens = set(tokens(name))
            evidence = [
                fid for fid, toks in exp_tokens.items() if item_tokens and item_tokens <= toks
            ]
            out.append(
                SkillMention(
                    name=name,
                    canonical=canonicalize(name),
                    mention_type=MentionType.evidenced if evidence else MentionType.listed_only,
                    fragment_ids=[frag.id, *evidence],
                )
            )
    return out


def _languages(resume: Document) -> list[Language]:
    out: list[Language] = []
    names: set[str] = set()
    for frag in resume.fragments:
        if frag.section_role not in ("skills", "about", "education", "other"):
            continue
        for m in _LANG.finditer(frag.text):
            name = m.group(1).lower()[:5]
            if name in names:
                continue
            names.add(name)
            tail = frag.text[m.end() : m.end() + 60]
            out.append(Language(name=m.group(1), level_raw=tail.strip(" —:-,") or None,
                                fragment_ids=[frag.id]))  # fmt: skip
    return out


def extract_profile_fallback(resume: Document) -> CandidateProfile:
    positions = _positions(resume)
    certificates = [
        Fact(text=f.text[:200], category="certificate", fragment_ids=[f.id])
        for f in resume.fragments
        if _CERT.search(f.text) and f.section_role in ("education", "skills", "other", "about")
    ]
    return CandidateProfile(
        positions=positions,
        education=_education(resume),
        skills=_skills(resume, positions),
        languages=_languages(resume),
        certificates=certificates,
    )
