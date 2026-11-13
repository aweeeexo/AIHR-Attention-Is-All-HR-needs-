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


def none_fits(ranking: Ranking | None) -> bool:
    return bool(ranking and ranking.items) and all(
        s.label == FitLabel.not_fit
        for s in ranking.items  # type: ignore[union-attr]
    )


def closest_other(score: VacancyScore, ranking: Ranking | None) -> VacancyScore | None:
    """Ближайшая по баллу другая вакансия — когда прямо не подходит ни одна (D35)."""
    if ranking is None:
        return None
    return next((s for s in ranking.items if s.vacancy_id != score.vacancy_id), None)


def manager_summary(
    score: VacancyScore,
    reqs: list[Requirement],
    verdicts: dict[str, Verdict],
    strength: str | None,
    ranking: Ranking | None,
) -> str:
    """2–3 предложения для нанимающего менеджера, без HR-терминов (D36)."""
    must = score.must
    verdict_word = {
        FitLabel.fits: "Кандидат подходит",
        FitLabel.fits_with_caveats: "Кандидат подходит с оговорками",
        FitLabel.not_fit: "Кандидат не подходит",
    }[score.label]
    parts = [
        f"{verdict_word}: из {must.total} обязательных требований подтверждено {must.match}"
        + (f", частично — {must.partial}" if must.partial else "")
        + "."
    ]
    unconfirmed = [
        _short(r.text, 60)
        for r in reqs
        if r.modality == Modality.must
        and r.verifiable
        and (v := verdicts.get(r.id))
        and v.status in (Status.mismatch, Status.not_stated)
    ]
    if unconfirmed:
        parts.append("Не подтверждено: " + "; ".join(unconfirmed[:3]) + ".")
    if strength:
        parts.append(f"Главное в пользу кандидата: {_short(strength, 120)}.")
    if none_fits(ranking):
        parts.append(
            "Прямо не подходит ни одна из открытых вакансий — см. итог рейтинга, там "
            "вакансии, куда кандидат мог бы подойти косвенно."
        )
    return " ".join(parts)


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
        step = (
            f"Следующий шаг: короткий звонок, чтобы уточнить {n} {_questions_word(n)}."
            if n
            else "Следующий шаг: короткий звонок для уточнения деталей."
        )
    else:
        alt = better_alternative(score, ranking)
        closest = closest_other(score, ranking) if none_fits(ranking) else None
        if alt:
            step = (
                f"Следующий шаг: предложить вакансию «{alt.title or alt.vacancy_id}» — по ней "
                f"метка «{LABEL_RU[alt.label]}»."
            )
        elif closest and closest.score > score.score:
            step = (
                "Прямо не подходит ни одна вакансия. Следующий шаг: обсудить с кандидатом "
                f"ближайшую — «{closest.title or closest.vacancy_id}» (балл {closest.score:g}), "
                "что можно закрыть обучением, или вежливый отказ."
            )
        elif none_fits(ranking):
            step = (
                "Прямо не подходит ни одна вакансия; эта — ближайшая из открытых. Следующий шаг: "
                "обсудить с кандидатом, что можно закрыть обучением, или вежливый отказ."
            )
        else:
            step = "Следующий шаг: вежливый отказ с обратной связью."
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
        lines += [
            "",
            "Если у вас есть такой опыт, но он не попал в резюме, напишите нам — мы "
            "вернёмся к вашей кандидатуре.",
        ]
    alt = better_alternative(score, ranking) or (
        closest_other(score, ranking) if none_fits(ranking) else None
    )
    if alt and alt.score > score.score:
        lines += ["", f"Возможно, вам будет интересна вакансия «{alt.title or alt.vacancy_id}»."]
    lines += ["", "С уважением, команда подбора"]
    return "\n".join(lines)
