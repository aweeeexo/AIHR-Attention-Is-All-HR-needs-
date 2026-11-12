"""T06, часть B (поиск) и T07, шаг 4 (правила поверх LLM)."""

import time
from typing import ClassVar

import numpy as np
import pytest

from aihr.contracts import (
    CandidateProfile,
    DocKind,
    Education,
    EducationLevel,
    Evidence,
    Language,
    Modality,
    Position,
    ReqKind,
    Requirement,
    Status,
    Threshold,
    ThresholdKind,
    Verdict,
    YearMonth,
)
from aihr.ingest import load_document
from aihr.match import apply_rules
from aihr.normalize import enrich_profile
from aihr.privacy import PrivacyContext, mask_document
from aihr.retrieve import Retriever, roles_for, tokens

RESUME = """Опыт работы
2018 — 2023, ООО «Пример», инженер-сметчик. Составлял локальные сметы в Гранд-Смете.
Вёл учёт имущества организации и инвентаризацию оборудования.
Писал скрипты на JS для автоматизации отчётов, C++ — для расчётного модуля.
Внедрил систему менеджмента качества по ISO 9001.
Образование
2017, Строительный университет, промышленное и гражданское строительство.
Навыки: 1С, Excel, AutoCAD.
"""


@pytest.fixture
def resume():
    doc = load_document(RESUME.encode(), "r.txt", DocKind.resume, "R")
    return mask_document(doc, PrivacyContext())


# ---------- токены ----------


def test_tokens_keep_exact_terms() -> None:
    toks = tokens("Знание 1С, C++, C# и ISO 9001; Ёлка")
    assert {"1с", "c++", "c#", "iso", "9001"} <= set(toks)
    assert "и" not in toks and "елк" in toks  # стоп-слово выброшено, ё → е, стемминг


# ---------- поиск ----------


def _ids(retriever: Retriever, query: str, terms: list[str] | None = None, **kw) -> list[str]:
    return [fid for fid, _ in retriever.search(query, terms or [], **kw)]


def test_bm25_finds_exact_terms(resume) -> None:
    r = Retriever(resume, encoder=None)
    assert not r.uses_embeddings
    assert _ids(r, "Опыт работы в 1С")[0] == "R8"
    assert _ids(r, "Сертификация ISO 9001")[0] == "R5"
    assert "R4" in _ids(r, "C++")


def test_synonyms_via_terms(resume) -> None:
    r = Retriever(resume, encoder=None)
    assert _ids(r, "JavaScript") == []  # без словаря синонимов не находится
    assert _ids(r, "JavaScript", ["JS", "ECMAScript"])[0] == "R4"  # алиасы из T06-A


def test_section_filter_and_fallback(resume) -> None:
    r = Retriever(resume, encoder=None)
    edu = _ids(r, "Высшее строительное образование", section_roles=roles_for(ReqKind.education))
    assert edu and all(fid in ("R6", "R7") for fid in edu)
    # в разделе навыков нет «инвентаризации» — ищем по всему документу
    assert _ids(r, "инвентаризация", section_roles=["skills"])[0] == "R3"


def test_no_overlap_no_result(resume) -> None:
    assert Retriever(resume, encoder=None).search("пилотирование самолёта", []) == []


class FakeEncoder:
    """Векторы по «смыслу»: учёт/имущество/инвентаризация → одна ось, остальное — другая."""

    AXES: ClassVar[list[str]] = [
        "учет имуществ инвентар основн средств",
        "смет",
        "скрипт js",
        "iso качеств",
    ]

    def __call__(self, texts):
        out = []
        for t in texts:
            low = t.lower().replace("ё", "е")
            v = np.array([sum(w in low for w in axis.split()) for axis in self.AXES], dtype=float)
            v = v + 1e-3
            out.append(v / np.linalg.norm(v))
        return np.array(out)


def test_embeddings_find_paraphrase(resume) -> None:
    r = Retriever(resume, encoder=FakeEncoder(), e5_prefixes=True)
    assert r.uses_embeddings
    # в запросе нет ни одного слова из фрагмента R3, BM25 его не найдёт, эмбеддинги — найдут
    assert "R3" not in _ids(Retriever(resume, encoder=None), "основные средства")
    assert _ids(r, "основные средства")[0] == "R3"


def test_index_is_fast(resume) -> None:
    big = resume.model_copy(update={"fragments": resume.fragments * 200})
    started = time.perf_counter()
    Retriever(big, encoder=None).search("сметы", [])
    assert time.perf_counter() - started < 2


# ---------- правила ----------

TODAY = YearMonth(year=2026, month=11)


def _profile(**kw) -> CandidateProfile:
    return enrich_profile(CandidateProfile(**kw), TODAY)


def _position(raw: str, fid: str) -> Position:
    return Position(
        title="x", organization=None, start=None, end=None, raw_dates=raw, fragment_ids=[fid]
    )


