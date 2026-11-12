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


@pytest.mark.parametrize(
    "name", sorted(p.name for p in (REPO_ROOT / "data" / "case").glob("*резюме*.docx"))
)
def test_case_resume_outbound_log_is_clean(live_llm: LLMClient, name: str, tmp_path) -> None:
    """Главный тест T02 вживую: замаскированное резюме кейса уходит в LLM, журнал без ПДн."""
    import re

    from aihr.privacy import patterns
    from aihr.privacy.names import name_pattern, names_from_filename
    from aihr.privacy.outbound import OutboundLog

    path = REPO_ROOT / "data" / "case" / name
    doc = load_document(path.read_bytes(), name, DocKind.resume, "R")
    ctx = PrivacyContext()
    masked = mask_document(doc, ctx)
    log = OutboundLog(tmp_path / "outbound.jsonl")
    llm = live_llm.for_run(ctx, log)
    result = llm.structured(
        "llm/selftest_fragments", {"fragments": masked.fragments[:40]}, FoundRequirements
    )
    sent = log.path.read_text(encoding="utf-8")
    for word in names_from_filename(name):
        assert not name_pattern(word).search(sent), "ФИО в журнале исходящих"
    for kind, pattern in patterns.GUARD_PATTERNS.items():
        assert not pattern.search(sent), kind
    assert "[CANDIDATE]" in sent
    known = {f.id for f in masked.fragments}
    assert {fid for i in result.items for fid in i.fragment_ids} <= known
    print(f"\n{name[-14:]}: {len(result.items)} пунктов, журнал {len(sent)} символов, ФИО нет")
    assert re.search(r'"status": "ok"', sent)


def test_requirements_against_golden(live_llm: LLMClient) -> None:
    """T04: полнота и модальность ≥ 90% против ручного эталона на вакансиях кейса."""
    import json
    import sys

    sys.path.insert(0, str(REPO_ROOT / "eval"))
    from requirements_eval import evaluate

    from aihr.extract import extract_requirements

    golden_dir = REPO_ROOT / "eval" / "golden"
    total = matched = modality_ok = 0
    for path in sorted(golden_dir.glob("requirements_V*.json")):
        golden = json.loads(path.read_text(encoding="utf-8"))
        file = REPO_ROOT / "data" / "case" / golden["vacancy_file"]
        vid = path.stem.split("_")[-1]
        doc = mask_document(
            load_document(file.read_bytes(), file.name, DocKind.vacancy, vid), PrivacyContext()
        )
        score = evaluate(golden, extract_requirements(doc, live_llm))
        total, matched, modality_ok = (
            total + score.golden,
            matched + score.matched,
            modality_ok + score.modality_ok,
        )
        assert not [w for w in doc.warnings if "не извлечено" in w], doc.warnings
    assert matched / total >= 0.9
    assert modality_ok / matched >= 0.9
