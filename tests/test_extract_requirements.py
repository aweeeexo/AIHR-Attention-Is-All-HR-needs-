"""T04: требования вакансии — постобработка кодом поверх ответа модели (заглушка LLM)."""

import json

import pytest

from aihr.contracts import DocKind, Modality, ReqKind, ThresholdKind
from aihr.extract import extract_requirements
from aihr.ingest import load_document
from aihr.llm import LLMClient
from aihr.privacy import PrivacyContext, mask_document
from tests.conftest import FakeOpenAI

VACANCY = """Логист по холодовой цепи
Обязанности:
Составление маршрутов доставки.
Контроль температурного режима при перевозке.
Требования:
Опыт работы логистом от 2 лет.
Знание SAP или Oracle WMS, Excel и Power BI.
Английский не ниже B2.
Высшее образование.
Стрессоустойчивость.
Будет плюсом: опыт работы с фармацевтическими грузами, обязательно с GDP.
Условия:
Оклад 90 000 руб., ДМС.
"""


@pytest.fixture
def vacancy():
    doc = load_document(VACANCY.encode(), "v.txt", DocKind.vacancy, "V2")
    return mask_document(doc, PrivacyContext())


def _item(text: str, fids: list[str], kind: str = "skill", modality: str = "must", **kw) -> dict:
    return {
        "text": text,
        "kind": kind,
        "modality_reason": "модель",
        "modality": modality,
        "source_fragment_ids": fids,
        **kw,
    }


def _ids(doc) -> dict[str, str]:
    return {f.text: f.id for f in doc.fragments}


def _run(doc, *answers: list[dict], settings=None):
    fake = FakeOpenAI([json.dumps({"items": a}, ensure_ascii=False) for a in answers])
    from aihr.config import Settings

    s = settings or Settings(_env_file=None, llm_base_url="http://x/v1", llm_model="m")  # type: ignore[call-arg]
    return extract_requirements(doc, LLMClient(s, client=fake)), fake


def _full_answer(doc) -> list[dict]:
    f = _ids(doc)
    return [
        _item(
            "Опыт составления маршрутов доставки",
            [f["Составление маршрутов доставки."]],
            "duty",
            "must",
        ),
        _item(
            "Опыт контроля температурного режима",
            [f["Контроль температурного режима при перевозке."]],
            "duty",
        ),
        _item(
            "Опыт работы логистом от 2 лет",
            [f["Опыт работы логистом от 2 лет."]],
            "experience",
            "nice",
            threshold={"kind": "years", "value": 2, "subject": "логистика"},
        ),
        _item(
            "Знание SAP или Oracle WMS",
            [f["Знание SAP или Oracle WMS, Excel и Power BI."]],
            alternatives=["SAP", "Oracle WMS"],
        ),
        _item(
            "Знание Excel и Power BI",
            [f["Знание SAP или Oracle WMS, Excel и Power BI."]],
            alternatives=["Excel", "Power BI"],
        ),
        _item(
            "Английский не ниже B2",
            [f["Английский не ниже B2."]],
            "language",
            threshold={
                "kind": "language_level",
                "value": "upper-intermediate",
                "subject": "английский",
            },
        ),
        _item(
            "Высшее образование",
            [f["Высшее образование."]],
            "education",
            threshold={"kind": "education_level", "value": "высшее"},
        ),
        _item("Стрессоустойчивость", [f["Стрессоустойчивость."]], "soft"),
        _item(
            "Опыт с фармацевтическими грузами",
            [f["Будет плюсом: опыт работы с фармацевтическими грузами, обязательно с GDP."]],
            "experience",
            "must",
        ),
        _item("Оклад 90 000 руб.", [f["Оклад 90 000 руб., ДМС."]], "other"),
        _item("Выдуманное", ["V2.999"]),
    ]


def test_postprocessing_rules(vacancy) -> None:
    reqs, fake = _run(vacancy, _full_answer(vacancy))
    assert len(fake.completions.calls) == 1  # всё покрыто — повтора нет
    by = {r.text: r for r in reqs}
    assert [r.id for r in reqs] == [f"V2.req{i}" for i in range(1, len(reqs) + 1)]
    assert "Выдуманное" not in by and "Оклад 90 000 руб." not in by  # нет фрагмента / условия

    duty = by["Опыт составления маршрутов доставки"]
    assert duty.kind == ReqKind.duty and duty.modality == Modality.nice  # D3, модель сказала must
    assert "D3" in duty.modality_reason

    years = by["Опыт работы логистом от 2 лет"]
    assert (
        years.modality == Modality.must and years.modality_marker == "от 2 лет"
    )  # маркер > модель
    assert (
        years.threshold
        and years.threshold.value == "2"
        and years.threshold.kind == ThresholdKind.years
    )

    alt = by["Знание SAP или Oracle WMS"]
    assert alt.alternatives == ["SAP", "Oracle WMS"]  # «или» — альтернативы остаются
    assert "Знание Excel" in by and "Знание Power BI" in by  # перечисление без «или» — делим

    lang = by["Английский не ниже B2"]
    assert lang.threshold and lang.threshold.value == "B2"  # словесный уровень → CEFR кодом
    edu = by["Высшее образование"]
    assert edu.threshold and edu.threshold.value == "higher"
    assert not by["Стрессоустойчивость"].verifiable

    pharma = by["Опыт с фармацевтическими грузами"]
    assert (
        pharma.modality == Modality.nice
    )  # «будет плюсом» сильнее «обязательно» в том же фрагменте


