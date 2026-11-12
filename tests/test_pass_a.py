"""T07, шаги 1–3: проход A — промпт и шлюз кода над ответом модели (заглушка LLM)."""

import json

import pytest

from aihr.config import Settings
from aihr.contracts import (
    CandidateProfile,
    DocKind,
    EvidenceType,
    Modality,
    Position,
    ReqKind,
    Requirement,
    Status,
    Threshold,
    ThresholdKind,
    YearMonth,
)
from aihr.ingest import load_document
from aihr.llm import LLMClient
from aihr.match import apply_rules
from aihr.match.pass_a import pass_a
from aihr.normalize import enrich_profile, find_terms
from aihr.privacy import PrivacyContext, mask_document
from tests.conftest import FakeOpenAI

RESUME = """Опыт работы
2021 — 2023, ООО «Пример», логист. Составлял маршруты доставки, работал в SAP.
2016 — 2021, водитель грузового автомобиля.
Образование
Колледж, логистика.
Навыки: Автокад.
"""


@pytest.fixture
def resume():
    doc = load_document(RESUME.encode(), "r.txt", DocKind.resume, "R")
    return mask_document(doc, PrivacyContext())


@pytest.fixture
def profile(resume) -> CandidateProfile:
    f = {x.text[:12]: x.id for x in resume.fragments}
    positions = [
        Position(
            title="логист",
            organization="ООО «Пример»",
            start=None,
            end=None,
            raw_dates="2021 — 2023",
            fragment_ids=[f["2021 — 2023,"]],
        ),
        Position(
            title="водитель",
            organization=None,
            start=None,
            end=None,
            raw_dates="2016 — 2021",
            fragment_ids=[f["2016 — 2021,"]],
        ),
    ]
    return enrich_profile(CandidateProfile(positions=positions), YearMonth(year=2026, month=11))


def _req(
    i: int,
    text: str,
    kind: ReqKind = ReqKind.skill,
    modality: Modality = Modality.must,
    threshold: Threshold | None = None,
) -> Requirement:
    return Requirement(
        id=f"V1.req{i}",
        vacancy_id="V1",
        text=text,
        kind=kind,
        modality=modality,
        modality_marker=None,
        modality_reason="",
        threshold=threshold,
        canonical_terms=find_terms(text),
        source_fragment_ids=["V1.2"],
    )


def _v(rid: str, status: str, ids: list[str], **kw) -> dict:
    return {
        "requirement_id": rid,
        "reasoning": "…",
        "status": status,
        "fragment_ids": ids,
        "comment": kw.pop("comment", "комментарий"),
        **kw,
    }


def _run(reqs, profile, resume, verdicts):
    fake = FakeOpenAI([json.dumps({"verdicts": verdicts}, ensure_ascii=False)])
    s = Settings(_env_file=None, llm_base_url="http://x/v1", llm_model="m")  # type: ignore[call-arg]
    out = pass_a(reqs, profile, resume, LLMClient(s, client=fake))
    return {v.requirement_id: v for v in out}, fake


def test_gate(resume, profile) -> None:
    f = {x.text[:12]: x.id for x in resume.fragments}
    reqs = [
        _req(1, "Знание SAP"),
        _req(2, "Высшее образование", ReqKind.education),
        _req(3, "Работа в КОМПАС-3D"),
        _req(4, "Права категории C", ReqKind.certificate),
        _req(5, "Знание 1С"),
        _req(6, "Английский B2", ReqKind.language),
        _req(7, "Знание Oracle"),
        _req(8, "Опыт с холодовой цепью", modality=Modality.nice),
    ]
    reqs_text = {r.id: r for r in reqs}
    answer = [
        _v("V1.req1", "match", [f["2021 — 2023,"]], evidence_type="direct", comment="x" * 400),
        _v("V1.req2", "mismatch", [f["Колледж, лог"]], evidence_type="direct"),
        _v("V1.req3", "match", [f["Навыки: Авто"]], evidence_type="adjacent"),
        _v(
            "V1.req4",
            "match",
            [f["2016 — 2021,"]],
            evidence_type="indirect",
            inference=f"[{f['2016 — 2021,']}] водил грузовик → есть категория C",
        ),
        _v(
            "V1.req5",
            "match",
            [f["2021 — 2023,"]],
            evidence_type="indirect",
            inference="логисты знают 1С",
        ),
        _v("V1.req6", "mismatch", ["R999"], evidence_type="direct"),
        _v("V9.req1", "match", [f["2021 — 2023,"]]),  # чужое требование
        # V1.req7 — модель промолчала
        _v("V1.req8", "not_stated", []),
    ]
    out, fake = _run(reqs, profile, resume, answer)

    sap = out["V1.req1"]
    assert sap.status == Status.match and sap.decided_by == "pass_a"
    assert sap.evidence[0].quote.startswith("2021 — 2023, ООО «Пример», логист")  # цитата из текста
    assert len(sap.comment) == 250

    assert out["V1.req2"].status == Status.mismatch  # факт против требования есть
    assert out["V1.req3"].status == Status.partial  # adjacent — не выше «Частично»

    trucks = out["V1.req4"]
    assert trucks.status == Status.match and trucks.evidence_type == EvidenceType.indirect
    assert trucks.inference and trucks.needs_review  # обязательное по косвенному — посмотреть

    assert out["V1.req5"].status == Status.not_stated and out["V1.req5"].needs_review  # цепочки нет
    assert (
        out["V1.req6"].status == Status.not_stated and not out["V1.req6"].evidence
    )  # нет фрагмента
    assert out["V1.req7"].status == Status.not_stated and out["V1.req7"].needs_review  # промолчала
    assert set(out) == set(reqs_text)

    user = fake.completions.calls[0]["messages"][1]["content"]
    assert "[V1.req4] (обязательное, сертификат) Права категории C" in user
    assert "логист, ООО «Пример»: 2021 — 2023 = ≈ 2 г." in user  # стаж посчитан кодом
    assert "one_c: " in user and "1с" in user  # синонимы словаря у требования
    assert "{Опыт работы}" in user and "<document>" in user


