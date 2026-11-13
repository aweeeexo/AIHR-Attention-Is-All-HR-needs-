"""Требования вакансии без LLM (T11, шаг 1): пункты разделов, модальность, тип, пороги."""

from __future__ import annotations

import re

from aihr.contracts import (
    Document,
    Fragment,
    Modality,
    ReqKind,
    Requirement,
    Threshold,
    ThresholdKind,
)
from aihr.normalize import canonicalize, find_terms
from aihr.normalize.levels import cefr_from_text, education_from_text

_REQ_ROLES = {
    "requirements": Modality.must,
    "skills": Modality.must,
    "nice_to_have": Modality.nice,
    "duties": Modality.nice,  # обязанность — пожелание, не обязательное требование (D3)
}
_NICE_MARKER = re.compile(
    r"(?i)будет\s+(?:большим\s+)?плюсом|будет\s+преимуществом|желательн\w*|приветству\w+"
    r"|плюсом\s+будет|nice\s+to\s+have|is\s+a\s+plus|preferred"
)
_MUST_MARKER = re.compile(r"(?i)обязательн\w*|необходим\w*|требуется|must\b|required")
# Вакансия сплошным текстом: фразы, похожие на требование
_REQ_HINT = re.compile(
    r"(?i)\bопыт|\bзнани|\bумени|\bнавык|\bвладени|образовани|\bстаж|права\s+категории"
    r"|сертификат|удостоверени|готовность|\bот\s+\d+\s+(?:лет|года)|experience|knowledge"
)

_YEARS = re.compile(
    r"(?i)(?:от|не\s+менее|более|минимум|свыше|from|at\s+least|min\.?)\s*(\d+(?:[.,]\d+)?)\s*\+?\s*"
    r"(?:-?х\s*)?(?:лет|года|год|years?|yrs?)"
    r"|(\d+(?:[.,]\d+)?)\s*\+\s*(?:лет|года|год|years?)"
    r"|(\d+(?:[.,]\d+)?)\+?\s+years?\s+of"
)
_EDUCATION_WORDS = re.compile(
    r"(?i)образовани|диплом|бакалавр|магистр|degree|bachelor|master|высшее|среднее\s+специальн"
)
_LANG_NAME = re.compile(
    r"(?i)английск|немецк|французск|испанск|итальянск|китайск|японск|корейск|арабск|турецк"
    r"|english|german|french|spanish|chinese"
)
_CERT = re.compile(
    r"(?i)сертификат|удостоверени|аккредитац|допуск\w*\s|лицензи|свидетельств|права\s+категории"
    r"|certificat|license|licence"
)
# Личные качества по резюме не проверяются (verifiable = False). Общий словарь, не под вакансию
_SOFT = re.compile(
    r"(?i)коммуникабель|ответственн|внимательн|внимание\s+к\s+детал|стрессоустойчив|самоорганиз"
    r"|системн\w+\s+мышлен|системност|аккуратн|пунктуальн|исполнительн|обучаем|инициативн"
    r"|клиентоориентир|командн\w+\s+игрок|умение\s+работать\s+в\s+команде|гибкост|честност"
    r"|доброжелательн|энергичн|целеустремл|многозадачн|концентрац|soft\s+skills|team\s+player"
    r"|communication\s+skills|responsib|attention\s+to\s+detail"
)
_LIST_SPLIT = re.compile(r"\s*(?:,|;|/|\s\bи\b\s|\s\band\b\s)\s*")


def _kind(text: str, role: str | None) -> ReqKind:
    if role == "duties":
        return ReqKind.duty
    if _LANG_NAME.search(text):
        return ReqKind.language
    if _EDUCATION_WORDS.search(text):
        return ReqKind.education
    if _CERT.search(text):
        return ReqKind.certificate
    if _SOFT.search(text):
        return ReqKind.soft
    if _YEARS.search(text) or re.search(r"(?i)\bопыт|experience", text):
        return ReqKind.experience
    return ReqKind.skill


