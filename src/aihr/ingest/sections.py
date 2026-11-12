"""Разделы документа и их роли. Словарь — про структуру документа, а не про предметную область:
одинаково работает для резюме повара, юриста или пилота.
"""

from __future__ import annotations

import re
from collections import Counter

from aihr.contracts import DocKind, Fragment, FragmentSource
from aihr.ingest.readers import Block
from aihr.ingest.text import normalize, split_long, strip_bullet

MAX_FRAGMENTS = 2000

_RESUME_HEADINGS: dict[str, list[str]] = {
    "experience": [
        "опыт работы",
        "опыт",
        "трудовая деятельность",
        "трудовой стаж",
        "места работы",
        "место работы",
        "профессиональный опыт",
        "опыт работы и проекты",
        "карьера",
        "проекты",
        "проектный опыт",
        "ключевые проекты",
        "обязанности",
        "достижения",
        "задачи",
        "функции",
        "основные обязанности",
        "work experience",
        "experience",
        "employment history",
        "employment",
        "projects",
        "professional experience",
        "собственные проекты",
        "личные проекты",
        "pet-проекты",
        "pet projects",
        "фриланс",
        "волонтерство",
        "стажировки",
        "практика",
    ],
    "education": [
        "образование",
        "основное образование",
        "высшее образование",
        "учеба",
        "обучение",
        "курсы",
        "повышение квалификации",
        "дополнительное образование",
        "тренинги",
        "сертификаты",
        "сертификация",
        "сертификаты и курсы",
        "курсы и сертификаты",
        "образование и курсы",
        "education",
        "courses",
        "certifications",
        "certificates",
        "training",
    ],
    "skills": [
        "навыки",
        "ключевые навыки",
        "профессиональные навыки",
        "технические навыки",
        "компетенции",
        "ключевые компетенции",
        "профессиональные компетенции",
        "стек",
        "технологии",
        "стек технологий",
        "инструменты",
        "программы",
        "знание программ",
        "владение программами",
        "знание языков",
        "языки",
        "иностранные языки",
        "знание иностранных языков",
        "skills",
        "key skills",
        "hard skills",
        "soft skills",
        "languages",
        "tech stack",
        "technologies",
        "tools",
    ],
    "about": [
        "о себе",
        "обо мне",
        "личные качества",
        "дополнительная информация",
        "дополнительные сведения",
        "общая информация",
        "цель",
        "желаемая должность",
        "желаемая должность и зарплата",
        "профиль",
        "summary",
        "about",
        "about me",
        "profile",
        "objective",
        "сопроводительное письмо",
        "cover letter",
        "специализации",
        "специализация",
    ],
    "contacts": [
        "контакты",
        "контактная информация",
        "контактные данные",
        "личные данные",
        "contacts",
        "contact information",
        "contact",
    ],
    "other": [
        "хобби",
        "интересы",
        "увлечения",
        "рекомендации",
        "портфолио",
        "публикации",
        "награды",
        "награды и достижения",
        "hobbies",
        "interests",
        "references",
        "portfolio",
        "publications",
        "awards",
    ],
}

_VACANCY_HEADINGS: dict[str, list[str]] = {
    "requirements": [
        "требования",
        "требования к кандидату",
        "требования к соискателю",
        "основные требования",
        "квалификационные требования",
        "квалификация",
        "мы ждем",
        "мы ждем от вас",
        "мы ждем от кандидата",
        "что мы ждем",
        "что мы ждем от вас",
        "мы ожидаем",
        "наши ожидания",
        "что нужно",
        "что нам важно",
        "кого мы ищем",
        "мы ищем",
        "ты нам подходишь если",
        "вы нам подходите если",
        "необходимые навыки",
        "что для нас важно",
        "требуемый опыт",
        "requirements",
        "what we expect",
        "qualifications",
        "must have",
    ],
    "nice_to_have": [
        "будет плюсом",
        "будет преимуществом",
        "плюсом будет",
        "преимуществом будет",
        "желательно",
        "приветствуется",
        "дополнительным плюсом будет",
        "будет здорово",
        "будет большим плюсом",
        "nice to have",
        "would be a plus",
        "plus",
    ],
    "duties": [
        "обязанности",
        "должностные обязанности",
        "основные обязанности",
        "функциональные обязанности",
        "задачи",
        "основные задачи",
        "ваши задачи",
        "твои задачи",
        "чем предстоит заниматься",
        "что предстоит делать",
        "чем заниматься",
        "что нужно делать",
        "что делать",
        "функционал",
        "функции",
        "responsibilities",
        "what you will do",
        "your tasks",
    ],
    "conditions": [
        "условия",
        "условия работы",
        "мы предлагаем",
        "что мы предлагаем",
        "предлагаем",
        "что мы даем",
        "мы даем",
        "компенсация",
        "бонусы",
        "плюшки",
        "преимущества работы",
        "что мы предлагаем вам",
        "we offer",
        "benefits",
        "conditions",
    ],
    "about": [
        "о компании",
        "о нас",
        "о проекте",
        "о команде",
        "описание",
        "описание вакансии",
        "кто мы",
        "about us",
        "about the company",
    ],
    "skills": ["ключевые навыки", "навыки", "key skills", "skills"],
    "contacts": ["контакты", "контактная информация", "contacts"],
}


def _key(text: str) -> str:
    s = text.lower().replace("ё", "е")
    s = re.sub(r"^[\d.)\s]+", "", s)  # «1. Требования»
    s = s.strip(" :.;!?—–-\t*")
    s = re.sub(r"[,]", "", s)
    return re.sub(r"\s+", " ", s)


def _index(table: dict[str, list[str]]) -> dict[str, str]:
    return {_key(phrase): role for role, phrases in table.items() for phrase in phrases}