def test_rules_override_years_after_pass_a(resume, profile) -> None:
    f = {x.text[:12]: x.id for x in resume.fragments}
    req = _req(
        1,
        "Опыт работы логистом от 3 лет",
        ReqKind.experience,
        threshold=Threshold(kind=ThresholdKind.years, value="3", subject="логистика"),
    )
    out, _ = _run(
        [req],
        profile,
        resume,
        [_v("V1.req1", "match", [f["2021 — 2023,"]], evidence_type="direct")],
    )
    ruled = apply_rules(req, out["V1.req1"], profile)
    assert ruled.status == Status.partial and ruled.decided_by == "rule"  # модель сказала match
    assert "≈ 2 г. < 3 лет" in (ruled.computed or "")


def test_batches_long_vacancy(resume, profile) -> None:
    from aihr.match.pass_a import BATCH

    n = BATCH * 2 + 5
    reqs = [_req(i, f"Навык номер {i}") for i in range(1, n + 1)]
    chunks = [range(1, BATCH + 1), range(BATCH + 1, 2 * BATCH + 1), range(2 * BATCH + 1, n + 1)]
    replies = [
        json.dumps({"verdicts": [_v(f"V1.req{i}", "not_stated", []) for i in c]}) for c in chunks
    ]
    fake = FakeOpenAI(replies)
    s = Settings(_env_file=None, llm_base_url="http://x/v1", llm_model="m")  # type: ignore[call-arg]
    out = pass_a(reqs, profile, resume, LLMClient(s, client=fake))
    assert len(fake.completions.calls) == 3 and len(out) == n
    assert all(v.status == Status.not_stated for v in out)


def test_timeout_splits_batch(resume, profile) -> None:
    """Провайдер не успел с длинным ответом — пачка делится пополам, вердикты не теряются."""
    import httpx
    import openai

    reqs = [_req(i, f"Навык номер {i}") for i in range(1, 5)]
    timeout = openai.APITimeoutError(request=httpx.Request("POST", "http://x/v1"))
    halves = [
        json.dumps({"verdicts": [_v(f"V1.req{i}", "not_stated", []) for i in c]})
        for c in (range(1, 3), range(3, 5))
    ]
    fake = FakeOpenAI([timeout, *halves])
    s = Settings(_env_file=None, llm_base_url="http://x/v1", llm_model="m", llm_max_retries=0)  # type: ignore[call-arg]
    out = pass_a(reqs, profile, resume, LLMClient(s, client=fake))
    assert len(fake.completions.calls) == 3 and len(out) == 4
    assert all(v.comment != "Модель не дала вердикт по этому требованию." for v in out)


def test_no_requirements_no_call(resume, profile) -> None:
    out, fake = _run([], profile, resume, [])
    assert out == {} and fake.completions.calls == []


def test_soft_skill_by_adjacent_facts_is_not_stated(resume) -> None:
    """D43: «коммуникабельность» по смежным фактам не выводим — вопрос на интервью."""
    from aihr.contracts import ReqKind
    from aihr.match.pass_a import gate
    from aihr.match.schemas import PassAVerdict

    fid = resume.fragments[0].id
    req = _req(1, "Коммуникабельность").model_copy(update={"kind": ReqKind.soft})
    raw = PassAVerdict(
        requirement_id=req.id,
        reasoning="…",
        status=Status.partial,
        evidence_type="adjacent",
        fragment_ids=[fid],
        comment="согласовывал",
    )
    v = gate(req, raw, resume)
    assert v.status == Status.not_stated and v.evidence == [] and "интервью" in v.comment
    direct = raw.model_copy(update={"evidence_type": "direct", "status": Status.match})
    assert gate(req, direct, resume).status == Status.match


def test_missing_fragment_ids_triggers_fix(resume, profile) -> None:
    """Модель поставила «Соответствует» без номеров — получает ошибку схемы и дописывает их."""
    fid = resume.fragments[0].id
    req = _req(1, "Знание AutoCAD")
    bad = {"requirement_id": req.id, "reasoning": "…", "status": "match", "fragment_ids": [],
           "comment": "есть"}  # fmt: skip
    good = {**bad, "fragment_ids": [fid]}
    fake = FakeOpenAI([json.dumps({"verdicts": [bad]}), json.dumps({"verdicts": [good]})])
    s = Settings(_env_file=None, llm_base_url="http://x/v1", llm_model="m")  # type: ignore[call-arg]
    [v] = pass_a([req], profile, resume, LLMClient(s, client=fake))
    assert v.status == Status.match and v.evidence[0].fragment_id == fid
    retry = fake.completions.calls[1]["messages"][-1]["content"]
    assert "fragment_ids" in retry  # модели объяснили, что исправить