def _subject(text: str, span: tuple[int, int]) -> str | None:
    """Тема порога стажа: текст без числа и общих слов. Пусто → общий стаж («опыт от 1 года»)."""
    rest = (text[: span[0]] + " " + text[span[1] :]).lower()
    rest = re.sub(r"(?i)\bопыт\w*|\bработ\w*|\bкоммерческ\w*|\bпрофессиональн\w*|\bстаж\w*"
                  r"|\bexperience|\bwork\w*|[^\w\s]", " ", rest)  # fmt: skip
    words = [w for w in rest.split() if len(w) > 2 and w not in {"в", "на", "по", "не", "of", "in"}]
    return " ".join(words) if words else None


def _threshold(text: str, kind: ReqKind) -> Threshold | None:
    m = _YEARS.search(text)
    if m and kind in (ReqKind.experience, ReqKind.skill):
        value = next(g for g in m.groups() if g)
        return Threshold(
            kind=ThresholdKind.years,
            value=value.replace(",", "."),
            subject=_subject(text, m.span()),
        )
    if kind == ReqKind.education:
        level = education_from_text(text)
        if level is not None and level.value != "course":
            value = "higher" if re.search(r"(?i)высше|higher", text) else level.value
            return Threshold(kind=ThresholdKind.education_level, value=value)
    if kind == ReqKind.language:
        cefr = cefr_from_text(text)
        name = _LANG_NAME.search(text)
        if cefr and name:
            return Threshold(kind=ThresholdKind.language_level, value=cefr, subject=name.group(0))
    return None


def _is_heading(frag: Fragment) -> bool:
    return bool(frag.section) and frag.text.rstrip(":").strip() == (frag.section or "").strip()


_SENTENCE = re.compile(r"(?<=[.!?;])\s+")


def _candidates(vacancy: Document) -> list[tuple[Fragment, str | None, str]]:
    out = [
        (f, f.section_role, f.text)
        for f in vacancy.fragments
        if f.section_role in _REQ_ROLES and not _is_heading(f)
    ]
    if out:
        return out
    # Разделов нет: каждое предложение, похожее на требование, кроме условий и контактов
    body = [f for f in vacancy.fragments if f.section_role not in ("conditions", "contacts")]
    return [
        (f, "requirements", sentence)
        for f in body
        for sentence in _SENTENCE.split(f.text)
        if _REQ_HINT.search(sentence)
    ]


def _split_atomic(text: str) -> list[str]:
    """Перечисление делим, только если каждый элемент — известный термин словаря синонимов."""
    head, sep, tail = text.partition(":")
    items = [i.strip(" .") for i in _LIST_SPLIT.split(tail if sep else text) if i.strip(" .")]
    if len(items) >= 2 and all(canonicalize(i) for i in items):
        prefix = f"{head.strip()}: " if sep else ""
        return [f"{prefix}{i}" for i in items]
    return [text]


def extract_requirements_fallback(vacancy: Document) -> list[Requirement]:
    reqs: list[Requirement] = []
    for frag, role, fragment_text in _candidates(vacancy):
        for text in _split_atomic(fragment_text):
            nice = _NICE_MARKER.search(text)
            must = _MUST_MARKER.search(text)
            modality = _REQ_ROLES.get(role or "", Modality.must)
            marker = None
            if nice:
                modality, marker = Modality.nice, nice.group(0)
            elif must and role != "duties":
                modality, marker = Modality.must, must.group(0)
            kind = _kind(text, role)
            section = frag.section or "без заголовка"
            reqs.append(
                Requirement(
                    id=f"{vacancy.id}.req{len(reqs) + 1}",
                    vacancy_id=vacancy.id,
                    text=text,
                    kind=kind,
                    modality=modality,
                    modality_marker=marker,
                    modality_reason=(f"маркер «{marker}»" if marker else f"раздел «{section}»")
                    + (" (обязанность — пожелание, D3)" if kind == ReqKind.duty else ""),
                    threshold=_threshold(text, kind),
                    canonical_terms=find_terms(text),
                    verifiable=kind != ReqKind.soft,
                    source_fragment_ids=[frag.id],
                )
            )
    return reqs
