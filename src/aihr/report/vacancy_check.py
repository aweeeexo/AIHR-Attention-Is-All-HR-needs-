"""Проверка качества вакансии (D51): что в требованиях мешает честно оценить кандидата.

Работает по извлечённым требованиям, кодом, без LLM. Находит:
- непроверяемые по резюме требования (личные качества) — их выносим в интервью;
- расплывчатые формулировки («уверенное знание» без меры) — рекрутеру стоит уточнить у заказчика;
- «вакансию-единорога» — слишком много обязательных требований;
- формулировки, которые выглядят дискриминирующими (возраст, пол, внешность, семья);
- дубли — два требования об одном и том же.

Словари — общие для любых вакансий, без слов из вакансий кейса (принцип 5).
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel

from aihr.contracts import Modality, ReqKind, Requirement
from aihr.retrieve import tokens

MAX_MUST = 10  # больше обязательных — «вакансия-единорог»
DUPLICATE_OVERLAP = 0.8

IssueKind = Literal["unverifiable", "vague", "too_many_must", "discriminatory", "duplicate"]

_VAGUE = re.compile(
    r"(?i)\b(?:уверенн\w*|хорош\w*|отличн\w*|глубок\w*|высок\w*\s+уров\w*|развит\w*|"
    r"сильн\w*|продвинут\w*|свободн\w*\s+владен\w*|грамотн\w*|опытн\w*)"
)
_DISCRIMINATORY = re.compile(
    r"(?i)\b(?:возраст\w*|не\s+старше\s+\d{2}|не\s+моложе\s+\d{2}|до\s+\d{2}\s+лет\s+включительно|"
    r"мужчин\w*|женщин\w*|девушк\w*|юнош\w*|славян\w*|внешност\w*|национальност\w*|"
    r"вероисповедан\w*|замужн\w*|холост\w*|без\s+детей|наличие\s+детей|прописк\w*)"
)


class VacancyIssue(BaseModel):
    kind: IssueKind
    requirement_id: str | None = None
    requirement: str | None = None
    text: str  # что не так
    hint: str  # что сделать


class VacancyCheck(BaseModel):
    vacancy_id: str
    title: str | None = None
    must_total: int
    nice_total: int
    issues: list[VacancyIssue]
    summary: str


def _token_set(req: Requirement) -> set[str]:
    return set(tokens(req.text)) | {f"={c}" for c in req.canonical_terms}


def check_vacancy(
    vacancy_id: str, requirements: list[Requirement], title: str | None = None
) -> VacancyCheck:
    issues: list[VacancyIssue] = []
    must = [r for r in requirements if r.modality == Modality.must]
    # Перечисление в одной строке вакансии делится на несколько требований — считаем строки
    must_lines = {tuple(r.source_fragment_ids) for r in must}
    seen_lines: set[tuple[str, tuple[str, ...]]] = set()

    def first_in_line(kind: str, r: Requirement) -> bool:
        key = (kind, tuple(r.source_fragment_ids))
        if key in seen_lines:
            return False
        seen_lines.add(key)
        return True

    for r in requirements:
        if _DISCRIMINATORY.search(r.text) and first_in_line("discriminatory", r):
            issues.append(
                VacancyIssue(
                    kind="discriminatory",
                    requirement_id=r.id,
                    requirement=r.text,
                    text="Формулировка похожа на ограничение по возрасту, полу, внешности, семье "
                    "или месту жительства.",
                    hint="Проверьте с юристом: в вакансиях такие ограничения запрещены. "
                    "Опишите нужный навык или условие работы вместо личного признака.",
                )
            )
        if (not r.verifiable or r.kind == ReqKind.soft) and first_in_line("unverifiable", r):
            same_line = [
                x.text
                for x in requirements
                if x.source_fragment_ids == r.source_fragment_ids
                and (not x.verifiable or x.kind == ReqKind.soft)
            ]
            issues.append(
                VacancyIssue(
                    kind="unverifiable",
                    requirement_id=r.id,
                    requirement="; ".join(same_line),
                    text="По резюме не проверить: это личное качество или готовность.",
                    hint="Вынести в интервью: попросить пример из опыта.",
                )
            )
        elif r.threshold is None and _VAGUE.search(r.text) and first_in_line("vague", r):
            word = _VAGUE.search(r.text).group(0).lower()  # type: ignore[union-attr]
            issues.append(
                VacancyIssue(
                    kind="vague",
                    requirement_id=r.id,
                    requirement=r.text,
                    text=f"Расплывчатая мера: «{word}» — без срока, задач или результата.",
                    hint="Уточнить у заказчика, что считать достаточным уровнем: стаж, типовые "
                    "задачи, пример проекта.",
                )
            )

    if len(must_lines) > MAX_MUST:
        issues.append(
            VacancyIssue(
                kind="too_many_must",
                text=f"Обязательных требований {len(must_lines)} — «вакансия-единорог»: "
                "кандидатов, закрывающих всё, на рынке почти нет.",
                hint=f"Оставить обязательными 5–7 ключевых, остальные перевести в «будет плюсом» "
                f"(сейчас больше {MAX_MUST}).",
            )
        )

    sets = [(r, _token_set(r)) for r in requirements]
    for i, (a, sa) in enumerate(sets):
        for b, sb in sets[i + 1 :]:
            if set(a.source_fragment_ids) & set(b.source_fragment_ids):
                continue  # части одного перечисления — не дубли
            shared = len(sa & sb)
            if shared >= 2 and shared / min(len(sa), len(sb)) >= DUPLICATE_OVERLAP:
                issues.append(
                    VacancyIssue(
                        kind="duplicate",
                        requirement_id=b.id,
                        requirement=b.text,
                        text=f"Почти повторяет требование {a.id}: «{a.text[:80]}».",
                        hint="Объединить в одно, иначе один навык весит в балле дважды.",
                    )
                )

    counts = {k: sum(i.kind == k for i in issues) for k in IssueKind.__args__}  # type: ignore[attr-defined]
    if not issues:
        summary = "Требования конкретные и проверяемые по резюме — замечаний нет."
    else:
        parts = []
        if counts["discriminatory"]:
            parts.append(f"похожих на дискриминацию — {counts['discriminatory']}")
        if counts["unverifiable"]:
            parts.append(f"не проверить по резюме — {counts['unverifiable']} (в интервью)")
        if counts["vague"]:
            parts.append(f"расплывчатых — {counts['vague']}")
        if counts["duplicate"]:
            parts.append(f"дублей — {counts['duplicate']}")
        if counts["too_many_must"]:
            parts.append(f"обязательных слишком много ({len(must_lines)})")
        summary = "Замечания к вакансии: " + "; ".join(parts) + "."
    return VacancyCheck(
        vacancy_id=vacancy_id,
        title=title,
        must_total=len(must_lines),
        nice_total=len({tuple(r.source_fragment_ids) for r in requirements}) - len(must_lines),
        issues=issues,
        summary=summary,
    )
