"""UI (T12): чистые функции отрисовки и сквозной сценарий через AppTest без сети."""

import importlib.util
import sys
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from aihr.api.app import app as api_app
from tests.conftest import REPO_ROOT

UI_PATH = REPO_ROOT / "ui" / "app.py"
_spec = importlib.util.spec_from_file_location("aihr_ui", UI_PATH)
assert _spec and _spec.loader
ui = importlib.util.module_from_spec(_spec)
sys.modules["aihr_ui"] = ui
_spec.loader.exec_module(ui)


def test_months_text() -> None:
    assert ui.months_text(39) == "3 г. 3 мес."
    assert ui.months_text(24) == "2 г."
    assert ui.months_text(None) == "не указано"


def test_resume_html_escapes_and_highlights() -> None:
    resume = {
        "fragments": [
            {"id": "R1", "section": "Опыт работы", "text": "<script>alert(1)</script>"},
            {"id": "R2", "section": "Опыт работы", "text": "Повар & кондитер"},
        ]
    }
    out = ui.resume_html(resume, {"R2"})
    assert "<script>" not in out and "&lt;script&gt;" in out
    assert "<mark" in out and "Повар &amp; кондитер</mark>" in out
    assert out.count("Опыт работы") == 1  # заголовок раздела один раз


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch, tmp_path) -> TestClient:
    """UI ходит в API через httpx — подменяем на TestClient того же приложения."""
    monkeypatch.setenv("LLM_PROVIDER", "none")
    from aihr.config import get_settings

    get_settings.cache_clear()
    client = TestClient(api_app)
    base = ui.API_URL

    def fake_get(url: str, **kw: Any) -> Any:
        return client.get(url.removeprefix(base), params=kw.get("params"))

    def fake_post(url: str, **kw: Any) -> Any:
        kw.pop("timeout", None)
        return client.post(url.removeprefix(base), **kw)

    monkeypatch.setattr(httpx, "get", fake_get)
    monkeypatch.setattr(httpx, "post", fake_post)
    return client


def test_ui_example_flow(api: TestClient) -> None:
    at = AppTest.from_file(str(UI_PATH), default_timeout=120).run()
    assert not at.exception
    assert "LLM: не настроена" in at.caption[0].value
    at = next(b for b in at.button if b.label == "Пример из кейса").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert [s.value for s in at.subheader] == ["Рейтинг вакансий", "Вакансия подробно"]
    assert sum(m.label == "Балл" for m in at.metric) == 3
    assert [t.label for t in at.tabs] == [
        "Требования",
        "Профиль кандидата",
        "Требования вакансии",
        "Отчёт",
        "Что если",
    ]
    assert any("упрощённый режим" in w.value for w in at.warning)
    radio = at.radio[1]  # [0] — режим «одно резюме / пакет»
    at = radio.set_value("V3").run()
    assert not at.exception


def test_ui_pasted_text_flow(api: TestClient) -> None:
    at = AppTest.from_file(str(UI_PATH), default_timeout=120).run()
    at.text_area[0].input("Опыт работы\n2019 — 2024 повар горячего цеха.\nНавыки: пароконвектомат")
    at.text_area[1].input(
        "Повар\nТребования:\nОпыт работы поваром от 3 лет.\nРабота с пароконвектоматом."
    )
    at = at.run()  # кнопка становится активной после ввода, как у пользователя
    at = next(b for b in at.button if b.label == "Сопоставить").click().run()
    assert not at.exception, [e.value for e in at.exception]
    scores = [m.value for m in at.metric if m.label == "Балл"]
    assert scores == ["100"]


def test_batch_matrix_and_retrieval_text() -> None:
    batch = {
        "resumes": [
            {"resume_id": "C1", "filename": "a.txt"},
            {"resume_id": "C2", "filename": "b.txt"},
        ],
        "vacancies": [{"vacancy_id": "V1", "filename": "v.txt", "title": "Повар"}],
        "cells": [{"resume_id": "C1", "vacancy_id": "V1", "score": 80.0, "label": "fits"}],
    }
    values, labels = ui.batch_matrix(batch)
    assert values.loc["C1 · a.txt", "V1 · Повар"] == "80 · подходит"
    assert values.loc["C2 · b.txt", "V1 · Повар"] == "—" and labels.loc["C2 · b.txt"].iloc[0] == ""
    assert ui.retrieval_text({"retrieval": "bm25+embeddings"}).endswith("BM25 + эмбеддинги")
    assert ui.retrieval_text({}) == ""


def test_ui_batch_example_flow(api: TestClient) -> None:
    at = AppTest.from_file(str(UI_PATH), default_timeout=300).run()
    at = at.radio[0].set_value("Пакет резюме").run()
    at = next(b for b in at.button if b.label == "Пакет из кейса").click().run()
    assert not at.exception, [e.value for e in at.exception]
    subheaders = [s.value for s in at.subheader]
    assert subheaders[:3] == [
        "Кандидаты × вакансии",
        "Лучшие кандидаты по вакансиям",
        "Кандидат подробно",
    ]
    assert "Рейтинг вакансий" in subheaders  # отчёт выбранного кандидата из пакета
    assert len(at.dataframe) >= 1
    at = at.selectbox[0].set_value("C2").run()
    assert not at.exception


def test_what_if_text() -> None:
    change = {"score_before": 52.5, "score_after": 78.0, "interval_after": [70.0, 86.0],
              "label_before": "not_fit", "label_after": "fits", "place_before": 2,
              "place_after": 1}  # fmt: skip
    text = ui.what_if_text(change)
    assert "52.5 → **78**" in text and "место 2 → 1" in text and "подходит**" in text


def test_ui_what_if_flow(api: TestClient) -> None:
    at = AppTest.from_file(str(UI_PATH), default_timeout=120).run()
    at = next(b for b in at.button if b.label == "Пример из кейса").click().run()
    boxes = [s for s in at.selectbox if s.label.endswith("сейчас «Не указано»")]
    assert boxes, "нет требований «Не указано» для «что если»"
    at = boxes[0].set_value("Соответствует").run()
    at = next(b for b in at.button if b.label == "Пересчитать").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("Балл" in s.value and "→" in s.value for s in at.success)
