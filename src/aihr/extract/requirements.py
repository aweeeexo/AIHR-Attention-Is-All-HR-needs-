"""Требования вакансии (T04): LLM извлекает, код проверяет и нормализует.

Порядок решения модальности (первое сработавшее правило побеждает):
1. маркер во фрагменте вакансии («будет плюсом» → nice, «обязательно» → must) — ищет код;
2. роль раздела (requirements → must, nice_to_have → nice, duties → nice, D3);
3. мнение модели — только если нет ни маркера, ни раздела.

Покрытие: каждый фрагмент разделов требований, пожеланий, обязанностей и навыков должен стать
источником хотя бы одного требования. Непокрытые — повторный вызов только на них, затем
предупреждение в Document.warnings.
"""

from __future__ import annotations

import logging
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
from aihr.extract.schemas import ExtractedRequirement, ExtractedRequirements
from aihr.llm import LLMClient
from aihr.normalize import canonicalize
from aihr.normalize.levels import cefr_from_text, education_from_text

log = logging.getLogger(__name__)

PROMPT_ID = "extract/requirements"

ROLE_RU = {
    "requirements": "Требования",
    "nice_to_have": "Будет плюсом",
    "duties": "Обязанности",
    "skills": "Навыки",
    "conditions": "Условия",
    "about": "О компании",
    "contacts": "Контакты",
    "other": "Прочее",
}
COVERED_ROLES = {"requirements", "nice_to_have", "duties", "skills"}
_ROLE_MODALITY = {
    "requirements": Modality.must,
    "skills": Modality.must,
    "nice_to_have": Modality.nice,
    "duties": Modality.nice,  # D3
}

_NICE = re.compile(
    r"(?i)будет\s+(?:большим\s+)?плюсом|будет\s+преимуществом|преимуществом\s+будет"
    r"|плюсом\s+будет|желательн\w*|приветству\w+|как\s+плюс|nice\s+to\s+have|is\s+a\s+plus"
    r"|preferred|would\s+be\s+a\s+plus"
)
_MUST_STRONG = re.compile(
    r"(?i)обязательн\w*|необходим\w*|требуется|обязательное\s+условие|\bmust\b|\brequired\b"
)
_MUST_THRESHOLD = re.compile(r"(?i)не\s+менее|\bот\s+\d+(?:[.,]\d+)?\s*(?:лет|года|год)")

_EDU_VALUES = {"secondary", "vocational", "higher", "master", "phd"}
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


# ---------- вход для модели ----------


def _is_heading(frag: Fragment) -> bool:
    return bool(frag.section) and frag.text.rstrip(":").strip() == (frag.section or "").strip()


def _for_prompt(fragments: list[Fragment]) -> list[Fragment]:
    """Копии фрагментов с пометкой раздела в masked_text: [V1.3] {Обязанности} текст."""
    out = []
    for f in fragments:
        role = ROLE_RU.get(f.section_role or "", "без раздела")
        out.append(f.model_copy(update={"masked_text": f"{{{role}}} {f.masked_text}"}))
    return out


# ---------- модальность ----------


_CLAUSE = re.compile(r"\s*(?:[.;,]|\s—\s|\s-\s|\bи\b)\s*")


def marker_scope(requirement: str, fragment: str) -> str:
    """Где искать маркер модальности: строчный заголовок «Будет плюсом:» и та часть фразы,
    к которой относится требование. Во фразе «нужны права C, знание города желательно»
    «желательно» относится только ко второму требованию."""
    from aihr.retrieve import tokens

    prefix = ""
    head, sep, rest = fragment.partition(":")
    if sep and len(head) <= 40:
        prefix, fragment = head, rest
    clauses = [c for c in _CLAUSE.split(fragment) if c.strip()]
    if len(clauses) <= 1:
        return f"{prefix} {fragment}"
    want = set(tokens(requirement))
    scored = [(len(want & set(tokens(c))), i) for i, c in enumerate(clauses)]
    best, _ = max(scored)
    if best == 0:
        return f"{prefix} {fragment}"
    picked = [clauses[i] for score, i in scored if score == best]
    return " ".join([prefix, *picked])


