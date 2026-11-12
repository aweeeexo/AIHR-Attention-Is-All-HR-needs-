"""T02: маскирование ПДн, склонения, guard, журнал исходящих, главный тест на резюме кейса."""

import json
import logging
import re
from pathlib import Path

import pytest

from aihr.contracts import DocKind, PrivacyViolation
from aihr.ingest import load_document
from aihr.llm import LLMClient
from aihr.llm.prompting import document
from aihr.privacy import (
    PrivacyContext,
    check_outbound,
    mask_document,
    mask_text,
    names,
    patterns,
    unmask,
)
from aihr.privacy.outbound import OutboundLog
from tests.conftest import CASE_DIR, EchoRequirementsLLM, FakeOpenAI
from tests.test_llm_client import Ping

SYNTHETIC = """Петрова Анна Сергеевна
Женщина, 34 года, родилась 12 мая 1991 г.
Телефон: +7 (916) 123-45-67, 8 916 765 43 21
E-mail: anna.petrova@example.com, Telegram: @anna_petrova91
Проживает: Москва, ул. Ленина, д. 5, кв. 12
Гражданство: Россия, замужем, есть дети
Паспорт 45 12 345678, СНИЛС 123-456-789 01, ИНН 772812345678
Портфолио: https://github.com/annapetrova, vk.com/anna.petrova
Опыт работы
2016 — 2024, ООО «Ромашка», медицинская сестра процедурного кабинета.
Руководитель: Сидоров Олег Иванович, отзыв можно запросить.
Образование
2016, Первый МГМУ им. Сеченова, сестринское дело.
Навыки: забор крови, внутривенные инъекции, МИС «Инфоклиника».
Рекомендации готова предоставить, обращайтесь к Петровой А. С. по почте.
"""

ORIGINAL_PII = [
    "Петрова", "Анна", "Сергеевна", "Петровой", "34 года", "12 мая 1991", "+7 (916) 123-45-67",
    "8 916 765 43 21", "anna.petrova@example.com", "@anna_petrova91", "ул. Ленина", "кв. 12",
    "Гражданство", "замужем", "45 12 345678", "123-456-789 01", "772812345678",
    "github.com/annapetrova", "vk.com/anna.petrova", "Сидоров Олег",
]  # fmt: skip
KEPT = ["ООО «Ромашка»", "Первый МГМУ им. Сеченова", "2016 — 2024", "забор крови", "Инфоклиника"]


def _masked(text: str, filename: str = "Петрова Анна_резюме.txt") -> tuple[str, PrivacyContext]:
    doc = load_document(text.encode(), filename, DocKind.resume, "R")
    ctx = PrivacyContext()
    masked = mask_document(doc, ctx)
    return "\n".join(f.masked_text for f in masked.fragments), ctx


def test_synthetic_resume_all_pii_masked() -> None:
    masked, ctx = _masked(SYNTHETIC)
    leaked = [v for v in ORIGINAL_PII if v.lower() in masked.lower()]
    assert not leaked, leaked
    for token in ("[CANDIDATE]", "[PHONE_1]", "[PHONE_2]", "[EMAIL_1]", "[URL_1]", "[ID_DOC]",
                  "[BIRTHDATE]", "[ADDRESS]", "[PERSON_1]"):  # fmt: skip
        assert token in masked, token
    check_outbound(masked, ctx, "test")  # guard пропускает замаскированный текст


def test_meaning_preserved() -> None:
    masked, _ = _masked(SYNTHETIC)
    for value in KEPT:
        assert value in masked, value
    assert "Опыт работы" in masked and "Образование" in masked


@pytest.mark.parametrize(
    "line", ["Петрова Анна", "Петровой Анны", "Петровой А.", "ПЕТРОВА АННА", "Анной Петровой"]
)
def test_name_inflections(line: str) -> None:
    ctx = PrivacyContext()
    ctx.add_names(["Петрова", "Анна"])
    masked = mask_text(f"Отзыв для {line} готов", ctx)
    assert "Петров" not in masked and "ПЕТРОВ" not in masked and "Анн" not in masked
    assert "[CANDIDATE]" in masked


def test_name_pattern_is_case_sensitive() -> None:
    ctx = PrivacyContext()
    ctx.add_names(["Роман"])
    assert mask_text("Роман прочитал роман", ctx) == "[CANDIDATE] прочитал роман"


def test_names_from_filename_skip_non_names() -> None:
    assert names.names_from_filename("Иванов Алексей_резюме 1.docx") == ["Иванов", "Алексей"]
    assert names.names_from_filename("Менеджер по продажам.docx") == []
    assert names.names_from_filename("resume_final_v2.pdf") == []


@pytest.mark.parametrize(
    "text",
    ["Зарплата 150 000 – 200 000 руб.", "01.03.2019 – 30.06.2024", "2015 — 2020, 5 лет",
     "ИНН организации не указан", "Опыт 3+ года, команда 12 человек"],
)  # fmt: skip
def test_no_false_positives(text: str) -> None:
    assert mask_text(text, PrivacyContext()) == text
    check_outbound(text, None, "test")


