"""Живые проверки провайдера LLM: `uv run pytest -m llm -s`. По умолчанию выключены.

Берут настройки из .env в корне репозитория. В модель уходят только выдуманные документы из
tests/fixtures (резюме кейса — только после маскирования, T02).
"""

from __future__ import annotations

import time

import pytest
from pydantic import BaseModel, Field

from aihr.config import Settings
from aihr.contracts import DocKind
from aihr.ingest import load_document
from aihr.llm import LLMClient
from aihr.privacy import PrivacyContext, mask_document
from tests.conftest import REPO_ROOT, fixture_file

pytestmark = pytest.mark.llm


class Ping(BaseModel):
    ok: bool
    word: str


class FoundRequirement(BaseModel):
    text: str
    fragment_ids: list[str] = Field(min_length=1)


class FoundRequirements(BaseModel):
    items: list[FoundRequirement]


@pytest.fixture
def live_llm() -> LLMClient:
    settings = Settings(_env_file=REPO_ROOT / ".env")  # type: ignore[call-arg]
    if not settings.llm_configured:
        pytest.skip("LLM не настроена в .env")
    return LLMClient(settings)


def test_ping(live_llm: LLMClient) -> None:
    started = time.perf_counter()
    result = live_llm.structured("llm/ping", {"word": "сосна"}, Ping)
    print(f"\nping: {result!r} за {time.perf_counter() - started:.1f} с")
    assert result.ok and result.word.strip().lower() == "сосна"


@pytest.mark.parametrize("name", ["vacancy_cook.txt", "vacancy_welder.txt"])
def test_fragment_ids_are_real(live_llm: LLMClient, name: str) -> None:
    data, filename = fixture_file(name)
    doc = mask_document(load_document(data, filename, DocKind.vacancy, "V1"), PrivacyContext())
    started = time.perf_counter()
    result = live_llm.structured(
        "llm/selftest_fragments", {"fragments": doc.fragments}, FoundRequirements
    )
    elapsed = time.perf_counter() - started
    known = {f.id for f in doc.fragments}
    used = [fid for item in result.items for fid in item.fragment_ids]
    print(f"\n{name}: {len(result.items)} требований за {elapsed:.1f} с")
    for item in result.items:
        print(f"  {item.fragment_ids} {item.text}")
    assert result.items
    assert set(used) <= known, f"выдуманные номера: {set(used) - known}"