def decide_modality(
    item: ExtractedRequirement, sources: list[Fragment]
) -> tuple[Modality, str | None, str]:
    """(модальность, найденный маркер, обоснование) по правилам шага 2."""
    roles = {f.section_role for f in sources}
    text = " ".join(marker_scope(item.text, f.text) for f in sources)
    duty_only = roles == {"duties"}
    if m := _NICE.search(text):
        return Modality.nice, m.group(0), f"маркер «{m.group(0)}»"
    if not duty_only and (m := _MUST_STRONG.search(text)):
        return Modality.must, m.group(0), f"маркер «{m.group(0)}»"
    if not duty_only and "nice_to_have" not in roles and (m := _MUST_THRESHOLD.search(text)):
        return Modality.must, m.group(0), f"маркер «{m.group(0)}»"
    for role in ("nice_to_have", "duties", "requirements", "skills"):
        if role in roles:
            modality = _ROLE_MODALITY[role]
            name = ROLE_RU[role]
            if role == "duties":
                return modality, None, f"раздел «{name}» → пожелание (D3)"
            suffix = " без маркера → must" if modality == Modality.must else " → nice"
            return modality, None, f"раздел «{name}»{suffix}"
    return item.modality, None, f"оценка модели: {item.modality_reason}"[:200]


# ---------- пороги ----------


def normalize_threshold(item: ExtractedRequirement) -> Threshold | None:
    t = item.threshold
    if t is None:
        return None
    raw = str(t.value).strip()
    if t.kind == ThresholdKind.years:
        m = _NUMBER.search(raw)
        if not m:
            return None
        value = m.group(0).replace(",", ".")
        value = value[:-2] if value.endswith(".0") else value
        return Threshold(kind=t.kind, value=value, subject=t.subject or None)
    if t.kind == ThresholdKind.education_level:
        low = raw.lower()
        if low not in _EDU_VALUES:
            level = education_from_text(raw)
            if level is None or level.value == "course":
                return None
            low = "higher" if level.value in ("bachelor", "specialist") else level.value
            low = "vocational" if low == "incomplete_higher" else low
        return Threshold(kind=t.kind, value=low, subject=t.subject or None)
    if t.kind == ThresholdKind.language_level:
        cefr = cefr_from_text(raw) or cefr_from_text(item.text)
        if cefr is None:
            return None
        return Threshold(kind=t.kind, value=cefr, subject=t.subject or None)
    return None


# ---------- сборка ----------


def _norm_key(text: str) -> str:
    return re.sub(r"[^\w]+", " ", text.lower().replace("ё", "е")).strip()


def _build(
    vacancy: Document, items: list[ExtractedRequirement]
) -> list[tuple[ExtractedRequirement, Requirement]]:
    by_id = {f.id: f for f in vacancy.fragments}
    out: list[tuple[ExtractedRequirement, Requirement]] = []
    for item in items:
        known = [fid for fid in dict.fromkeys(item.source_fragment_ids) if fid in by_id]
        if not known:
            log.warning("%s: требование без существующих фрагментов отброшено", vacancy.id)
            continue
        sources = [by_id[fid] for fid in known]
        if all(f.section_role in ("conditions", "contacts") for f in sources):
            log.info("%s: требование из раздела условий отброшено", vacancy.id)
            continue
        modality, marker, reason = decide_modality(item, sources)
        if modality != item.modality:
            log.info(
                "%s: модальность модели %s заменена правилом (%s)",
                vacancy.id,
                item.modality.value,
                reason,
            )
        kind = ReqKind.duty if {f.section_role for f in sources} == {"duties"} else item.kind
        if kind == ReqKind.duty:
            modality = Modality.nice  # обязанность никогда не обязательна (D3)
        verifiable = item.verifiable and kind != ReqKind.soft
        canonical = [
            c for c in [canonicalize(item.text), *map(canonicalize, item.alternatives)] if c
        ]
        out.append(
            (
                item,
                Requirement(
                    id="",
                    vacancy_id=vacancy.id,
                    text=item.text.strip(),
                    kind=kind,
                    modality=modality,
                    modality_marker=marker,
                    modality_reason=reason,
                    alternatives=[a.strip() for a in item.alternatives if a.strip()],
                    threshold=normalize_threshold(item),
                    canonical_terms=list(dict.fromkeys(canonical)),
                    verifiable=verifiable,
                    source_fragment_ids=known,
                ),
            )
        )
    return out