def test_vacancy_masks_recruiter_keeps_company_and_city() -> None:
    text = (
        "Повар горячего цеха\nТребования: опыт от 3 лет.\nУсловия: ресторан «Север», Казань.\n"
        "Контакты: Мария Иванова, hr@sever.example, +7 900 000-00-00"
    )
    doc = load_document(text.encode(), "v.txt", DocKind.vacancy, "V1")
    masked = "\n".join(f.masked_text for f in mask_document(doc, PrivacyContext()).fragments)
    assert "hr@sever.example" not in masked and "+7 900" not in masked
    assert "Мария Иванова" not in masked and "[PERSON_1]" in masked
    assert "ресторан «Север», Казань" in masked


def test_unmask_roundtrip() -> None:
    ctx = PrivacyContext()
    masked = mask_text("Пишите на ivan@example.com или звоните +7 900 111-22-33", ctx)
    assert unmask(masked, ctx) == "Пишите на ivan@example.com или звоните +7 900 111-22-33"


def test_context_repr_and_logs_have_no_pii(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    masked, ctx = _masked(SYNTHETIC)
    assert "Петров" not in repr(ctx)
    with pytest.raises(PrivacyViolation) as exc:
        check_outbound(masked + " anna.petrova@example.com", ctx, "llm/ping")
    assert "anna" not in str(exc.value)
    assert "Петров" not in caplog.text and "anna.petrova" not in caplog.text


# ---------- guard в LLM-клиенте и журнал исходящих ----------


def test_guard_blocks_before_sending(llm_settings, tmp_path: Path) -> None:
    fake = FakeOpenAI(['{"ok": true, "word": "x"}'])
    log = OutboundLog(tmp_path / "outbound.jsonl")
    llm = LLMClient(llm_settings, client=fake).for_run(PrivacyContext(), log)
    with pytest.raises(PrivacyViolation, match="email"):
        llm.structured("llm/ping", {"word": "пишите на boss@example.com"}, Ping)
    assert fake.completions.calls == []  # запрос не ушёл
    entry = json.loads(log.path.read_text(encoding="utf-8"))
    assert entry["status"] == "blocked" and "messages" not in entry
    assert "boss@example.com" not in log.path.read_text(encoding="utf-8")


def test_guard_blocks_candidate_name(llm_settings) -> None:
    ctx = PrivacyContext()
    ctx.add_names(["Петрова"])
    llm = LLMClient(llm_settings, client=FakeOpenAI([])).for_run(ctx, None)
    with pytest.raises(PrivacyViolation, match="ФИО"):
        llm.structured("llm/ping", {"word": "Петровой"}, Ping)


def test_outbound_log_records_request(llm_settings, tmp_path: Path) -> None:
    fake = FakeOpenAI(['{"ok": true, "word": "сосна"}'])
    log = OutboundLog(tmp_path / "outbound.jsonl")
    llm = LLMClient(llm_settings, client=fake).for_run(PrivacyContext(), log)
    llm.structured("llm/ping", {"word": "сосна"}, Ping)
    entry = json.loads(log.path.read_text(encoding="utf-8").splitlines()[0])
    assert entry["prompt_id"] == "llm/ping" and entry["prompt_version"] == 1
    assert entry["status"] == "ok" and entry["model"] == "test-model"
    assert "сосна" in entry["messages"][1]["content"] and entry["response_chars"] > 0


def test_pipeline_guard_violation_falls_back_for_step(
    llm_settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aihr import pipeline
    from tests.conftest import fixture_file

    def leaky(doc, llm):
        raise PrivacyViolation("guard: найден email в промпте extract/x")

    monkeypatch.setattr(pipeline.extract, "extract_profile", leaky)
    llm = LLMClient(llm_settings, client=EchoRequirementsLLM())
    r = pipeline.run(fixture_file("resume_cook.txt"), [fixture_file("vacancy_cook.txt")],
                     settings=llm_settings, llm=llm)  # fmt: skip
    assert r.mode == "llm"  # заблокирован один шаг, а не весь прогон
    assert any("заблокирован проверкой ПДн" in w for w in r.warnings)
    assert r.profile is not None and r.ranking and r.ranking.items


# ---------- главный тест: резюме кейса ----------

CASE_RESUMES = sorted(p.name for p in CASE_DIR.glob("*резюме*.docx"))


@pytest.mark.parametrize("name", CASE_RESUMES)
def test_case_resume_outbound_has_no_pii(name: str) -> None:
    path = CASE_DIR / name
    doc = load_document(path.read_bytes(), name, DocKind.resume, "R")
    ctx = PrivacyContext()
    masked = mask_document(doc, ctx)
    prompt = document(masked.fragments)  # ровно то, что ушло бы в LLM
    original = "\n".join(f.text for f in doc.fragments)

    for word in names.names_from_filename(name):
        assert not names.name_pattern(word).search(prompt), "ФИО кандидата в промпте"
    for kind, pattern in patterns.GUARD_PATTERNS.items():
        for value in pattern.findall(original):
            assert value not in prompt, kind
    check_outbound(prompt, ctx, "case")
    assert "[CANDIDATE]" in prompt
    # смысл на месте: разделы и годы работы не тронуты
    assert "Опыт работы" in prompt
    assert re.search(r"20\d\d", prompt)
