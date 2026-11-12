"""Правила поверх LLM (T07, шаг 4): числовые пороги проверяет код (D13).

- Стаж: объединение периодов мест работы, на которые ссылается доказательство (тема порога).
  Без темы — общий стаж. Факт ≥ порога → «Соответствует», меньше → «Частично» с долей.
- Образование: порядковая шкала. Уровня не хватает → «Не соответствует», раздела нет → «Не указано».
- Язык: CEFR. Ниже на ступень → «Частично», ниже сильнее → «Не соответствует», уровень не
  написан → «Частично» (вопрос кандидату), язык не упомянут → «Не указано».

Статусы «Соответствует», «Частично», «Не соответствует» правило ставит только вместе с фрагментом
резюме (принцип 2). Цитаты после правил подставляет attach_quotes.
"""

from __future__ import annotations

import re

from aihr.contracts import (
    CandidateProfile,
    Evidence,
    EvidenceType,
    Position,
    Requirement,
    Status,
    ThresholdKind,
    Verdict,
)
from aihr.normalize.levels import (
    CEFR,
    EDUCATION_RANK,
    cefr_from_text,
    meets_education,
    required_education,
)
from aihr.normalize.tenure import format_months, tenure_for

_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")

_LANGUAGES = {
    "англ": "en", "english": "en", "нем": "de", "german": "de", "deutsch": "de",
    "франц": "fr", "french": "fr", "испан": "es", "spanish": "es", "итал": "it",
    "italian": "it", "китай": "zh", "chinese": "zh", "япон": "ja", "japanese": "ja",
    "русск": "ru", "russian": "ru", "араб": "ar", "arabic": "ar", "турец": "tr",
    "turkish": "tr", "корей": "ko", "korean": "ko", "португ": "pt", "portuguese": "pt",
}  # fmt: skip


def _language_code(name: str) -> str:
    low = name.lower()
    for prefix, code in _LANGUAGES.items():
        if low.startswith(prefix) or prefix in low.split():
            return code
    return low[:4]


def _evidence(fragment_ids: list[str]) -> list[Evidence]:
    seen: list[str] = []
    for fid in fragment_ids:
        if fid not in seen:
            seen.append(fid)
    return [Evidence(fragment_id=fid, quote="") for fid in seen]  # цитату подставит код


def _changed(verdict: Verdict, **update: object) -> Verdict:
    new = verdict.model_copy(update=update)
    if new.status != verdict.status:
        new = new.model_copy(update={"decided_by": "rule"})
    return new


def _period(p: Position) -> str:
    def fmt(ym: object) -> str:
        y, m = ym.year, ym.month  # type: ignore[attr-defined]
        return f"{m:02d}.{y}" if m else str(y)

    if p.start is None or p.end is None:
        return p.raw_dates or "?"
    end = "н.в." if p.is_current else fmt(p.end)
    return f"{fmt(p.start)}–{end}"


# ---------- стаж ----------


def _years_rule(req: Requirement, verdict: Verdict, profile: CandidateProfile) -> Verdict:
    assert req.threshold is not None
    m = _NUMBER.search(req.threshold.value)
    if not m:
        return verdict
    required_years = float(m.group(0).replace(",", "."))
    if required_years <= 0:
        return verdict

    evidence_ids = {e.fragment_id for e in verdict.evidence}
    if req.threshold.subject:
        positions = [p for p in profile.positions if evidence_ids & set(p.fragment_ids)]
        scope = "по теме"
    else:
        positions = list(profile.positions)  # «опыт работы от N лет» без темы — общий стаж
        scope = "общий стаж"
    months, approximate = tenure_for(positions)
    if months is None:
        return verdict  # мест работы по теме нет или нет дат — решение модели не трогаем

    dated = [p for p in positions if p.start is not None]
    periods = ", ".join(_period(p) for p in dated)
    fact = format_months(months, approximate)
    need = f"{required_years:g} {_years_word(required_years)}"
    fact_years = months / 12
    if fact_years + 1e-9 >= required_years:
        status, partial_value, sign = Status.match, None, "≥"
    else:
        status, partial_value, sign = Status.partial, round(fact_years / required_years, 2), "<"
    computed = f"{scope}: {periods} = {fact} {sign} {need}"
    weak = verdict.evidence_type in (EvidenceType.adjacent, EvidenceType.indirect)
    if status == Status.match and req.threshold.subject and weak:
        # Стаж набран, но опыт по теме смежный или косвенный — не выше «Частично» (D15, D43)
        status = Status.partial
        computed += "; опыт по теме смежный — не выше «Частично»"
    ids = [fid for p in dated for fid in p.fragment_ids]
    return _changed(
        verdict,
        status=status,
        partial_value=partial_value,
        computed=computed,
        evidence=verdict.evidence or _evidence(ids),
        evidence_type=verdict.evidence_type or EvidenceType.direct,
        missing=(f"не хватает {format_months(round(required_years * 12) - months)}"
                 if status == Status.partial and not weak else verdict.missing),
    )  # fmt: skip


