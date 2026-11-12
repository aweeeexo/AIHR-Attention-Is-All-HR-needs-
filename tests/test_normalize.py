"""T05, часть B: даты, стаж, уровни — кодом, без LLM."""

import pytest

from aihr.contracts import (
    CandidateProfile,
    EducationLevel,
    Language,
    MentionType,
    Position,
    SkillMention,
    YearMonth,
)
from aihr.normalize import enrich_profile
from aihr.normalize.dates import parse_duration, parse_period, parse_point
from aihr.normalize.levels import (
    cefr_from_text,
    education_from_text,
    meets_education,
    meets_language,
    required_education,
)
from aihr.normalize.tenure import format_months, months_between, tenure_for

TODAY = YearMonth(year=2026, month=11)


def ym(year: int, month: int | None = None) -> YearMonth:
    return YearMonth(year=year, month=month)


# ---------- точки и периоды ----------


@pytest.mark.parametrize(
    ("text", "expected", "approx"),
    [
        ("03.2021", ym(2021, 3), False),
        ("3/2021", ym(2021, 3), False),
        ("2021-03", ym(2021, 3), False),
        ("март 2021", ym(2021, 3), False),
        ("марта 2021", ym(2021, 3), False),
        ("мар. 2021", ym(2021, 3), False),
        ("March 2021", ym(2021, 3), False),
        ("Mar 2021", ym(2021, 3), False),
        ("Сентябрь 2019", ym(2019, 9), False),
        ("2021", ym(2021), True),
    ],
)
def test_parse_point(text: str, expected: YearMonth, approx: bool) -> None:
    p = parse_point(text)
    assert p is not None
    assert (p.ym, p.approximate) == (expected, approx)


@pytest.mark.parametrize(
    ("raw", "start", "end", "current", "approx"),
    [
        ("03.2019 — 06.2021", ym(2019, 3), ym(2021, 6), False, False),
        ("2019–2021", ym(2019), ym(2021), False, True),
        ("с 2019 по 2021", ym(2019), ym(2021), False, True),
        ("с 03.2019", ym(2019, 3), TODAY, True, False),
        ("01.2022 - по н.в.", ym(2022, 1), TODAY, True, False),
        ("Январь 2020 — по настоящее время (6 лет 10 месяцев)", ym(2020, 1), TODAY, True, False),
        ("сентябрь 2023 — сейчас", ym(2023, 9), TODAY, True, False),
        ("Jun 2018 – present", ym(2018, 6), TODAY, True, False),
        ("2015-09 to 2018-06", ym(2015, 9), ym(2018, 6), False, False),
        ("март 2021 — июнь 2024", ym(2021, 3), ym(2024, 6), False, False),
        ("2017", ym(2017, 1), ym(2018, 1), False, True),
        ("05.2020", ym(2020, 5), ym(2020, 5), False, False),
    ],
)
def test_parse_period(
    raw: str, start: YearMonth, end: YearMonth, current: bool, approx: bool
) -> None:
    p = parse_period(raw, TODAY)
    assert p is not None
    assert (p.start, p.end, p.is_current, p.approximate) == (start, end, current, approx)


@pytest.mark.parametrize("raw", ["", None, "по договорённости", "2023 — 2019", "knowledge"])
def test_parse_period_none(raw: str | None) -> None:
    assert parse_period(raw, TODAY) is None


@pytest.mark.parametrize(
    ("text", "months"),
    [("5 лет 3 месяца", 63), ("1 год", 12), ("7 лет 9 месяцев", 93), ("11 мес.", 11),
     ("2 years 4 months", 28), ("без опыта", None)],
)  # fmt: skip
def test_parse_duration(text: str, months: int | None) -> None:
    assert parse_duration(text) == months


# ---------- стаж ----------


def pos(raw: str, fid: str = "R1", tools: list[str] | None = None) -> Position:
    return Position(
        title="Должность",
        organization=None,
        start=None,
        end=None,
        raw_dates=raw,
        tools=tools or [],
        fragment_ids=[fid],
    )


def test_duration_matches_contract_example() -> None:
    assert months_between(ym(2021, 3), ym(2024, 6)) == 39
    assert format_months(39) == "3 г. 3 мес."
    assert format_months(24, approximate=True) == "≈ 2 г."
    assert format_months(5) == "5 мес."
    assert format_months(None) == "не указано"


def test_overlapping_periods_not_double_counted() -> None:
    profile = enrich_profile(
        CandidateProfile(positions=[pos("2019–2021", "R1"), pos("2020–2022", "R2")]), TODAY
    )
    durations = [p.duration_months for p in profile.positions]
    assert durations == [24, 24]  # год без месяца — середина года
    assert profile.total_experience_months == 36  # объединение, а не 48
    assert all(p.dates_approximate for p in profile.positions)


