"""Принцип 4 (D10): единственная точка выхода к LLM — src/aihr/llm/client.py."""

import re

from tests.conftest import REPO_ROOT

SRC = REPO_ROOT / "src" / "aihr"
NETWORK = re.compile(
    r"^\s*(?:import|from)\s+(?:openai|httpx2?|requests|urllib\.request|aiohttp|http\.client)\b"
    r"|\b(?:httpx2?|requests)\.(?:get|post|put|request|Client|AsyncClient)\b",
    re.MULTILINE,
)


# D58: загрузка страницы вакансии по ссылке. Не LLM и не резюме: только GET страницы по адресу,
# который ввёл рекрутер. Модуль не должен знать про LLM и не получает текст резюме.
PAGE_FETCH = ("ingest/web.py",)


def test_page_fetch_does_not_touch_llm_or_resume() -> None:
    for rel in PAGE_FETCH:
        text = (SRC / rel).read_text(encoding="utf-8")
        assert not re.search(r"\b(?:openai|aihr\.llm|aihr\.privacy|DocKind\.resume)\b", text), rel
        assert 'client.stream("GET"' in text and ".post(" not in text, rel


def test_only_llm_client_talks_to_network() -> None:
    offenders = []
    for path in SRC.rglob("*.py"):
        rel = path.relative_to(SRC).as_posix()
        if rel in ("llm/client.py", *PAGE_FETCH):
            continue
        if NETWORK.search(path.read_text(encoding="utf-8")):
            offenders.append(rel)
    assert not offenders, offenders