def _req(kind: ThresholdKind, value: str, subject: str | None = None) -> Requirement:
    return Requirement(
        id="V1.req1",
        vacancy_id="V1",
        text="требование",
        kind=ReqKind.experience,
        modality=Modality.must,
        modality_marker=None,
        modality_reason="",
        threshold=Threshold(kind=kind, value=value, subject=subject),
        source_fragment_ids=["V1.1"],
    )


def _verdict(status: Status, *fids: str) -> Verdict:
    return Verdict(
        requirement_id="V1.req1",
        status=status,
        evidence=[Evidence(fragment_id=f, quote="") for f in fids],
        comment="",
        confidence=0.7,
        decided_by="pass_a",
    )


def test_years_by_topic_partial() -> None:
    profile = _profile(
        positions=[_position("03.2021 — 06.2022", "R2"), _position("2015 — 2020", "R5")]
    )
    req = _req(ThresholdKind.years, "3", subject="сметное дело")
    v = apply_rules(req, _verdict(Status.match, "R2"), profile)  # модель сочла достаточным
    assert v.status == Status.partial and v.decided_by == "rule"
    assert v.partial_value == round(15 / 36, 2)
    assert v.computed == "по теме: 03.2021–06.2022 = 1 г. 3 мес. < 3 лет"
    assert v.missing == "не хватает 1 г. 9 мес."


def test_years_match_and_union() -> None:
    profile = _profile(
        positions=[_position("03.2019 — 03.2022", "R2"), _position("01.2021 — по н.в.", "R5")]
    )
    v = apply_rules(
        _req(ThresholdKind.years, "3", subject="тема"),
        _verdict(Status.partial, "R2", "R5"),
        profile,
    )
    assert v.status == Status.match
    assert v.computed.startswith("по теме: 03.2019–03.2022, 01.2021–н.в. = 7 г. 8 мес. ≥ 3 лет")


def test_years_total_without_subject_adds_evidence() -> None:
    profile = _profile(positions=[_position("2016 — 2018", "R2")])
    v = apply_rules(_req(ThresholdKind.years, "1"), _verdict(Status.not_stated), profile)
    assert v.status == Status.match
    assert [e.fragment_id for e in v.evidence] == ["R2"]
    assert v.computed == "общий стаж: 2016–2018 = ≈ 2 г. ≥ 1 года"


def test_years_without_dates_keeps_model_verdict() -> None:
    profile = _profile(positions=[_position("", "R2")])
    verdict = _verdict(Status.match, "R2")
    assert apply_rules(_req(ThresholdKind.years, "3", subject="тема"), verdict, profile) == verdict


def test_education_rules() -> None:
    higher = _req(ThresholdKind.education_level, "higher")
    edu = Education(level=EducationLevel.vocational, institution="Колледж", field=None,
                    year_end=2015,
                    fragment_ids=["R7"])  # fmt: skip
    v = apply_rules(higher, _verdict(Status.match, "R7"), _profile(education=[edu]))
    assert v.status == Status.mismatch and v.evidence[0].fragment_id == "R7"
    master = edu.model_copy(update={"level": EducationLevel.master})
    assert (
        apply_rules(higher, _verdict(Status.partial), _profile(education=[master])).status
        == Status.match
    )
    none = apply_rules(higher, _verdict(Status.mismatch), _profile())
    assert none.status == Status.not_stated and none.evidence == []  # «не указано» ≠ «нет»


@pytest.mark.parametrize(
    ("level_raw", "status"),
    [("C1", Status.match), ("B1", Status.partial), ("A2", Status.mismatch), (None, Status.partial)],
)
def test_language_rules(level_raw: str | None, status: Status) -> None:
    lang = Language(name="Английский", level_raw=level_raw, fragment_ids=["R9"])
    req = _req(ThresholdKind.language_level, "B2", subject="английский")
    v = apply_rules(req, _verdict(Status.not_stated), _profile(languages=[lang]))
    assert v.status == status
    assert v.evidence[0].fragment_id == "R9"


def test_language_not_mentioned_stays_not_stated() -> None:
    lang = Language(name="Немецкий", level_raw="B2", fragment_ids=["R9"])
    req = _req(ThresholdKind.language_level, "B2", subject="английский")
    assert (
        apply_rules(req, _verdict(Status.not_stated), _profile(languages=[lang])).status
        == Status.not_stated
    )


def test_tokens_are_thread_safe() -> None:
    """Регрессия: общий стеммер snowball ломался при параллельной обработке вакансий."""
    from concurrent.futures import ThreadPoolExecutor

    texts = [
        f"developing interfaces responsibilities requirements {i} разработка" for i in range(400)
    ]
    expected = [tokens(t) for t in texts]
    with ThreadPoolExecutor(max_workers=8) as pool:
        for _ in range(5):
            assert list(pool.map(tokens, texts)) == expected