def test_coverage_retry_only_on_uncovered(vacancy) -> None:
    answer = _full_answer(vacancy)
    first = [a for a in answer if "Стрессоустойчивость" not in a["text"]]
    f = _ids(vacancy)
    retry = [_item("Стрессоустойчивость", [f["Стрессоустойчивость."]], "soft")]
    reqs, fake = _run(vacancy, first, retry)
    assert len(fake.completions.calls) == 2
    retry_prompt = fake.completions.calls[1]["messages"][1]["content"]
    assert "Стрессоустойчивость" in retry_prompt and "маршрутов" not in retry_prompt
    assert "только те фрагменты" in retry_prompt
    assert any(r.text == "Стрессоустойчивость" for r in reqs)
    assert not vacancy.warnings


def test_uncovered_after_retry_gives_warning(vacancy) -> None:
    first = [a for a in _full_answer(vacancy) if "Стрессоустойчивость" not in a["text"]]
    reqs, _ = _run(vacancy, first, [])
    sid = _ids(vacancy)["Стрессоустойчивость."]
    assert any(sid in w for w in vacancy.warnings)
    assert reqs


def test_duplicates_merged_with_stricter_modality(vacancy) -> None:
    f = _ids(vacancy)
    answer = [
        *_full_answer(vacancy),
        _item(
            "Опыт работы логистом от 2 лет",
            [f["Составление маршрутов доставки."]],
            "experience",
            "nice",
        ),
    ]
    reqs, _ = _run(vacancy, answer)
    same = [r for r in reqs if r.text == "Опыт работы логистом от 2 лет"]
    assert len(same) == 1
    assert same[0].modality == Modality.must
    assert set(same[0].source_fragment_ids) == {
        f["Опыт работы логистом от 2 лет."],
        f["Составление маршрутов доставки."],
    }


def test_sections_are_shown_to_model(vacancy) -> None:
    _, fake = _run(vacancy, _full_answer(vacancy))
    user = fake.completions.calls[0]["messages"][1]["content"]
    assert "{Обязанности} Составление маршрутов доставки." in user
    assert "{Требования} Высшее образование." in user
    assert "<document>" in user


def test_plain_text_vacancy_uses_model_modality() -> None:
    text = "Ищем водителя: нужны права категории C и стаж от 3 лет, знание города желательно."
    doc = mask_document(
        load_document(text.encode(), "v.txt", DocKind.vacancy, "V1"), PrivacyContext()
    )
    fid = doc.fragments[0].id
    reqs, _ = _run(
        doc,
        [
            _item("Права категории C", [fid], "certificate", "must"),
            _item("Знание города", [fid], "skill", "nice"),
        ],
    )
    by = {r.text: r for r in reqs}
    # «желательно» относится только к своей части фразы; у второй нет ни маркера, ни раздела
    assert by["Знание города"].modality == Modality.nice
    assert by["Знание города"].modality_marker == "желательно"
    assert by["Права категории C"].modality == Modality.must  # мнение модели
    assert by["Права категории C"].modality_reason.startswith("оценка модели")


def test_vacancy_extracted_once_for_many_resumes(llm_settings) -> None:
    """T04 шаг 9: та же вакансия для разных кандидатов — один вызов извлечения (кэш)."""
    from aihr import pipeline
    from tests.conftest import EchoRequirementsLLM, fixture_file

    fake = EchoRequirementsLLM()
    llm = LLMClient(llm_settings, client=fake)
    vacancy = (
        "Повар\nТребования:\nОпыт работы поваром от 3 лет.\nКонтакты: Мария Иванова, hr@example.com"
    ).encode()
    resumes = [
        fixture_file("resume_cook.txt"),
        (
            "Пётр Сидоров\nОпыт работы\n2020 — 2024 кондитер, рекомендатель Анна Белова.".encode(),
            "r.txt",
        ),
    ]
    for resume in resumes:
        pipeline.run(resume, [(vacancy, "v.txt")], settings=llm_settings, llm=llm, save=False)
    extraction = [c for c in fake.calls if "Разбери вакансию" in c["messages"][1]["content"]]
    assert len(extraction) == 1
