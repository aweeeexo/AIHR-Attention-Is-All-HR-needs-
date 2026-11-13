"""Оценка извлечения требований (T04) против ручного эталона eval/golden/requirements_V*.json.

    uv run python eval/requirements_eval.py            # с LLM из .env (ответы кэшируются)
    LLM_PROVIDER=none uv run python eval/requirements_eval.py   # базовая линия без LLM

Сопоставление: пункт эталона закрыт, если есть извлечённое требование с общим фрагментом
вакансии и хотя бы одним общим значимым словом. Каждое извлечённое требование закрывает не
больше одного пункта (жадно, по числу общих слов). Метрики: полнота, точность модальности
среди закрытых, «лишние» — извлечённые требования, не закрывшие ни одного пункта.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aihr.config import Settings  # noqa: E402
from aihr.contracts import DocKind, Requirement  # noqa: E402
from aihr.extract import extract_requirements  # noqa: E402
from aihr.fallback import extract_requirements_fallback  # noqa: E402
from aihr.ingest import load_document  # noqa: E402
from aihr.llm import LLMClient  # noqa: E402
from aihr.privacy import PrivacyContext, mask_document  # noqa: E402
from aihr.retrieve import tokens  # noqa: E402


@dataclass
class Score:
    vacancy: str
    golden: int
    matched: int
    modality_ok: int
    extracted: int
    extra: list[str]
    missed: list[str]
    wrong_modality: list[str]
    matches: dict[int, int]  # пункт эталона → индекс извлечённого требования

    @property
    def completeness(self) -> float:
        return self.matched / self.golden if self.golden else 0.0

    @property
    def modality(self) -> float:
        return self.modality_ok / self.matched if self.matched else 0.0


def evaluate(golden: dict, reqs: list[Requirement]) -> Score:
    pairs = []
    for gi, item in enumerate(golden["items"]):
        want = set(tokens(item["key"]))
        for ri, req in enumerate(reqs):
            if not set(item["fragment_ids"]) & set(req.source_fragment_ids):
                continue
            overlap = len(want & set(tokens(" ".join([req.text, *req.alternatives]))))
            if overlap:
                pairs.append((overlap, gi, ri))
    used_g: set[int] = set()
    used_r: set[int] = set()
    matches: dict[int, int] = {}
    for _, gi, ri in sorted(pairs, key=lambda p: (-p[0], p[1], p[2])):
        if gi in used_g or ri in used_r:
            continue
        used_g.add(gi)
        used_r.add(ri)
        matches[gi] = ri
    items = golden["items"]
    wrong = [
        f"{items[gi]['key']}: эталон {items[gi]['modality']}, получено {reqs[ri].modality.value}"
        for gi, ri in matches.items()
        if reqs[ri].modality.value != items[gi]["modality"]
    ]
    return Score(
        vacancy=golden["vacancy_file"],
        golden=len(items),
        matched=len(matches),
        modality_ok=len(matches) - len(wrong),
        extracted=len(reqs),
        extra=[reqs[ri].text for ri in range(len(reqs)) if ri not in used_r],
        missed=[items[gi]["key"] for gi in range(len(items)) if gi not in used_g],
        wrong_modality=wrong,
        matches=matches,
    )


def main() -> int:
    settings = Settings(_env_file=ROOT / ".env")  # type: ignore[call-arg]
    mode = (
        "llm"
        if settings.llm_configured and os.environ.get("LLM_PROVIDER") != "none"
        else "fallback"
    )
    llm = LLMClient(settings)
    scores = []
    for path in sorted((ROOT / "eval" / "golden").glob("requirements_V*.json")):
        golden = json.loads(path.read_text(encoding="utf-8"))
        vid = path.stem.split("_")[-1]
        file = ROOT / "data" / "case" / golden["vacancy_file"]
        doc = mask_document(
            load_document(file.read_bytes(), file.name, DocKind.vacancy, vid), PrivacyContext()
        )
        reqs = (
            extract_requirements(doc, llm) if mode == "llm" else extract_requirements_fallback(doc)
        )
        scores.append(evaluate(golden, reqs))

    total_g = sum(s.golden for s in scores)
    total_m = sum(s.matched for s in scores)
    total_ok = sum(s.modality_ok for s in scores)
    out = [
        f"## Извлечение требований (T04), режим `{mode}`",
        "",
        "| Вакансия | Эталон | Извлечено | Полнота | Модальность | Лишние |",
        "|---|---|---|---|---|---|",
    ]
    for s in scores:
        out.append(
            f"| {s.vacancy} | {s.golden} | {s.extracted} | {s.completeness:.0%} | "
            f"{s.modality:.0%} | {len(s.extra)} |"
        )
    out.append(
        f"| **Всего** | {total_g} | {sum(s.extracted for s in scores)} | "
        f"**{total_m / total_g:.0%}** | **{total_ok / max(total_m, 1):.0%}** | "
        f"{sum(len(s.extra) for s in scores)} |"
    )
    for s in scores:
        if s.missed or s.wrong_modality or s.extra:
            out += ["", f"**{s.vacancy}**"]
            out += [f"- пропущено: {m}" for m in s.missed]
            out += [f"- модальность: {w}" for w in s.wrong_modality]
            out += [f"- лишнее: {e}" for e in s.extra]
    sys.stdout.write("\n".join(out) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
