"""«Что если» (D50): рекрутер отмечает ответ кандидата — балл и рейтинг пересчитываются кодом.

Ответ на уточняющий вопрос меняет статус требования (чаще всего «Не указано» → «Соответствует»
или «Частично»). Пересчёт идёт той же формулой и тем же порядком, что основной рейтинг (D11),
без LLM, за миллисекунды. Результат прогона не меняется: это расчёт поверх него.
"""

from __future__ import annotations

from pydantic import BaseModel

from aihr.contracts import FitLabel, MatchResult, Ranking, Status, Verdict
from aihr.score import rank, score_vacancy
from aihr.score.summary import ranking_summary


class WhatIfAnswer(BaseModel):
    vacancy_id: str
    requirement_id: str
    status: Status  # каким статус стал после ответа кандидата


class WhatIfChange(BaseModel):
    vacancy_id: str
    score_before: float
    score_after: float
    interval_before: tuple[float, float]
    interval_after: tuple[float, float]
    label_before: FitLabel
    label_after: FitLabel
    place_before: int
    place_after: int
    answers: int  # сколько ответов учтено по этой вакансии


class WhatIfResult(BaseModel):
    ranking: Ranking
    changes: list[WhatIfChange]


class WhatIfError(ValueError):
    """Ответ ссылается на вакансию или требование, которых нет в прогоне."""


def _apply(verdict: Verdict, status: Status) -> Verdict:
    if status == verdict.status:
        return verdict
    return verdict.model_copy(
        update={
            "status": status,
            "partial_value": None,  # без порога — «частично» по умолчанию из конфига
            "comment": f"По ответу кандидата: {verdict.comment}"[:250],
        }
    )


def what_if(result: MatchResult, answers: list[WhatIfAnswer]) -> WhatIfResult:
    if result.ranking is None:
        raise WhatIfError("В прогоне нет рейтинга — пересчитывать нечего.")
    by_vacancy: dict[str, dict[str, Status]] = {}
    for a in answers:
        known = {v.requirement_id for v in result.verdicts.get(a.vacancy_id, [])}
        if a.vacancy_id not in result.verdicts:
            raise WhatIfError(f"Вакансии {a.vacancy_id} нет в рейтинге этого прогона.")
        if a.requirement_id not in known:
            raise WhatIfError(f"Требования {a.requirement_id} нет у вакансии {a.vacancy_id}.")
        by_vacancy.setdefault(a.vacancy_id, {})[a.requirement_id] = a.status

    docs = {d.id: d for d in result.vacancies}
    verdicts = {
        vid: [_apply(v, by_vacancy.get(vid, {}).get(v.requirement_id, v.status)) for v in vs]
        for vid, vs in result.verdicts.items()
    }
    scores = [
        score_vacancy(docs[vid], result.requirements[vid], verdicts[vid])
        for vid in result.verdicts
        if vid in docs
    ]
    ranking = rank(scores)
    ranking = ranking.model_copy(
        update={"summary": ranking_summary(ranking, result.requirements, verdicts)}
    )

    before = {s.vacancy_id: (i, s) for i, s in enumerate(result.ranking.items, 1)}
    changes = []
    for place, s in enumerate(ranking.items, 1):
        old_place, old = before[s.vacancy_id]
        changes.append(
            WhatIfChange(
                vacancy_id=s.vacancy_id,
                score_before=old.score,
                score_after=s.score,
                interval_before=(old.score_min, old.score_max),
                interval_after=(s.score_min, s.score_max),
                label_before=old.label,
                label_after=s.label,
                place_before=old_place,
                place_after=place,
                answers=len(by_vacancy.get(s.vacancy_id, {})),
            )
        )
    return WhatIfResult(ranking=ranking, changes=changes)