def _years_word(n: float) -> str:
    """Родительный падеж после «от» и «≥»: 1 года, 1,5 года, 3 лет, 21 года."""
    if n != int(n):
        return "года"
    k = int(n) % 100
    return "года" if k % 10 == 1 and k != 11 else "лет"


# ---------- образование ----------

# Требование называет специальность, а не только уровень: «высшее техническое», «профильное»,
# «по специальности …», «в области …»
_FIELD = re.compile(
    r"(?i)\b(?:высшее|среднее(?:\s+(?:специальное|профессиональное))?)\s+(?!образован|специальн|профессиональн)"
    r"[а-яё]+ое\b|профильн|по\s+специальност|в\s+области|по\s+направлени"
)


def _education_rule(req: Requirement, verdict: Verdict, profile: CandidateProfile) -> Verdict:
    assert req.threshold is not None
    required = required_education(req.threshold.value)
    if required is None or required not in EDUCATION_RANK:
        return verdict
    if not profile.education and not verdict.evidence:
        return _changed(
            verdict,
            status=Status.not_stated,
            evidence=[],
            evidence_type=None,
            partial_value=None,
            computed="раздел об образовании в резюме не найден",
            comment="В резюме нет сведений об образовании.",
        )
    levels = [e.level for e in profile.education]
    ok = meets_education(levels, required) if levels else None
    if ok is None:
        return verdict  # уровень не распознан — оставляем решение модели
    best = max((lv for lv in levels if lv in EDUCATION_RANK), key=lambda lv: EDUCATION_RANK[lv])
    ids = [fid for e in profile.education if e.level == best for fid in e.fragment_ids]
    computed = f"уровень в резюме: {best.value}; требуется не ниже {required.value}"
    status = Status.match if ok else Status.mismatch
    field_doubt = verdict.status in (Status.partial, Status.mismatch) and bool(verdict.evidence)
    if ok and _FIELD.search(f"{req.threshold.value} {req.text}") and field_doubt:
        # Уровень подходит, а специальность модель сочла другой: код уровень проверил,
        # специальность — нет. Не выше «Частично» (D43)
        status = Status.partial
        computed += "; специальность не совпала по оценке модели"
    return _changed(
        verdict,
        status=status,
        evidence=verdict.evidence or _evidence(ids),
        evidence_type=verdict.evidence_type or EvidenceType.direct,
        partial_value=None,
        computed=computed,
    )


# ---------- язык ----------


def _language_rule(req: Requirement, verdict: Verdict, profile: CandidateProfile) -> Verdict:
    assert req.threshold is not None
    required = cefr_from_text(req.threshold.value)
    if required is None:
        return verdict
    subject = req.threshold.subject or req.text
    code = _language_code(subject)
    langs = [lang for lang in profile.languages if _language_code(lang.name) == code]
    if not langs:
        return verdict  # язык не упомянут в профиле: остаётся решение модели («не указано»)
    lang = langs[0]
    ids = lang.fragment_ids
    if lang.cefr is None:
        return _changed(
            verdict,
            status=Status.partial,
            evidence=_evidence(ids),
            evidence_type=EvidenceType.direct,
            partial_value=None,
            computed=f"{lang.name}: уровень не указан, требуется {required}",
            missing="уровень языка",
        )
    have, need = CEFR.index(lang.cefr), CEFR.index(required)
    if have >= need:
        status, partial_value = Status.match, None
    elif need - have == 1:
        status, partial_value = Status.partial, round((have + 1) / (need + 1), 2)
    else:
        status, partial_value = Status.mismatch, None
    sign = "≥" if have >= need else "<"
    return _changed(
        verdict,
        status=status,
        evidence=_evidence(ids),
        evidence_type=EvidenceType.direct,
        partial_value=partial_value,
        computed=f"{lang.name}: {lang.cefr} {sign} {required}",
    )


def apply_rules(req: Requirement, verdict: Verdict, profile: CandidateProfile) -> Verdict:
    if req.threshold is None:
        return verdict
    kind = req.threshold.kind
    if kind == ThresholdKind.years:
        return _years_rule(req, verdict, profile)
    if kind == ThresholdKind.education_level:
        return _education_rule(req, verdict, profile)
    if kind == ThresholdKind.language_level:
        return _language_rule(req, verdict, profile)
    return verdict
