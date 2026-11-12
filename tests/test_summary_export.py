"""D35: «прямо не подходит ни одна» и косвенные варианты; D36: вывод для менеджера; D37: DOCX."""

import io

import docx
import pytest
from fastapi.testclient import TestClient

from aihr.api.app import app
from aihr.config import get_settings
from aihr.contracts import (
    DocKind,
    Document,
    Evidence,
    EvidenceType,
    FitLabel,
    Fragment,
    FragmentSource,
    Modality,
    ReqKind,
    Requirement,
    Status,
    Verdict,
)
from aihr.pipeline import run
from aihr.score import rank, score_vacancy
from aihr.score.summary import ranking_summary
from tests.conftest import fixture_file


def _doc(vid: str, title: str) -> Document:
    frag = Fragment(
        id=f"{vid}.1",
        order=1,
        section=None,
        section_role="requirements",
        source=FragmentSource.paragraph,
        text="x",
    )
    return Document(
        id=vid,
        content_hash="0" * 12,
        kind=DocKind.vacancy,
        filename=f"{vid}.txt",
        title=title,
        fragments=[frag],
    )


def _req(vid: str, i: int, text: str, modality: Modality = Modality.must) -> Requirement:
    return Requirement(
        id=f"{vid}.req{i}",
        vacancy_id=vid,
        text=text,
        kind=ReqKind.skill,
        modality=modality,
        modality_marker=None,
        modality_reason="",
        source_fragment_ids=[f"{vid}.1"],
    )


def _v(rid: str, status: Status, etype: EvidenceType | None = None, **kw) -> Verdict:
    ev = [Evidence(fragment_id="R3", quote="q")] if status != Status.not_stated else []
    return Verdict(
        requirement_id=rid,
        status=status,
        evidence_type=etype,
        evidence=ev,
        comment="c",
        confidence=0.8,
        decided_by="pass_a",
        **kw,
    )


def _case(statuses: dict[str, list[tuple]]):
    reqs, verdicts, scores = {}, {}, []
    for vid, items in statuses.items():
        reqs[vid] = [_req(vid, i, text, mod) for i, (text, mod, *_rest) in enumerate(items, 1)]
        verdicts[vid] = [
            _v(f"{vid}.req{i}", st, *et, **(kw[0] if kw else {}))
            for i, (_t, _m, st, *rest) in enumerate(items, 1)
            for et, kw in [([rest[0]] if rest else [], rest[1:] if len(rest) > 1 else [])]
        ]
        scores.append(score_vacancy(_doc(vid, f"Вакансия {vid}"), reqs[vid], verdicts[vid]))
    return rank(scores), reqs, verdicts


def test_none_fits_names_reasons_and_indirect_options() -> None:
    ranking, reqs, verdicts = _case(
        {
            "V1": [
                ("Опыт продаж B2B", Modality.must, Status.mismatch, EvidenceType.direct),
                (
                    "Знание CRM",
                    Modality.must,
                    Status.partial,
                    EvidenceType.adjacent,
                    {"missing": "другая CRM"},
                ),
            ],
            "V2": [
                ("Опыт в медицине", Modality.must, Status.not_stated),
                ("Сертификат специалиста", Modality.must, Status.mismatch, EvidenceType.direct),
            ],
        }
    )
    assert all(s.label == FitLabel.not_fit for s in ranking.items)
    text = ranking_summary(ranking, reqs, verdicts)
    assert text.startswith("Прямо не подходит ни одна вакансия.")
    assert "Опыт продаж B2B — по резюме не выполнено (R3)" in text  # обоснование с фрагментом
    assert "Опыт в медицине — нет сведений" in text
    assert "Косвенно мог бы подойти: «Вакансия V1» (V1)" in text
    assert "смежный навык, закрывается обучением; не хватает: другая CRM" in text


def test_best_vacancy_summary_when_something_fits() -> None:
    ranking, reqs, verdicts = _case(
        {
            "V1": [("Навык A", Modality.must, Status.match, EvidenceType.direct)],
            "V2": [("Навык B", Modality.must, Status.mismatch, EvidenceType.direct)],
        }
    )
    text = ranking_summary(ranking, reqs, verdicts)
    assert text.startswith("Лучше всего подходит «Вакансия V1» (V1): подходит")


def test_no_indirect_matches_is_said_plainly() -> None:
    ranking, reqs, verdicts = _case(
        {"V1": [("Навык A", Modality.must, Status.mismatch, EvidenceType.direct)]}
    )
    assert ranking_summary(ranking, reqs, verdicts).endswith(
        "Косвенных совпадений по требованиям нет."
    )


@pytest.fixture
def result():
    return run(
        fixture_file("resume_cook.txt"),
        [fixture_file("vacancy_cook.txt"), fixture_file("vacancy_welder.txt")],
    )


def test_pipeline_sets_summaries(result) -> None:
    assert result.ranking and result.ranking.summary
    for report in result.reports.values():
        assert report.summary.startswith("Кандидат ")
        assert "must" not in report.summary and "nice" not in report.summary  # без HR-терминов


def test_docx_export(result) -> None:
    from aihr.report.export import report_docx

    vid = result.ranking.items[0].vacancy_id
    d = docx.Document(io.BytesIO(report_docx(result, vid)))
    text = "\n".join(p.text for p in d.paragraphs)
    for part in (
        "Оценка кандидата",
        "Требования вакансии",
        "Для рекрутера",
        "Черновик письма кандидату",
    ):
        assert part in text
    assert result.reports[vid].summary in text
    table = d.tables[0]
    assert [c.text for c in table.rows[0].cells] == [
        "Требование",
        "Тип",
        "Статус",
        "Подтверждение в резюме",
        "Комментарий",
    ]
    assert len(table.rows) == len(result.reports[vid].rows) + 1


def test_docx_endpoint() -> None:
    client = TestClient(app)
    resume, vac = fixture_file("resume_cook.txt"), fixture_file("vacancy_cook.txt")
    r = client.post(
        "/match", files=[("resume", (resume[1], resume[0])), ("vacancies", (vac[1], vac[0]))]
    )
    run_id = r.json()["run_id"]
    got = client.get(f"/runs/{run_id}/report/V1.docx")
    assert got.status_code == 200 and got.content[:2] == b"PK"
    assert "attachment" in got.headers["content-disposition"]
    assert client.get(f"/runs/{run_id}/report/V9.docx").status_code == 404
    get_settings.cache_clear()


def test_near_tie_is_flagged_in_comparison_and_summary() -> None:
    ranking, reqs, verdicts = _case(
        {
            "V1": [
                ("Навык A", Modality.must, Status.match, EvidenceType.direct),
                ("Навык B", Modality.nice, Status.not_stated),
            ],
            "V2": [
                ("Навык C", Modality.must, Status.match, EvidenceType.direct),
                ("Навык D", Modality.nice, Status.partial, EvidenceType.direct),
            ],
        }
    )
    a, b = ranking.items
    assert abs(a.score - b.score) < 3  # 87.5 и 87.5 — вровень
    assert "Баллы почти равны" in ranking.comparison[0]
    text = ranking_summary(ranking, reqs, verdicts)
    assert "почти вровень" in text


def test_clear_gap_is_not_flagged() -> None:
    ranking, _reqs, _verdicts = _case(
        {
            "V1": [("Навык A", Modality.must, Status.match, EvidenceType.direct)],
            "V2": [("Навык B", Modality.must, Status.mismatch, EvidenceType.direct)],
        }
    )
    assert "почти равны" not in ranking.comparison[0]
