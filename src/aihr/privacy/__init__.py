"""Маскирование ПДн (T02). Во внешний API уходит только masked_text.

Резюме: ФИО кандидата → [CANDIDATE] во всех падежах, другие люди → [PERSON_n], контакты,
ссылки, документы, дата рождения, возраст, адрес, город в контактах; фразы о поле, семье и
гражданстве удаляются. Вакансии: контакты, ссылки и имена людей. Работодатели и вузы не
маскируются (D16). Таблица замен живёт только в памяти одного прогона.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from aihr.contracts import DocKind, Document, Fragment, FragmentSource
from aihr.privacy import names, patterns
from aihr.privacy.guard import check_outbound

__all__ = ["PrivacyContext", "check_outbound", "mask_document", "mask_text", "unmask"]

# Токены без номера: обычно одно значение на резюме
_SINGLE = {"CANDIDATE", "BIRTHDATE", "AGE", "ADDRESS", "CITY", "ID_DOC"}
# Эти исходные значения guard не ищет дословно: «Москва» законно встречается в вакансии
_NOT_GUARDED = {"BIRTHDATE", "AGE", "CITY"}
_HEADER_ZONE_ORDER = 5
_CITY_PREFIX = re.compile(
    r"(?i)\b(г\.|город|проживает|проживаю|место\s+жительства|location)\s*:?\s*"
)


@dataclass
class PrivacyContext:
    """Таблица замен «токен → исходное значение» на один прогон. Не пишется никуда."""

    replacements: dict[str, str] = field(default_factory=dict)
    name_patterns: list[re.Pattern[str]] = field(default_factory=list)
    _by_value: dict[tuple[str, str], str] = field(default_factory=dict)
    _counters: Counter[str] = field(default_factory=Counter)

    def token(self, kind: str, value: str) -> str:
        key = (kind, " ".join(value.lower().split()))
        if key in self._by_value:
            return self._by_value[key]
        if kind in _SINGLE:
            tok = f"[{kind}]"
        else:
            self._counters[kind] += 1
            tok = f"[{kind}_{self._counters[kind]}]"
        self._by_value[key] = tok
        self.replacements.setdefault(tok, value)
        return tok

    def guarded_values(self) -> list[str]:
        return [
            original
            for (kind, _), tok in self._by_value.items()
            if kind not in _NOT_GUARDED
            and (original := self.replacements.get(tok))
            and len(original) >= 4
        ]

    def add_names(self, words: list[str]) -> None:
        known = {p.pattern for p in self.name_patterns}
        for w in words:
            if len(w) >= 3:
                p = names.name_pattern(w)
                if p.pattern not in known:
                    self.name_patterns.append(p)
                    known.add(p.pattern)

    def __repr__(self) -> str:  # исходные значения не печатаем даже в отладке
        return f"PrivacyContext(tokens={len(self.replacements)})"


def _sub(pattern: re.Pattern[str], text: str, repl: object) -> str:
    return pattern.sub(repl, text)  # type: ignore[arg-type]


def _tidy(text: str) -> str:
    text = re.sub(r"\s+([,.;:])", r"\1", text)
    text = re.sub(r"([,;])\s*(?=[,;])", "", text)
    text = re.sub(r"^[\s,;:—-]+|[\s,;—-]+$", "", text)
    return re.sub(r"\s{2,}", " ", text)


def mask_text(text: str, ctx: PrivacyContext, *, personal_zone: bool = False) -> str:
    """personal_zone — контакты и «о себе»: там же удаляем фразы о поле и семье, маскируем город."""
    t = text
    t = _sub(patterns.EMAIL, t, lambda m: ctx.token("EMAIL", m.group(0)))
    t = _sub(patterns.URL, t, lambda m: ctx.token("URL", m.group(0)))
    t = _sub(patterns.HANDLE, t, lambda m: ctx.token("URL", m.group(0)))
    t = _sub(patterns.PHONE, t, lambda m: ctx.token("PHONE", m.group(0)))
    for p in (patterns.SNILS, patterns.INN, patterns.PASSPORT):
        t = _sub(p, t, lambda m: ctx.token("ID_DOC", m.group(0)))
    t = _sub(patterns.BIRTHDATE, t, lambda m: f"{m.group(1)} {ctx.token('BIRTHDATE', m.group(2))}")
    t = _sub(patterns.AGE_WITH_GENDER, t, lambda m: ctx.token("AGE", m.group(0)))
    t = _sub(patterns.AGE, t, lambda m: f"{m.group(1)}{ctx.token('AGE', m.group(2))}")
    t = _sub(patterns.ADDRESS, t, lambda m: ctx.token("ADDRESS", m.group(0)))

    for p in ctx.name_patterns:  # ФИО кандидата во всех падежах, в любом месте документа
        t = _sub(p, t, lambda m: ctx.token("CANDIDATE", m.group(0)))

    # Другие люди: только «Имя Фамилия» из двух и более слов — одиночные PER у Natasha
    # часто оказываются названиями компаний, а работодателей не маскируем (D16)
    for start, stop, span in reversed(names.person_spans(t)):
        if "[" in span:
            continue
        if len(span.split()) >= 2 or (personal_zone and names.is_name_word(span.strip("."))):
            t = t[:start] + ctx.token("PERSON", span) + t[stop:]

    t = _sub(patterns.PERSONAL_FIELDS, t, "")
    if personal_zone:
        t = _sub(patterns.PERSONAL_PHRASES, t, "")
        m = _CITY_PREFIX.search(t)
        for start, stop, span in reversed(names.location_spans(t)):
            near_prefix = m is not None and 0 <= start - m.end() <= 2
            if near_prefix or len(t) <= 40:
                t = t[:start] + ctx.token("CITY", span) + t[stop:]
    return _tidy(t) if t != text else t


def _candidate_names(doc: Document) -> list[str]:
    found = names.names_from_filename(doc.filename)
    head = [
        f
        for f in doc.fragments
        if f.order <= _HEADER_ZONE_ORDER or f.source == FragmentSource.header
    ]
    if head:
        found += names.names_from_line(head[0].text)
    for frag in head + [f for f in doc.fragments if f.section_role == "contacts"][:10]:
        for _, _, span in names.person_spans(frag.text):
            found += [w.strip(".,") for w in span.split() if names.is_name_word(w.strip(".,"))]
    uniq: list[str] = []
    for w in found:
        if w not in uniq:
            uniq.append(w)
    return uniq


def _is_personal_zone(frag: Fragment) -> bool:
    return (
        frag.section_role == "contacts"
        or frag.order <= _HEADER_ZONE_ORDER
        or frag.source in (FragmentSource.header, FragmentSource.footer)
    )


def mask_document(doc: Document, ctx: PrivacyContext) -> Document:
    if doc.kind == DocKind.resume:
        ctx.add_names(_candidate_names(doc))
        fragments = [
            f.model_copy(
                update={
                    "masked_text": mask_text(f.text, ctx, personal_zone=_is_personal_zone(f))
                    or "[УДАЛЕНО]"
                }
            )
            for f in doc.fragments
        ]
    else:
        fragments = [
            f.model_copy(update={"masked_text": _vacancy_mask(f.text, ctx) or "[УДАЛЕНО]"})
            for f in doc.fragments
        ]
    return doc.model_copy(update={"fragments": fragments})


def _vacancy_mask(text: str, ctx: PrivacyContext) -> str:
    t = text
    t = _sub(patterns.EMAIL, t, lambda m: ctx.token("EMAIL", m.group(0)))
    t = _sub(patterns.URL, t, lambda m: ctx.token("URL", m.group(0)))
    t = _sub(patterns.HANDLE, t, lambda m: ctx.token("URL", m.group(0)))
    t = _sub(patterns.PHONE, t, lambda m: ctx.token("PHONE", m.group(0)))
    for start, stop, span in reversed(names.person_spans(t)):
        if "[" not in span and len(span.split()) >= 2:
            t = t[:start] + ctx.token("PERSON", span) + t[stop:]
    return t


def unmask(text: str, ctx: PrivacyContext) -> str:
    for token in sorted(ctx.replacements, key=len, reverse=True):
        text = text.replace(token, ctx.replacements[token])
    return text
