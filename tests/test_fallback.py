"""T11: режим без LLM — требования, профиль, сопоставление, переключение, кейс."""

from pathlib import Path

import pytest

from aihr import pipeline
from aihr.config import Settings
from aihr.contracts import (
    DocKind,
    EducationLevel,
    MentionType,
    Modality,
    ReqKind,
    Status,
    ThresholdKind,
    YearMonth,
)
from aihr.fallback import (
    extract_profile_fallback,
    extract_requirements_fallback,
    match_vacancy_fallback,
)
from aihr.ingest import load_document
from aihr.inputs import case_files, read_files
from aihr.normalize import enrich_profile
from aihr.privacy import PrivacyContext, mask_document
from aihr.retrieve import Retriever
from tests.conftest import CASE_DIR, FIXTURES, fixture_file

TODAY = YearMonth(year=2026, month=11)

RESUME = """Кузнецова Мария
Опыт работы
03.2019 — по настоящее время, ГБУЗ «Городская поликлиника № 5», медицинская сестра.
Забор венозной крови, внутривенные инъекции, ведение документации в МИС.
2015 — 2018, ООО «Клиника Здоровье», младшая медицинская сестра.
Уход за пациентами, подготовка процедурного кабинета.
Образование
2015, Медицинский колледж № 1, сестринское дело.
Навыки
Забор крови, внутривенные инъекции, МИС, стерилизация инструментов.
Английский язык — базовый.
Свидетельство об аккредитации специалиста, 2024.
"""


def _vacancy(name: str, doc_id: str = "V1"):
    data, filename = fixture_file(name) if "/" not in name else (Path(name).read_bytes(), name)
    return mask_document(load_document(data, filename, DocKind.vacancy, doc_id), PrivacyContext())


def _resume(text: str = RESUME):
    doc = load_document(text.encode(), "Кузнецова Мария_резюме.txt", DocKind.resume, "R")
    return mask_document(doc, PrivacyContext())


# ---------- требования ----------


def test_requirements_from_sections() -> None:
    reqs = extract_requirements_fallback(_vacancy("vacancy_cook.txt"))
    by_text = {r.text: r for r in reqs}
    years = by_text["Опыт работы поваром от 3 лет."]
    assert years.kind == ReqKind.experience and years.modality == Modality.must
    assert years.threshold is not None and years.threshold.kind == ThresholdKind.years
    assert years.threshold.value == "3" and years.threshold.subject == "поваром"
    edu = by_text["Среднее профессиональное образование по специальности."]
    assert edu.kind == ReqKind.education
    assert edu.threshold is not None and edu.threshold.value == "vocational"
    nice = next(r for r in reqs if "пароконвектомат" in r.text)
    assert nice.modality == Modality.nice and nice.modality_marker
    duties = [r for r in reqs if r.kind == ReqKind.duty]
    assert duties and all(r.modality == Modality.nice for r in duties)  # D3
    assert all(r.source_fragment_ids for r in reqs)


def test_requirements_soft_and_language() -> None:
    text = (
        "Аналитик данных\nТребования:\nВысшее образование.\nАнглийский язык не ниже B2.\n"
        "Ответственность и внимание к деталям.\nОпыт работы от 2 лет."
    )
    doc = mask_document(
        load_document(text.encode(), "v.txt", DocKind.vacancy, "V2"), PrivacyContext()
    )
    reqs = {r.text: r for r in extract_requirements_fallback(doc)}
    assert reqs["Высшее образование."].threshold.value == "higher"  # type: ignore[union-attr]
    lang = reqs["Английский язык не ниже B2."]
    assert lang.kind == ReqKind.language and lang.threshold.value == "B2"  # type: ignore[union-attr]
    # «и» между двумя терминами словаря — два атомарных требования
    assert not reqs["Ответственность"].verifiable
    assert not reqs["внимание к деталям"].verifiable
    total = reqs["Опыт работы от 2 лет."].threshold
    assert total is not None and total.subject is None  # общий стаж, без темы


def test_requirements_plain_text_vacancy() -> None:
    from tests.bad_files import PLAIN_VACANCY

    doc = mask_document(
        load_document(PLAIN_VACANCY.encode(), "v.txt", DocKind.vacancy, "V1"), PrivacyContext()
    )
    reqs = extract_requirements_fallback(doc)
    assert reqs  # без заголовков требования всё равно находятся