HEADINGS: dict[DocKind, dict[str, str]] = {
    DocKind.resume: _index(_RESUME_HEADINGS),
    DocKind.vacancy: _index(_VACANCY_HEADINGS),
}
DEFAULT_ROLE = {DocKind.resume: "contacts", DocKind.vacancy: "about"}

_INLINE_RE = re.compile(r"^([^:]{2,45}):\s*(\S.*)$")
# «Опыт работы: 3 года 2 месяца» — это заголовок раздела со сводкой, а не строка раздела
_DURATION_TAIL = re.compile(r"^\d+\s*(?:год|лет|г\.|мес|year|month)", re.IGNORECASE)
_DASH_TAIL_RE = re.compile(r"^(.{2,40}?)\s*[—–-]\s*\d")


def match_heading(text: str, kind: DocKind) -> tuple[str, str, bool] | None:
    """(роль, заголовок как написан, inline) или None. inline — «Заголовок: содержимое»."""
    table = HEADINGS[kind]
    if len(text) <= 80:
        k = _key(text)
        if k in table:
            return table[k], text.strip().rstrip(":").strip(), False
        m = _DASH_TAIL_RE.match(k)  # «Опыт работы — 6 лет 2 месяца»
        if m and _key(m.group(1)) in table:
            return table[_key(m.group(1))], text.strip(), False
    m = _INLINE_RE.match(text)
    if m and _key(m.group(1)) in table:
        inline = not _DURATION_TAIL.match(m.group(2).strip())
        return table[_key(m.group(1))], m.group(1).strip(), inline
    return None


_TITLE_PREFIX = re.compile(r"^(?:вакансия|должность|позиция|vacancy|position)\s*[:—–-]\s*", re.I)


def find_title(fragments: list[Fragment]) -> str | None:
    for frag in fragments[:10]:
        m = _TITLE_PREFIX.match(frag.text)
        if m and frag.text[m.end() :].strip():
            return frag.text[m.end() :].strip()[:200]
    for frag in fragments[:10]:
        if _key(frag.text) in ("вакансия", "vacancy"):
            continue
        if frag.section_role == DEFAULT_ROLE[DocKind.vacancy] or frag.section is None:
            return frag.text[:200]
        break
    return fragments[0].text[:200] if fragments else None


def build_fragments(
    blocks: list[Block], kind: DocKind, doc_id: str
) -> tuple[list[Fragment], list[str]]:
    prefix = "R" if kind == DocKind.resume else f"{doc_id}."
    role = DEFAULT_ROLE[kind]
    section: str | None = None
    fragments: list[Fragment] = []
    warnings: list[str] = []
    truncated = False

    for block in blocks:
        text = normalize(block.text)
        if not text:
            continue
        text, bullet = strip_bullet(text)
        heading = match_heading(text, kind)
        frag_role, frag_section = role, section
        if heading and not heading[2]:
            role, section = heading[0], heading[1]
            frag_role, frag_section = role, section
        elif heading:
            frag_role, frag_section = heading[0], heading[1]
        elif block.heading_style and len(text) <= 80:
            section = frag_section = text.rstrip(":")

        source = block.source
        if source == FragmentSource.paragraph and (bullet or block.list_item):
            source = FragmentSource.list_item
        for chunk in split_long(text):
            if len(fragments) >= MAX_FRAGMENTS:
                truncated = True
                break
            n = len(fragments) + 1
            fragments.append(
                Fragment(
                    id=f"{prefix}{n}",
                    order=n,
                    section=frag_section,
                    section_role=frag_role,
                    source=source,
                    text=chunk,
                )
            )
        if truncated:
            warnings.append(
                f"Документ обрезан до {MAX_FRAGMENTS} фрагментов: остальной текст не учитывается."
            )
            break
    return fragments, warnings


_DATE_RANGE = re.compile(
    r"(?:(?:0?[1-9]|1[0-2])[./])?(?:19|20)\d{2}\s*(?:г\.?\s*)?[—–-]\s*"
    r"(?:(?:(?:0?[1-9]|1[0-2])[./])?(?:19|20)\d{2}|по\s*н|наст|н\.\s*в|сейчас|present|now|current)",
    re.IGNORECASE,
)
_VACANCY_MARKERS = re.compile(
    r"требовани|обязанност|мы предлагаем|будет плюсом|условия работы|график работы|заработн",
    re.IGNORECASE,
)


def kind_warnings(fragments: list[Fragment], kind: DocKind) -> list[str]:
    roles = Counter(f.section_role for f in fragments)
    text = "\n".join(f.text for f in fragments)
    has_dates = bool(_DATE_RANGE.search(text))
    out: list[str] = []
    if kind == DocKind.resume:
        resume_sections = roles["experience"] + roles["education"] + roles["skills"]
        if not resume_sections and not has_dates:
            out.append(
                "Документ не похож на резюме: не найдены разделы опыта, образования или навыков "
                "и периоды работы."
            )
        elif not resume_sections and len(_VACANCY_MARKERS.findall(text)) >= 3:
            out.append("Документ похож на вакансию, а не на резюме.")
    else:
        vacancy_sections = sum(
            roles[r] for r in ("requirements", "duties", "nice_to_have", "skills", "conditions")
        )
        if not vacancy_sections:
            if len(_DATE_RANGE.findall(text)) >= 2 and not _VACANCY_MARKERS.search(text):
                out.append("Документ похож на резюме, а не на вакансию.")
            else:
                out.append(
                    "В вакансии не найдены разделы требований или обязанностей: требования "
                    "будут искаться по всему тексту."
                )
    if sum(len(f.text) for f in fragments) < 300:
        out.append("В документе мало текста: выводы будут неполными.")
    return out