def test_total_with_current_job_and_gap() -> None:
    profile = enrich_profile(
        CandidateProfile(
            positions=[pos("03.2016 — 02.2019", "R1"), pos("01.2021 — по н.в.", "R2")]
        ),
        TODAY,
    )
    assert profile.positions[1].is_current and profile.positions[1].end == TODAY
    assert profile.total_experience_months == 35 + 70
    assert profile.gaps_months == [(ym(2019, 2), ym(2021, 1))]


def test_short_break_is_not_a_gap() -> None:
    profile = enrich_profile(
        CandidateProfile(
            positions=[pos("01.2018 — 03.2020", "R1"), pos("08.2020 — 12.2022", "R2")]
        ),
        TODAY,
    )
    assert profile.gaps_months == []


def test_skill_tenure_by_fragments_and_tools() -> None:
    skills = [
        SkillMention(
            name="пароконвектомат", mention_type=MentionType.evidenced, fragment_ids=["R2"]
        ),
        SkillMention(name="Excel", mention_type=MentionType.listed_only, fragment_ids=["R30"]),
        SkillMention(name="1С", mention_type=MentionType.evidenced, fragment_ids=["R40"]),
    ]
    profile = enrich_profile(
        CandidateProfile(
            positions=[
                pos("01.2015 — 01.2018", "R1", tools=["Excel"]),
                pos("01.2018 — 01.2021", "R2"),
            ],
            skills=skills,
        ),
        TODAY,
    )
    by_name = {s.name: s for s in profile.skills}
    assert by_name["пароконвектомат"].years == 3.0
    assert by_name["пароконвектомат"].last_used_year == 2021
    assert by_name["Excel"].years == 3.0  # из инструментов места работы
    assert by_name["1С"].years is None  # не привязан ни к одному месту работы


def test_resume_without_dates() -> None:
    profile = enrich_profile(CandidateProfile(positions=[pos("")], skills=[]), TODAY)
    assert profile.total_experience_months is None
    assert profile.positions[0].duration_months is None
    assert tenure_for(profile.positions) == (None, False)


def test_tenure_for_subset() -> None:
    positions = enrich_profile(
        CandidateProfile(positions=[pos("2019–2021", "R1"), pos("03.2022 — 03.2023", "R2")]),
        TODAY,
    ).positions
    assert tenure_for(positions) == (36, True)
    assert tenure_for(positions[1:]) == (12, False)


# ---------- уровни ----------


@pytest.mark.parametrize(
    ("text", "level"),
    [
        ("Высшее", EducationLevel.bachelor),
        ("Бакалавр, юриспруденция", EducationLevel.bachelor),
        ("Магистр экономики", EducationLevel.master),
        ("Неоконченное высшее", EducationLevel.incomplete_higher),
        ("Среднее специальное", EducationLevel.vocational),
        ("Медицинский колледж", EducationLevel.vocational),
        ("Кандидат технических наук", EducationLevel.phd),
        ("к.э.н.", EducationLevel.phd),
        ("Курсы повышения квалификации", EducationLevel.course),
        ("Среднее общее", EducationLevel.secondary),
        ("что-то непонятное", None),
    ],
)
def test_education_from_text(text: str, level: EducationLevel | None) -> None:
    assert education_from_text(text) == level


def test_meets_education() -> None:
    higher = required_education("higher")
    assert higher == EducationLevel.bachelor
    assert meets_education([EducationLevel.specialist], higher) is True
    assert meets_education([EducationLevel.master, EducationLevel.course], higher) is True
    assert meets_education([EducationLevel.vocational], higher) is False
    assert meets_education([EducationLevel.course], higher) is None  # курсы — не уровень
    assert meets_education([], higher) is None  # «не указано», а не «нет»


@pytest.mark.parametrize(
    ("text", "cefr"),
    [
        ("B2", "B2"), ("В2", "B2"), ("Upper-Intermediate", "B2"), ("разговорный", "B2"),
        ("Intermediate", "B1"), ("технический, читаю документацию", "B1"),
        ("Pre-intermediate", "A2"), ("базовый", "A2"), ("свободный", "C1"), ("Fluent", "C1"),
        ("родной", "C2"), ("Native", "C2"), ("C1 — Продвинутый", "C1"), ("хороший", None),
    ],
)  # fmt: skip
def test_cefr_from_text(text: str, cefr: str | None) -> None:
    assert cefr_from_text(text) == cefr


def test_meets_language_and_enrich() -> None:
    assert meets_language("C1", "B2") is True
    assert meets_language("B1", "не ниже B2") is False
    assert meets_language(None, "B2") is None
    profile = enrich_profile(
        CandidateProfile(
            languages=[
                Language(name="английский", level_raw="Upper-Intermediate", fragment_ids=["R9"])
            ]
        ),
        TODAY,
    )
    assert profile.languages[0].cefr == "B2"