_ALTERNATIVE_WORDS = re.compile(
    r"(?i)\bили\b|\bлибо\b|/|\bодн\w*\s+из\b|\bлюб\w+\s+из\b|\bor\b|\bany\s+of\b|\beither\b"
)


def split_conjunctions(reqs: list[Requirement]) -> list[Requirement]:
    """«Опыт с A, B и C» модель иногда кладёт в alternatives. Без «или», «/», «одно из» это
    перечисление: нужны все — делим на атомарные требования (шаг 1 T04)."""
    out: list[Requirement] = []
    for req in reqs:
        if len(req.alternatives) < 2 or _ALTERNATIVE_WORDS.search(req.text):
            out.append(req)
            continue
        for alt in req.alternatives:
            text = _replace_list(req.text, req.alternatives, alt)
            out.append(
                req.model_copy(
                    update={
                        "text": text,
                        "alternatives": [],
                        "canonical_terms": [c for c in [canonicalize(alt)] if c],
                    }
                )
            )
    return out


def _replace_list(text: str, items: list[str], keep: str) -> str:
    """«Опыт работы с AutoCAD, Revit, ArchiCAD» → «Опыт работы с Revit»."""
    positions = [text.find(i) for i in items]
    if all(p >= 0 for p in positions):
        start = min(positions)
        last = items[positions.index(max(positions))]
        end = max(positions) + len(last)
        return f"{text[:start]}{keep}{text[end:]}".strip()
    return f"{text} — {keep}"


def merge_duplicates(reqs: list[Requirement]) -> list[Requirement]:
    """Одинаковый текст (или канонические термины) и тип → одно требование.

    Модальность остаётся более строгая, фрагменты объединяются. Обязанность, совпавшая
    с требованием, склеивается с требованием.
    """
    merged: list[Requirement] = []
    index: dict[tuple[str, str], int] = {}
    for req in reqs:
        family = (
            "exp"
            if req.kind in (ReqKind.duty, ReqKind.experience, ReqKind.skill)
            else req.kind.value
        )
        keys = [(family, _norm_key(req.text))]
        if req.canonical_terms:
            keys.append((family, "|".join(sorted(req.canonical_terms))))
        hit = next((index[k] for k in keys if k in index), None)
        if hit is None:
            for k in keys:
                index[k] = len(merged)
            merged.append(req)
            continue
        base = merged[hit]
        stricter = base if base.modality == Modality.must else req
        merged[hit] = stricter.model_copy(
            update={
                "source_fragment_ids": list(
                    dict.fromkeys(base.source_fragment_ids + req.source_fragment_ids)
                ),
                "kind": base.kind if base.kind != ReqKind.duty else req.kind,
            }
        )
    return merged


def uncovered(vacancy: Document, reqs: list[Requirement]) -> list[Fragment]:
    used = {fid for r in reqs for fid in r.source_fragment_ids}
    return [
        f
        for f in vacancy.fragments
        if f.section_role in COVERED_ROLES and not _is_heading(f) and f.id not in used
    ]


def _call(
    llm: LLMClient, fragments: list[Fragment], only_uncovered: bool
) -> list[ExtractedRequirement]:
    result = llm.structured(
        PROMPT_ID,
        {"fragments": _for_prompt(fragments), "only_uncovered": only_uncovered},
        ExtractedRequirements,
    )
    return result.items


def extract_requirements(vacancy: Document, llm: LLMClient) -> list[Requirement]:
    items = _call(llm, vacancy.fragments, only_uncovered=False)
    reqs = [r for _, r in _build(vacancy, items)]

    missing = uncovered(vacancy, reqs)
    if missing:
        log.info("%s: непокрытых фрагментов %d, повторный вызов", vacancy.id, len(missing))
        allowed = {f.id for f in missing}
        extra = [
            r
            for item, r in _build(vacancy, _call(llm, missing, only_uncovered=True))
            if set(item.source_fragment_ids) & allowed
        ]
        reqs += extra
        still = uncovered(vacancy, reqs)
        if still:
            ids = ", ".join(f.id for f in still)
            vacancy.warnings.append(
                f"Из фрагментов {ids} не извлечено ни одного требования — проверьте их вручную."
            )

    reqs = merge_duplicates(split_conjunctions(reqs))
    return [r.model_copy(update={"id": f"{vacancy.id}.req{i}"}) for i, r in enumerate(reqs, 1)]
