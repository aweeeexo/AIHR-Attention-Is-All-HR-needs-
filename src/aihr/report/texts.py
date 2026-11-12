"""Рекомендация рекрутеру и письмо кандидату (T09, шаги 6–7) — шаблонами из чисел и вердиктов.

Шаблон не может выдумать факт: в нём только метка, счётчики, тексты требований и вопросы.
Письмо — черновик для рекрутера, автоматически не отправляется. Без оценок кандидата.
"""

from __future__ import annotations

from aihr.contracts import (
    FitLabel,
    Modality,
    Question,
    Ranking,
    Requirement,
    Status,
    VacancyScore,
    Verdict,
)

LABEL_RU = {
    FitLabel.fits: "подходит",
    FitLabel.fits_with_caveats: "подходит с оговорками",
    FitLabel.not_fit: "не подходит",
}
_LABEL_ORDER = {FitLabel.fits: 0, FitLabel.fits_with_caveats: 1, FitLabel.not_fit: 2}


def _short(text: str, n: int = 80) -> str:
    text = " ".join(text.split()).rstrip(".")
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def better_alternative(score: VacancyScore, ranking: Ranking | None) -> VacancyScore | None:
    """Другая вакансия из рейтинга с меткой лучше — предложить её при отказе."""
    if ranking is None:
        return None
    for other in ranking.items:
        if (
            other.vacancy_id != score.vacancy_id
            and _LABEL_ORDER[other.label] < _LABEL_ORDER[score.label]
        ):
            return other
    return None


def recommendation(
    score: VacancyScore,
    reqs: list[Requirement],
    verdicts: dict[str, Verdict],
    questions: list[Question],
    ranking: Ranking | None,
) -> str:
    must = score.must
    head = (
        f"{LABEL_RU[score.label].capitalize()}: закрыто {must.match} из {must.total} обязательных "
        f"требований, балл {score.score:g} (от {score.score_min:g} до {score.score_max:g})."
    )
    unconfirmed = [
        _short(r.text, 60)
        for r in reqs
        if r.modality == Modality.must
        and (v := verdicts.get(r.id))
        and v.status in (Status.mismatch, Status.not_stated)
        and r.verifiable
    ]
    detail = f" Не подтверждено: {'; '.join(unconfirmed[:3])}." if unconfirmed else ""
    if score.label == FitLabel.fits:
        step = "Следующий шаг: пригласить на интервью."
    elif score.label == FitLabel.fits_with_caveats:
        n = len(questions)
        step = f"Следующий шаг: короткий звонок, чтобы уточнить {n} {_questions_word(n)}." if n \
            else "Следующий шаг: короткий звонок для уточнения деталей."  # fmt: skip
    else:
        alt = better_alternative(score, ranking)
        step = (
            f"Следующий шаг: предложить вакансию «{alt.title or alt.vacancy_id}» — по ней метка "
            f"«{LABEL_RU[alt.label]}»."
            if alt
            else "Следующий шаг: вежливый отказ с обратной связью."
        )
    return f"{head}{detail} {step}"


def _questions_word(n: int) -> str:
    k = n % 100
    if 11 <= k <= 14:
        return "вопросов"
    return {1: "вопрос", 2: "вопроса", 3: "вопроса", 4: "вопроса"}.get(k % 10, "вопросов")


def candidate_message(
    score: VacancyScore,
    reqs: list[Requirement],
    verdicts: dict[str, Verdict],
    questions: list[Question],
    ranking: Ranking | None,
) -> str:
    title = score.title or "вакансию"
    if score.label in (FitLabel.fits, FitLabel.fits_with_caveats):
        lines = [
            "Здравствуйте!",
            "",
            f"Спасибо за отклик на вакансию «{title}». Мы изучили резюме и хотели бы "
            "пообщаться подробнее.",
        ]
        if questions:
            lines += ["", "Перед встречей подскажите, пожалуйста:"]
            lines += [f"— {q.text}" for q in questions[:3]]
        lines += ["", "Когда вам удобно созвониться?", "", "С уважением, команда подбора"]
        return "\n".join(lines)

    unconfirmed = [
        _short(r.text, 70)
        for r in reqs
        if r.modality == Modality.must
        and (v := verdicts.get(r.id))
        and v.status in (Status.mismatch, Status.not_stated, Status.partial)
        and r.verifiable
    ]
    lines = [
        "Здравствуйте!",
        "",
        f"Спасибо за интерес к вакансии «{title}». Мы внимательно изучили резюме: сейчас по нему "
        "не подтверждаются некоторые обязательные требования.",
    ]
    if unconfirmed:
        lines += [""] + [f"— {u}" for u in unconfirmed[:3]]
        lines += ["", "Если у вас есть такой опыт, но он не попал в резюме, напишите нам — мы "
                      "вернёмся к вашей кандидатуре."]  # fmt: skip
    alt = better_alternative(score, ranking)
    if alt:
        lines += ["", f"Возможно, вам будет интересна вакансия «{alt.title or alt.vacancy_id}»."]
    lines += ["", "С уважением, команда подбора"]
    return "\n".join(lines)
