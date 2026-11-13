"""D50: «что если» — ответ кандидата меняет статус, балл и рейтинг пересчитывает код."""

import pytest
from fastapi.testclient import TestClient

from aihr.api.app import app
from aihr.config import get_settings
from aihr.contracts import Status
from aihr.pipeline import run
from aihr.score.whatif import WhatIfAnswer, WhatIfError, what_if
from tests.conftest import fixture_file


@pytest.fixture
def result():
    return run(
        fixture_file("resume_cook.txt"),
        [fixture_file("vacancy_cook.txt"), fixture_file("vacancy_welder.txt")],
    )


def _unknown(result, vid):
    return [v for v in result.verdicts[vid] if v.status == Status.not_stated]


def test_answer_raises_score_and_narrows_interval(result) -> None:
    vid = next(v for v in result.verdicts if _unknown(result, v))
    target = _unknown(result, vid)[0]
    out = what_if(result, [WhatIfAnswer(vacancy_id=vid, requirement_id=target.requirement_id,
                                        status=Status.match)])  # fmt: skip
    ch = next(c for c in out.changes if c.vacancy_id == vid)
    assert ch.score_after > ch.score_before and ch.answers == 1
    width = lambda iv: iv[1] - iv[0]  # noqa: E731
    assert width(ch.interval_after) < width(ch.interval_before)
    # Прогон не меняется — это расчёт поверх него
    assert target.status == Status.not_stated
    assert [s.vacancy_id for s in out.ranking.items] == sorted(
        [s.vacancy_id for s in out.ranking.items],
        key=lambda v: next(c.place_after for c in out.changes if c.vacancy_id == v),
    )


def test_no_answers_changes_nothing(result) -> None:
    out = what_if(result, [])
    assert all(c.score_before == c.score_after and c.place_before == c.place_after
               for c in out.changes)  # fmt: skip


def test_unknown_requirement_rejected(result) -> None:
    with pytest.raises(WhatIfError):
        what_if(result, [WhatIfAnswer(vacancy_id="V1", requirement_id="V1.req999",
                                      status=Status.match)])  # fmt: skip
    with pytest.raises(WhatIfError):
        what_if(result, [WhatIfAnswer(vacancy_id="V9", requirement_id="V9.req1",
                                      status=Status.match)])  # fmt: skip


def test_whatif_api(result) -> None:
    client = TestClient(app)
    vid = next(v for v in result.verdicts if _unknown(result, v))
    rid = _unknown(result, vid)[0].requirement_id
    body = {"answers": [{"vacancy_id": vid, "requirement_id": rid, "status": "match"}]}
    r = client.post(f"/runs/{result.run_id}/whatif", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["ranking"]["items"]
    bad = {"answers": [{"vacancy_id": vid, "requirement_id": "x", "status": "match"}]}
    assert client.post(f"/runs/{result.run_id}/whatif", json=bad).status_code == 422
    assert client.post("/runs/20260101-000000-abcdef/whatif", json=body).status_code == 404
    get_settings.cache_clear()
