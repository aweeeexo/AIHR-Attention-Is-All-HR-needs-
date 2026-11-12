"""Проверка вердикта по документу (принципы 1 и 2, D8, D9).

- цитату всегда подставляет код из Fragment.text, что бы ни пришло от модели;
- fragment_id, которого нет в резюме, отбрасывается;
- «Соответствует», «Частично», «Не соответствует» без проверенного фрагмента → «Не указано».
"""

from __future__ import annotations

from aihr.contracts import Document, Evidence, Status, Verdict

NO_EVIDENCE_COMMENT = "В резюме не найден фрагмент, подтверждающий вывод, поэтому «Не указано»."


def attach_quotes(verdict: Verdict, resume: Document) -> Verdict:
    by_id = {f.id: f for f in resume.fragments}
    seen: set[str] = set()
    evidence: list[Evidence] = []
    for ev in verdict.evidence:
        frag = by_id.get(ev.fragment_id)
        if frag is None or frag.id in seen:
            continue
        seen.add(frag.id)
        evidence.append(Evidence(fragment_id=frag.id, quote=frag.text))

    update: dict[str, object] = {"evidence": evidence}
    if not evidence and verdict.status != Status.not_stated:
        update |= {
            "status": Status.not_stated,
            "evidence_type": None,
            "inference": None,
            "missing": None,
            "partial_value": None,
            "comment": NO_EVIDENCE_COMMENT,
        }
    return verdict.model_copy(update=update)
