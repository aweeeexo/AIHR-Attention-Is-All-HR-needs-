"""Проверка цитат (принципы 1, 2) и базовая формула балла (D4, D5)."""

import pytest

from aihr.contracts import (
    DocKind,
    Document,
    Evidence,
    FitLabel,
    Fragment,
    FragmentSource,
    Modality,
    ReqKind,
    Requirement,
    Status,
    Verdict,
)
from aihr.match.verify import attach_quotes
from aihr.score import plural, rank, score_vacancy

RESUME = Document(
    id="R",
    content_hash="0" * 12,
    kind=DocKind.resume,
    filename="r.txt",
    fragments=[
        Fragment(
            id=f"R{i}",
            order=i,
            section=None,
            section_role=None,
            source=FragmentSource.paragraph,
            text=f"фрагмент {i}",
        )
        for i in (1, 2)
    ],
)
VACANCY = RESUME.model_copy(update={"id": "V1", "kind": DocKind.vacancy, "title": "Повар"})


def _verdict(status: Status, *fids: str, rid: str = "V1.req1", **kw: object) -> Verdict:
    return Verdict(
        requirement_id=rid,
        status=status,
        evidence=[Evidence(fragment_id=f, quote="выдумано моделью") for f in fids],
        comment="",
        confidence=0.9,
        decided_by="pass_a",
        **kw,
    )


def _req(i: int, modality: Modality) -> Requirement:
    return Requirement(
        id=f"V1.req{i}",
        vacancy_id="V1",
        text=f"требование {i}",
        kind=ReqKind.skill,
        modality=modality,
        modality_marker=None,
        modality_reason="",
        source_fragment_ids=["V1.1"],
    )


# ---------- проверка цитат ----------


def test_quote_comes_from_document_not_model() -> None:
    v = attach_quotes(_verdict(Status.match, "R2"), RESUME)
    assert v.evidence == [Evidence(fragment_id="R2", quote="фрагмент 2")]
    assert v.status == Status.match


def test_unknown_fragment_dropped_and_status_downgraded() -> None:
    v = attach_quotes(_verdict(Status.mismatch, "R99", partial_value=0.5), RESUME)
    assert v.evidence == []
    assert v.status == Status.not_stated
    assert v.partial_value is None


def test_duplicates_removed_valid_kept() -> None:
    v = attach_quotes(_verdict(Status.partial, "R1", "R99", "R1"), RESUME)
    assert [e.fragment_id for e in v.evidence] == ["R1"]
    assert v.status == Status.partial


def test_not_stated_stays_not_stated() -> None:
    assert attach_quotes(_verdict(Status.not_stated), RESUME).status == Status.not_stated


# ---------- балл ----------


def test_score_formula_and_interval() -> None:
    reqs = [_req(1, Modality.must), _req(2, Modality.must), _req(3, Modality.nice)]
    verdicts = [
        _verdict(Status.match, "R1", rid="V1.req1"),
        _verdict(Status.not_stated, rid="V1.req2"),
        _verdict(Status.partial, "R2", rid="V1.req3"),
    ]
    s = score_vacancy(VACANCY, reqs, verdicts)
    # веса 3, 3, 1: (3·1 + 3·u + 1·0.5) / 7
    assert s.score == pytest.approx(round(100 * (3 + 1.5 + 0.5) / 7, 1))
    assert s.score_min == pytest.approx(round(100 * 3.5 / 7, 1))
    assert s.score_max == pytest.approx(round(100 * 6.5 / 7, 1))
    assert s.must.total == 2 and s.must.match == 1 and s.must.not_stated == 1
    assert s.nice.partial == 1
    assert s.top_plus[0] in {"V1.req1"}
    assert "от 50 до 92.9" in s.explanation


def test_partial_value_overrides_default() -> None:
    reqs = [_req(1, Modality.must)]
    s = score_vacancy(VACANCY, reqs, [_verdict(Status.partial, "R1", partial_value=0.25)])
    assert s.score == 25.0


def test_blocking_gap_prevents_fits_but_keeps_score() -> None:
    reqs = [_req(i, Modality.must) for i in range(1, 6)]
    verdicts = [_verdict(Status.match, "R1", rid=f"V1.req{i}") for i in range(1, 5)]
    verdicts.append(_verdict(Status.mismatch, "R2", rid="V1.req5"))
    s = score_vacancy(VACANCY, reqs, verdicts)
    assert s.score == 80.0
    assert s.blocking_gaps == ["V1.req5"]
    assert s.label == FitLabel.fits_with_caveats  # D4: нокаута нет, но и «подходит» нет


def test_missing_verdict_counts_as_not_stated() -> None:
    s = score_vacancy(VACANCY, [_req(1, Modality.nice)], [])
    assert s.nice.not_stated == 1 and s.score == 50.0