@pytest.mark.parametrize("name", ["nurse.txt", "sales.txt", "lawyer.txt", "engineer_en.txt"])
def test_requirements_other_professions(name: str) -> None:
    doc = mask_document(
        load_document(
            (FIXTURES / "vacancies_other" / name).read_bytes(), name, DocKind.vacancy, "V1"
        ),
        PrivacyContext(),
    )
    reqs = extract_requirements_fallback(doc)
    assert len(reqs) >= 3
    assert {Modality.must} <= {r.modality for r in reqs}


# ---------- профиль ----------


def test_profile_fallback() -> None:
    profile = enrich_profile(extract_profile_fallback(_resume()), TODAY)
    assert [p.raw_dates for p in profile.positions] == [
        "03.2019 — по настоящее время",
        "2015 — 2018",
    ]
    assert profile.positions[0].is_current
    assert profile.positions[0].organization and "поликлиника" in profile.positions[0].organization
    assert profile.total_experience_months == 92 + 36
    assert profile.education[0].level == EducationLevel.vocational
    assert profile.education[0].year_end == 2015
    langs = {lang.name.lower()[:4]: lang for lang in profile.languages}
    assert langs["англ"].cefr == "A2"
    skills = {s.name: s for s in profile.skills}
    assert skills["внутривенные инъекции"].mention_type == MentionType.evidenced
    assert skills["стерилизация инструментов"].mention_type == MentionType.listed_only
    assert profile.certificates


# ---------- сопоставление ----------


def _match(vacancy_text: str):
    vac = mask_document(
        load_document(vacancy_text.encode(), "v.txt", DocKind.vacancy, "V1"), PrivacyContext()
    )
    resume = _resume()
    profile = enrich_profile(extract_profile_fallback(resume), TODAY)
    reqs = extract_requirements_fallback(vac)
    verdicts = match_vacancy_fallback(reqs, profile, resume, Retriever(resume, embeddings=False))
    return {r.text: v for r, v in zip(reqs, verdicts, strict=True)}


def test_match_statuses() -> None:
    v = _match(
        "Медсестра\nТребования:\nЗабор венозной крови и внутривенные инъекции.\n"
        "Стерилизация инструментов.\nОпыт работы медицинской сестрой от 5 лет.\n"
        "Высшее образование.\nКоммуникабельность.\nВладение японским языком на уровне B2."
    )
    blood = v["Забор венозной крови"]  # перечисление терминов словаря поделено на атомарные
    assert v["внутривенные инъекции"].status == Status.match
    assert blood.status == Status.match and blood.evidence and blood.decided_by == "fallback"
    assert blood.evidence[0].quote  # цитату подставил код
    listed = v["Стерилизация инструментов."]
    assert listed.status == Status.match and listed.needs_review  # только в списке навыков
    years = v["Опыт работы медицинской сестрой от 5 лет."]
    assert years.status == Status.match and years.computed
    edu = v["Высшее образование."]
    assert edu.status == Status.mismatch and edu.computed  # доказал код: колледж < высшее
    assert v["Коммуникабельность."].status == Status.not_stated
    assert v["Владение японским языком на уровне B2."].status == Status.not_stated


def test_unknown_requirement_is_not_stated_not_mismatch() -> None:
    v = _match("Пилот\nТребования:\nНалёт на Boeing 737 от 1500 часов.\nДопуск к полётам по ПВП.")
    assert all(x.status == Status.not_stated and not x.evidence for x in v.values())


# ---------- переключение и кейс ----------


def test_provider_none_runs_fallback_with_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "none")
    from aihr.config import get_settings

    get_settings.cache_clear()
    r = pipeline.run(fixture_file("resume_cook.txt"), [fixture_file("vacancy_cook.txt")])
    assert r.mode == "fallback"
    assert any("LLM_PROVIDER=none" in w for w in r.warnings)
    assert r.ranking and r.ranking.items and r.reports


def test_case_fallback_mismatch_only_with_code_proof() -> None:
    settings = Settings(_env_file=None, llm_provider="none")  # type: ignore[call-arg]
    resumes, vacancies = case_files(CASE_DIR)
    for resume in resumes:
        r = pipeline.run(
            read_files([resume])[0], read_files(vacancies), settings=settings, save=False
        )
        assert r.mode == "fallback" and r.ranking and len(r.ranking.items) == 3
        for verdicts in r.verdicts.values():
            for v in verdicts:
                if v.status == Status.mismatch:
                    assert v.computed, "«Не соответствует» без расчёта кода"
                if v.status != Status.not_stated:
                    assert v.evidence and all(e.quote for e in v.evidence)
