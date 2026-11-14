"""D58: реестр открытых вакансий и вакансия по ссылке."""

import time

import pytest
from fastapi.testclient import TestClient

from aihr.api.app import app
from aihr.config import get_settings
from aihr.ingest import web
from aihr.ingest.web import UrlImportError, page_to_text, safe_filename
from aihr.vacancies import add_vacancy, list_vacancies, registry_files, remove_vacancy
from tests.conftest import fixture_file

HH_PAGE = """<html><head><title>Вакансия — сайт</title></head><body>
<header>Меню сайта</header>
<h1 data-qa="vacancy-title">Технолог пищевого производства</h1>
<p data-qa="vacancy-experience">1–3 года</p>
<div data-qa="vacancy-description">
<p><strong>Обязанности:</strong></p><ul><li>Разработка технологических карт</li>
<li>Контроль закладки сырья</li></ul>
<p><strong>Требования:</strong></p><ul><li>Высшее профильное образование</li>
<li>Опыт работы технологом от 1 года</li></ul>
</div>
<span data-qa="skills-element">ХАССП</span><span data-qa="skills-element">ГОСТ</span>
<footer>Подвал</footer></body></html>"""

PLAIN_PAGE = """<html><head><title>Работа у нас</title><script>var x = 1;</script></head><body>
<nav>Главная · Новости</nav><main><h1>Инженер-сметчик</h1>
<p>Отдел капитального строительства ищет инженера-сметчика.<br>Полная занятость.</p>
<h2>Что нужно уметь</h2><ul><li>Составлять локальные сметы</li><li>Работать в Гранд-Смете</li></ul>
</main><footer>© Организация</footer></body></html>"""


@pytest.fixture
def no_seed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VACANCIES_SEED", "0")
    get_settings.cache_clear()


def test_registry_is_seeded_from_example_once() -> None:
    first = list_vacancies()
    assert first and all(v.source == "example" for v in first)
    assert remove_vacancy(first[0].id)
    assert len(list_vacancies()) == len(first) - 1  # удалённое не возвращается при перечитывании


@pytest.mark.usefixtures("no_seed")
def test_add_list_remove_and_files_keep_original_names() -> None:
    data, name = fixture_file("vacancy_cook.txt")
    item = add_vacancy(data, name)
    assert item.title and item.filename == name
    assert [v.id for v in list_vacancies()] == [item.id]
    assert registry_files() == [(data, name)]
    assert remove_vacancy(item.id) and list_vacancies() == [] and registry_files() == []
    assert not remove_vacancy(item.id)


@pytest.mark.usefixtures("no_seed")
def test_broken_or_unsupported_file_is_rejected_with_message() -> None:
    with pytest.raises(ValueError, match="DOCX, PDF"):
        add_vacancy(b"x" * 100, "vacancy.xlsx")
    with pytest.raises(ValueError):
        add_vacancy(b"", "empty.txt")
    assert list_vacancies() == []


def test_hh_page_keeps_title_experience_lists_and_skills() -> None:
    title, text = page_to_text(HH_PAGE.encode("utf-8"))
    assert title == "Технолог пищевого производства"
    lines = text.split("\n")
    assert lines[0] == title
    assert "Требуемый опыт работы: 1–3 года" in lines
    assert "- Контроль закладки сырья" in lines and "- Опыт работы технологом от 1 года" in lines
    assert lines[-2:] == ["- ХАССП", "- ГОСТ"]
    assert "Меню сайта" not in text and "Подвал" not in text


def test_plain_page_drops_navigation_and_scripts() -> None:
    title, text = page_to_text(PLAIN_PAGE.encode("utf-8"))
    assert title == "Инженер-сметчик"
    assert "Полная занятость." in text.split("\n")  # <br> разделяет строки
    assert "- Работать в Гранд-Смете" in text
    assert "var x" not in text and "Главная" not in text and "©" not in text


def test_safe_filename() -> None:
    assert safe_filename('Логист / экспедитор: "срочно"') == "Логист экспедитор срочно.txt"
    assert safe_filename("  ") == "вакансия.txt"


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.org/v",
        "http://127.0.0.1/v",
        "http://localhost:8000/health",
        "http://10.0.0.5/",
    ],
)
def test_internal_and_non_http_urls_are_refused(url: str) -> None:
    with pytest.raises(UrlImportError):
        web.fetch_page(url)


def test_api_registry_flow(no_seed: None, monkeypatch: pytest.MonkeyPatch) -> None:
    client = TestClient(app)
    assert client.get("/vacancies").json() == []
    empty = client.post("/jobs/match/registry", files=[("resume", ("r.txt", b"x"))])
    assert empty.status_code == 404

    data, name = fixture_file("vacancy_cook.txt")
    r = client.post("/vacancies", files=[("files", (name, data)), ("files", ("bad.xlsx", b"x"))])
    body = r.json()
    assert r.status_code == 200 and len(body["added"]) == 1
    assert body["errors"][0].startswith("bad.xlsx")

    page = HH_PAGE.replace("Контроль", "Контроль " + "качества и выхода продукции " * 5)
    monkeypatch.setattr(web, "fetch_page", lambda url: (page.encode("utf-8"), url))
    r = client.post("/vacancies/url", json={"url": "https://example.org/vacancy/1"})
    assert r.status_code == 200 and r.json()["source"] == "url"
    assert r.json()["filename"] == "Технолог пищевого производства.txt"
    again = client.post("/vacancies/url", json={"url": "https://example.org/vacancy/1"})
    assert again.status_code == 422 and "уже есть" in again.json()["detail"]

    resume, rname = fixture_file("resume_cook.txt")
    job = client.post("/jobs/match/registry", files=[("resume", (rname, resume))]).json()
    deadline = time.monotonic() + 120
    while job["status"] not in ("done", "failed") and time.monotonic() < deadline:
        time.sleep(0.2)
        job = client.get(f"/jobs/{job['job_id']}").json()
    assert job["status"] == "done"
    result = client.get(f"/runs/{job['run_id']}").json()
    assert len(result["vacancies"]) == 2

    vid = client.get("/vacancies").json()[0]["id"]
    assert client.delete(f"/vacancies/{vid}").status_code == 204
    assert client.delete(f"/vacancies/{vid}").status_code == 404
    assert client.delete("/vacancies/..%2Fx").status_code == 404
