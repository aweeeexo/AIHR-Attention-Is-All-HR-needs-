"""Уровни образования и языка кодом (D13). Неизвестное значение → None: не угадываем."""

from __future__ import annotations

import re

from aihr.contracts import EducationLevel

# bachelor = specialist; курсы — не уровень образования
EDUCATION_RANK: dict[EducationLevel, int] = {
    EducationLevel.secondary: 1,
    EducationLevel.vocational: 2,
    EducationLevel.incomplete_higher: 3,
    EducationLevel.bachelor: 4,
    EducationLevel.specialist: 4,
    EducationLevel.master: 5,
    EducationLevel.phd: 6,
    EducationLevel.doctor: 7,
}

_EDU_PATTERNS: list[tuple[re.Pattern[str], EducationLevel]] = [
    (re.compile(r"(?i)неоконченн\w*\s+высш|незаконченн\w*\s+высш|incomplete\s+higher"),
     EducationLevel.incomplete_higher),
    (re.compile(r"(?i)доктор\w*\s+\w*\s*наук|\bд\.\s?[а-я]{1,3}\.\s?н\.|doctor\s+of\s+science"),
     EducationLevel.doctor),
    (re.compile(r"(?i)кандидат\w*\s+\w*\s*наук|\bк\.\s?[а-я]{1,3}\.\s?н\.|\bph\.?\s?d\b|аспирантур"),
     EducationLevel.phd),
    (re.compile(r"(?i)магистр|master|\bmsc\b|\bm\.s\.|\bmba\b"), EducationLevel.master),
    (re.compile(r"(?i)специалитет|специалист\b|дипломированн\w+\s+специалист"),
     EducationLevel.specialist),
    (re.compile(r"(?i)бакалавр|bachelor|\bbsc\b|\bb\.s\.|высше\w*|higher|degree|университет|институт"),
     EducationLevel.bachelor),
    (re.compile(r"(?i)средн\w*\s+(?:специальн|профессиональн|техническ)|колледж|техникум|училищ"
                r"|\bспо\b|vocational"), EducationLevel.vocational),
    (re.compile(r"(?i)курс\w*|тренинг|course|bootcamp"), EducationLevel.course),
    (re.compile(r"(?i)средн\w*\s+(?:общ|образован)|школ|secondary|high\s+school"),
     EducationLevel.secondary),
]  # fmt: skip

# Значение порога в требовании (Threshold.value) → минимальный уровень
REQUIRED_EDUCATION: dict[str, EducationLevel] = {
    "higher": EducationLevel.bachelor,
    "bachelor": EducationLevel.bachelor,
    "specialist": EducationLevel.specialist,
    "master": EducationLevel.master,
    "phd": EducationLevel.phd,
    "doctor": EducationLevel.doctor,
    "vocational": EducationLevel.vocational,
    "secondary": EducationLevel.secondary,
    "incomplete_higher": EducationLevel.incomplete_higher,
}


def education_from_text(text: str) -> EducationLevel | None:
    for pattern, level in _EDU_PATTERNS:
        if pattern.search(text):
            return level
    return None


def required_education(value: str) -> EducationLevel | None:
    v = value.strip().lower()
    return REQUIRED_EDUCATION.get(v) or education_from_text(v)


def meets_education(levels: list[EducationLevel | None], required: EducationLevel) -> bool | None:
    """True / False по лучшему уровню кандидата; None — уровней нет (значит «не указано»)."""
    ranks = [EDUCATION_RANK[lv] for lv in levels if lv is not None and lv in EDUCATION_RANK]
    if not ranks or required not in EDUCATION_RANK:
        return None
    return max(ranks) >= EDUCATION_RANK[required]


CEFR = ["A1", "A2", "B1", "B2", "C1", "C2"]
# Латинские и кириллические буквы: «В2» часто пишут русской «В»
_CEFR_CODE = re.compile(r"(?<![A-Za-zА-Яа-я])([AaАа]|[BbВв]|[CcСс])\s?([12])(?!\d)")
_CEFR_WORDS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?i)upper[\s-]?intermediate|выше\s+среднего|разговорн"), "B2"),
    (re.compile(r"(?i)pre[\s-]?intermediate|ниже\s+среднего"), "A2"),
    (re.compile(r"(?i)intermediate|средн|техническ|читаю\s+(?:техническ|документ|професс)"), "B1"),
    (re.compile(r"(?i)proficien|в\s+совершенстве"), "C2"),
    (re.compile(r"(?i)native|родно|носител"), "C2"),
    (re.compile(r"(?i)advanced|fluent|свободн|продвинут"), "C1"),
    (re.compile(r"(?i)elementary|базов|начальн|basic"), "A2"),
    (re.compile(r"(?i)beginner|starter|со\s+словарём|со\s+словарем"), "A1"),
]  # fmt: skip
_CYR_TO_LAT = str.maketrans("АаВвСс", "AABBCC")


def cefr_from_text(text: str) -> str | None:
    m = _CEFR_CODE.search(text)
    if m:
        return (m.group(1).translate(_CYR_TO_LAT).upper() + m.group(2)).upper()
    for pattern, level in _CEFR_WORDS:
        if pattern.search(text):
            return level
    return None


def meets_language(candidate: str | None, required: str) -> bool | None:
    req = cefr_from_text(required) or required.upper()
    if candidate is None or candidate not in CEFR or req not in CEFR:
        return None
    return CEFR.index(candidate) >= CEFR.index(req)
