"""T05-A: профиль кандидата — постобработка кодом поверх ответа модели (заглушка LLM)."""

import json

import pytest

from aihr.config import Settings
from aihr.contracts import DocKind, EducationLevel, MentionType, TaskLevel, YearMonth
from aihr.extract import extract_profile
from aihr.ingest import load_document
from aihr.llm import LLMClient
from aihr.normalize import enrich_profile
from aihr.privacy import PrivacyContext, mask_document
from tests.conftest import FakeOpenAI

RESUME = """Кузнецова Мария
Опыт работы
03.2019 — по настоящее время, ГБУЗ «Поликлиника № 5», старшая медицинская сестра.
Руководила сменой из 4 медсестёр, вела документацию в МИС «Инфоклиника».
2015 — 2018, ООО «Клиника», медицинская сестра.
Под руководством врача выполняла инъекции.
Образование
2015, медицинский колледж № 1, сестринское дело.
2022, курсы повышения квалификации «Сестринское дело в хирургии».
Навыки
МИС «Инфоклиника», стерилизация инструментов.
Английский — базовый.
Свидетельство об аккредитации, 2024.
"""


@pytest.fixture
def resume():
    doc = load_document(RESUME.encode(), "Кузнецова Мария_резюме.txt", DocKind.resume, "R")
    return mask_document(doc, PrivacyContext())


def _ids(doc) -> dict[str, str]:
    return {f.text[:25]: f.id for f in doc.fragments}


def _answer(doc) -> dict:
    f = _ids(doc)
    return {
        "positions": [
            {
                "title": "старшая медицинская сестра",
                "organization": "ГБУЗ «Поликлиника № 5»",
                "raw_dates": "03.2019 — по настоящее время",
                "tasks": ["руководство сменой", "ведение документации"],
                "tools": ["МИС «Инфоклиника»"],
                "level_reason": "руководила сменой",
                "level": "lead",
                "scale": "смена из 4 медсестёр",
                "fragment_ids": [f["03.2019 — по настоящее вр"], f["Руководила сменой из 4 ме"]],
            },
            {
                "title": "медицинская сестра",
                "organization": "ООО «Клиника»",
                "raw_dates": "2015 — 2018",
                "level": "executor",
                "fragment_ids": [
                    f["2015 — 2018, ООО «Клиника"],
                    f["Под руководством врача вы"],
                    "R999",
                ],
            },
            {"title": "выдуманная", "raw_dates": "2010", "fragment_ids": ["R998"]},
        ],
        "education": [
            {
                "level": None,
                "institution": "медицинский колледж № 1",
                "year_end": 2015,
                "fragment_ids": [f["2015, медицинский колледж"]],
            },
        ],
        "skills": [
            {"name": "МИС «Инфоклиника»", "fragment_ids": [f["МИС «Инфоклиника», стерил"]]},
            {"name": "стерилизация инструментов", "fragment_ids": [f["МИС «Инфоклиника», стерил"]]},
            {"name": "инъекции", "fragment_ids": []},
            {"name": "призрак", "fragment_ids": ["R997"]},
        ],
        "languages": [
            {
                "name": "английский",
                "level_raw": "базовый",
                "fragment_ids": [f["Английский — базовый."]],
            }
        ],
        "facts": [
            {
                "text": "Свидетельство об аккредитации, 2024",
                "category": "certificate",
                "fragment_ids": [f["Свидетельство об аккредит"]],
            },
            {
                "text": "Курсы «Сестринское дело в хирургии», 2022",
                "category": "course",
                "fragment_ids": [f["2022, курсы повышения ква"]],
            },
        ],
    }


def _run(doc, answer: dict):
    fake = FakeOpenAI([json.dumps(answer, ensure_ascii=False)])
    s = Settings(_env_file=None, llm_base_url="http://x/v1", llm_model="m")  # type: ignore[call-arg]
    return extract_profile(doc, LLMClient(s, client=fake)), fake


def test_profile_postprocessing(resume) -> None:
    answer = _answer(resume)
    answer["skills"] = [s for s in answer["skills"] if s["fragment_ids"]]  # схема требует min 1
    profile, fake = _run(resume, answer)
    assert len(fake.completions.calls) == 1
    user = fake.completions.calls[0]["messages"][1]["content"]
    assert "{Опыт работы}" in user and "Кузнецова" not in user  # раздел виден, ФИО замаскировано

    assert [p.title for p in profile.positions] == [
        "старшая медицинская сестра",
        "медицинская сестра",
    ]
    lead, executor = profile.positions
    assert lead.level == TaskLevel.lead and lead.scale == "смена из 4 медсестёр"
    assert "R999" not in executor.fragment_ids  # несуществующий фрагмент отброшен

    skills = {s.name: s for s in profile.skills}
    assert "призрак" not in skills
    assert skills["МИС «Инфоклиника»"].mention_type == MentionType.evidenced  # есть в опыте
    assert skills["стерилизация инструментов"].mention_type == MentionType.listed_only
    assert set(lead.fragment_ids) & set(skills["МИС «Инфоклиника»"].fragment_ids)

    levels = [e.level for e in profile.education]
    assert levels[0] == EducationLevel.vocational  # уровень по тексту фрагмента: колледж
    assert EducationLevel.course in levels  # курс из facts → образование с level=course
    assert [c.category for c in profile.certificates] == ["certificate"]
    assert profile.languages[0].level_raw == "базовый"


def test_dates_and_tenure_by_code(resume) -> None:
    answer = _answer(resume)
    answer["skills"] = [s for s in answer["skills"] if s["fragment_ids"]]
    profile, _ = _run(resume, answer)
    profile = enrich_profile(profile, YearMonth(year=2026, month=11))
    lead, executor = profile.positions
    assert lead.is_current and lead.duration_months == 92
    assert executor.dates_approximate and executor.duration_months == 36
    assert profile.total_experience_months == 128
    assert profile.languages[0].cefr == "A2"
    mis = next(s for s in profile.skills if s.name == "МИС «Инфоклиника»")
    assert mis.years == 7.7 and mis.last_used_year == 2026


def test_empty_profile_is_valid(resume) -> None:
    profile, _ = _run(
        resume, {"positions": [], "education": [], "skills": [], "languages": [], "facts": []}
    )
    assert profile.positions == [] and profile.total_experience_months is None