def test_rank_orders_by_score() -> None:
    low = score_vacancy(VACANCY, [_req(1, Modality.must)], [_verdict(Status.mismatch, "R1")])
    high_doc = VACANCY.model_copy(update={"id": "V2"})
    high = score_vacancy(high_doc, [_req(1, Modality.must)], [_verdict(Status.match, "R1")])
    r = rank([low, high])
    assert [s.vacancy_id for s in r.items] == ["V2", "V1"]
    assert r.best_vacancy_id == "V2"
    assert r.comparison[0].startswith("V2 выше V1 на 100 пунктов")
    assert "обязательное требование 3" in r.formula


@pytest.mark.parametrize(
    ("n", "word"), [(1, "пункт"), (3, "пункта"), (5, "пунктов"), (11, "пунктов"), (21, "пункт")]
)
def test_plural(n: int, word: str) -> None:
    assert plural(n, ("пункт", "пункта", "пунктов")) == word


# ---------- T08: крайние случаи и объяснения ----------


def test_manual_calculation_small_example() -> None:
    reqs = [
        _req(1, Modality.must),
        _req(2, Modality.must),
        _req(3, Modality.nice),
        _req(4, Modality.nice),
    ]
    verdicts = [
        _verdict(Status.match, "R1", rid="V1.req1"),
        _verdict(Status.partial, "R1", rid="V1.req2", partial_value=0.25),
        _verdict(Status.mismatch, "R2", rid="V1.req3"),
        _verdict(Status.not_stated, rid="V1.req4"),
    ]
    s = score_vacancy(VACANCY, reqs, verdicts)
    # (3·1 + 3·0.25 + 1·0 + 1·0.5) / 8 = 4.25 / 8
    assert s.score == round(100 * 4.25 / 8, 1)
    assert (s.score_min, s.score_max) == (round(100 * 3.75 / 8, 1), round(100 * 4.75 / 8, 1))
    assert s.top_plus[:2] == ["V1.req1", "V1.req2"]
    assert s.top_minus[0] == "V1.req2"  # потеря 3 · 0.75 — самая большая
    assert "«требование 1»" in s.explanation and "частично — 1" in s.explanation


def test_no_unknown_means_no_interval() -> None:
    reqs = [_req(1, Modality.must), _req(2, Modality.nice)]
    verdicts = [
        _verdict(Status.match, "R1", rid="V1.req1"),
        _verdict(Status.mismatch, "R2", rid="V1.req2"),
    ]
    s = score_vacancy(VACANCY, reqs, verdicts)
    assert s.score_min == s.score == s.score_max == 75.0
    assert "Не указано" not in s.explanation


def test_must_mismatch_never_fits() -> None:
    reqs = [_req(i, Modality.must) for i in range(1, 21)]
    verdicts = [_verdict(Status.match, "R1", rid=f"V1.req{i}") for i in range(1, 20)]
    verdicts.append(_verdict(Status.mismatch, "R2", rid="V1.req20"))
    s = score_vacancy(VACANCY, reqs, verdicts)
    assert s.score == 95.0 and s.label != FitLabel.fits
    assert "решает рекрутер" in s.explanation


def test_empty_resume_scores_fifty() -> None:
    reqs = [_req(1, Modality.must), _req(2, Modality.nice)]
    s = score_vacancy(
        VACANCY,
        reqs,
        [_verdict(Status.not_stated, rid="V1.req1"), _verdict(Status.not_stated, rid="V1.req2")],
    )
    assert (s.score, s.score_min, s.score_max) == (50.0, 0.0, 100.0)
    assert s.label == FitLabel.not_fit  # D41: без подтверждений — не «с оговорками»
    assert "мало данных" in s.explanation and "Мало данных: в резюме подтверждено 0 из 1" in (
        s.explanation
    )


def test_only_nice_requirements() -> None:
    s = score_vacancy(VACANCY, [_req(1, Modality.nice)], [_verdict(Status.match, "R1")])
    assert s.score == 100.0 and "нет обязательных требований" in s.explanation


def test_rank_tie_breaks_and_comparison_reason() -> None:
    a_doc = VACANCY.model_copy(update={"id": "V1"})
    b_doc = VACANCY.model_copy(update={"id": "V2"})
    reqs_a = [_req(1, Modality.must), _req(2, Modality.nice)]
    a = score_vacancy(
        a_doc,
        reqs_a,
        [
            _verdict(Status.match, "R1", rid="V1.req1"),
            _verdict(Status.mismatch, "R1", rid="V1.req2"),
        ],
    )
    b = score_vacancy(
        b_doc,
        reqs_a,
        [
            _verdict(Status.mismatch, "R1", rid="V1.req1"),
            _verdict(Status.match, "R1", rid="V1.req2"),
        ],
    )
    r = rank([b, a])
    assert [s.vacancy_id for s in r.items] == ["V1", "V2"]
    assert "не подтверждены 1 из 1 обязательных" in r.comparison[0]


def test_score_has_no_case_specific_logic() -> None:
    import inspect

    import aihr.score as score_module

    source = inspect.getsource(score_module).lower()
    for word in ("вакансия 1", "вакансия 2", "вакансия 3", "v1.", "v2.", "v3."):
        assert word not in source
