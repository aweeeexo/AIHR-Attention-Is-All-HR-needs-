"""Метрики на золотом наборе (T10) → eval/report.md. Запуск: `make eval` / `uv run poe eval`.

Методы:
  1. «Ключевые слова» — базовая линия: требование выполнено, если в резюме есть ≥ половины его
     значимых слов; иначе «Не указано». Получает требования эталона.
  2. «Без LLM» — наш режим T11 (правила, поиск, синонимы).
  3. «Один промпт» — базовая линия с LLM: вакансия и резюме целиком в одном запросе, модель сама
     выделяет требования, ставит статусы, пишет цитаты и балл. Без номеров фрагментов
     в доказательствах, проверки цитат и правил кода. Лучшая вакансия — по баллу модели.
  4. «С LLM» — полный пайплайн. 3 и 4 считаются, если модель отвечает; иначе «не посчитано».

Пары резюме × вакансия без эталона в метрики статусов не входят.
"""

from __future__ import annotations

import json
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "eval"))

from typing import Literal  # noqa: E402

from pydantic import BaseModel, Field  # noqa: E402
from requirements_eval import evaluate  # noqa: E402

from aihr.config import Settings  # noqa: E402
from aihr.contracts import DocKind, LLMBadOutput, LLMUnavailable, MatchResult, Status  # noqa: E402
from aihr.ingest import load_document  # noqa: E402
from aihr.inputs import case_files, read_files  # noqa: E402
from aihr.llm import LLMClient  # noqa: E402
from aihr.pipeline import run  # noqa: E402
from aihr.privacy import PrivacyContext, mask_document  # noqa: E402
from aihr.retrieve import tokens  # noqa: E402

GOLDEN = ROOT / "eval" / "golden"
STATUSES = [s.value for s in Status]
RU = {"match": "Соотв.", "partial": "Частично", "mismatch": "Не соотв.", "not_stated": "Не указано"}


@dataclass
class MethodResult:
    name: str
    pairs: list[tuple[str, str]] = field(default_factory=list)  # (эталон, предсказание)
    req_total: int = 0
    req_matched: int = 0
    req_modality_ok: int = 0
    quotes_total: int = 0
    quotes_ok: int = 0
    best_ok: int = 0
    best_total: int = 0
    seconds: list[float] = field(default_factory=list)
    note: str = ""

    def macro_f1(self) -> float:
        scores = []
        for st in STATUSES:
            tp = sum(1 for g, p in self.pairs if g == st and p == st)
            fp = sum(1 for g, p in self.pairs if g != st and p == st)
            fn = sum(1 for g, p in self.pairs if g == st and p != st)
            if tp + fp + fn == 0:
                continue
            prec = tp / (tp + fp) if tp + fp else 0.0
            rec = tp / (tp + fn) if tp + fn else 0.0
            scores.append(2 * prec * rec / (prec + rec) if prec + rec else 0.0)
        return sum(scores) / len(scores) if scores else 0.0

    def accuracy(self) -> float:
        return sum(g == p for g, p in self.pairs) / len(self.pairs) if self.pairs else 0.0

    def wrong_mismatch(self) -> int:
        """Главная метрика критерия 5: «Не соответствует» там, где правильно «Не указано»."""
        return sum(1 for g, p in self.pairs if g == "not_stated" and p == "mismatch")


def golden_pairs() -> dict[tuple[str, str], dict]:
    out = {}
    for path in sorted(GOLDEN.glob("verdicts_R*_V*.json")):
        g = json.loads(path.read_text(encoding="utf-8"))
        out[(g["resume_file"], g["vacancy_file"])] = g
    return out


def golden_requirements() -> dict[str, dict]:
    return {
        json.loads(p.read_text(encoding="utf-8"))["vacancy_file"]: json.loads(
            p.read_text(encoding="utf-8")
        )
        for p in sorted(GOLDEN.glob("requirements_V*.json"))
    }


def vacancy_id(vfile: str) -> str:
    """Номер вакансии, как в пайплайне: V{n} по порядку файлов примера (эталон в тех же id)."""
    _, vacancies = case_files(ROOT / "data" / "case")
    return f"V{[p.name for p in vacancies].index(vfile) + 1}"


def score_pipeline(name: str, settings: Settings, llm: LLMClient | None = None) -> MethodResult:
    res = MethodResult(name)
    gold = golden_pairs()
    reqs_gold = golden_requirements()
    best = json.loads((GOLDEN / "rankings.json").read_text(encoding="utf-8"))["best"]
    resumes, vacancies = case_files(ROOT / "data" / "case")
    counted_req: set[str] = set()
    for resume in resumes:
        started = time.perf_counter()
        result: MatchResult = run(
            read_files([resume])[0], read_files(vacancies), settings=settings, llm=llm, save=False
        )
        res.seconds.append(time.perf_counter() - started)
        files = {v.id: v.filename for v in result.vacancies}
        for report in result.reports.values():
            res.quotes_total += report.verification.quotes_total
            res.quotes_ok += report.verification.quotes_verified
        if result.ranking and resume.name in best:
            res.best_total += 1
            res.best_ok += files.get(result.ranking.best_vacancy_id or "") == best[resume.name]
        for vid, reqs in result.requirements.items():
            vfile = files[vid]
            if vfile not in reqs_gold:
                continue
            score = evaluate(reqs_gold[vfile], reqs)
            if vfile not in counted_req:  # извлечение одинаково для всех резюме — считаем раз
                counted_req.add(vfile)
                res.req_total += score.golden
                res.req_matched += score.matched
                res.req_modality_ok += score.modality_ok
            g = gold.get((resume.name, vfile))
            if g is None:
                continue
            verdicts = {v.requirement_id: v for v in result.verdicts.get(vid, [])}
            for gi, item in enumerate(g["items"]):
                ri = score.matches.get(gi)
                predicted = verdicts[reqs[ri].id].status.value if ri is not None else "not_stated"
                res.pairs.append((item["status"], predicted))
    return res


def score_keywords() -> MethodResult:
    """Базовая линия: требования без LLM, статус «Соответствует», если в резюме есть ≥ половины
    значимых слов требования, иначе «Не указано»."""
    from aihr.fallback import extract_requirements_fallback

    res = MethodResult("Ключевые слова")
    reqs_gold = golden_requirements()
    for (resume_file, vfile), g in golden_pairs().items():
        path = ROOT / "data" / "case" / resume_file
        doc = mask_document(
            load_document(path.read_bytes(), path.name, DocKind.resume, "R"), PrivacyContext()
        )
        resume_tokens = set(tokens(" ".join(f.masked_text for f in doc.fragments)))
        vpath = ROOT / "data" / "case" / vfile
        vac = mask_document(
            load_document(vpath.read_bytes(), vfile, DocKind.vacancy, vacancy_id(vfile)),
            PrivacyContext(),
        )
        reqs = extract_requirements_fallback(vac)
        score = evaluate(reqs_gold[vfile], reqs)
        for gi, item in enumerate(g["items"]):
            ri = score.matches.get(gi)
            want = set(tokens(reqs[ri].text)) if ri is not None else set()
            hit = len(want & resume_tokens) / len(want) if want else 0
            res.pairs.append((item["status"], "match" if hit >= 0.5 else "not_stated"))
    res.note = "требования без LLM, статус по доле слов"
    return res


class OnePromptItem(BaseModel):
    # Все поля обязательные: иначе часть моделей их пропускает, и сравнить с эталоном нельзя
    requirement: str
    must: bool
    source_fragment_ids: list[str] = Field(min_length=1)
    status: Literal["match", "partial", "mismatch", "not_stated"]
    quote: str


class OnePromptResult(BaseModel):
    items: list[OnePromptItem]
    score: int = Field(ge=0, le=100)


def _norm(text: str) -> str:
    return " ".join(text.lower().replace("ё", "е").split())


def score_one_prompt(settings: Settings) -> MethodResult:
    """Базовая линия «один промпт»: всё делает модель за один вызов (через тот же LLMClient)."""
    from aihr.contracts import Modality, ReqKind, Requirement

    res = MethodResult("Один промпт (LLM)")
    gold = golden_pairs()
    reqs_gold = golden_requirements()
    best = json.loads((GOLDEN / "rankings.json").read_text(encoding="utf-8"))["best"]
    resumes, vacancies = case_files(ROOT / "data" / "case")
    counted: set[str] = set()
    failures: list[str] = []
    for rpath in resumes:
        started = time.perf_counter()
        ctx = PrivacyContext()  # как в пайплайне: вакансии маскируются первыми
        vacs = [
            mask_document(
                load_document(v.read_bytes(), v.name, DocKind.vacancy, vacancy_id(v.name)), ctx
            )
            for v in vacancies
        ]
        resume = mask_document(
            load_document(rpath.read_bytes(), rpath.name, DocKind.resume, "R"), ctx
        )
        llm = LLMClient(settings).for_run(ctx, None)
        resume_text = _norm(" ".join(f.masked_text for f in resume.fragments))
        scores: dict[str, int] = {}
        for vac in vacs:
            try:
                out = llm.structured(
                    "llm/one_prompt",
                    {"vacancy": vac.fragments, "resume": resume.fragments},
                    OnePromptResult,
                )
            except (LLMUnavailable, LLMBadOutput) as exc:
                # Длинный ответ «всё за раз» — слабое место подхода: считаем как пустой ответ
                failures.append(f"{rpath.name[:12]}…×{vac.id}: {type(exc).__name__}")
                out = OnePromptResult(items=[], score=0)
            scores[vac.filename] = out.score
            known = {f.id for f in vac.fragments}
            reqs = [
                Requirement(
                    id=f"{vac.id}.req{i}",
                    vacancy_id=vac.id,
                    text=item.requirement[:300],
                    kind=ReqKind.other,
                    modality=Modality.must if item.must else Modality.nice,
                    modality_marker=None,
                    modality_reason="",
                    source_fragment_ids=[f for f in item.source_fragment_ids if f in known]
                    or [vac.fragments[0].id],
                )
                for i, item in enumerate(out.items, 1)
            ]
            for item in out.items:
                if item.status != "not_stated":
                    res.quotes_total += 1
                    res.quotes_ok += bool(item.quote.strip()) and _norm(item.quote) in resume_text
            score = evaluate(reqs_gold[vac.filename], reqs)
            if vac.filename not in counted:
                counted.add(vac.filename)
                res.req_total += score.golden
                res.req_matched += score.matched
                res.req_modality_ok += score.modality_ok
            g = gold.get((rpath.name, vac.filename))
            if g is None:
                continue
            for gi, item in enumerate(g["items"]):
                ri = score.matches.get(gi)
                res.pairs.append(
                    (item["status"], out.items[ri].status if ri is not None else "not_stated")
                )
        res.seconds.append(time.perf_counter() - started)
        if rpath.name in best and scores:
            res.best_total += 1
            res.best_ok += max(scores, key=lambda k: scores[k]) == best[rpath.name]
    res.note = "цитаты пишет модель: проверены дословно по резюме"
    if failures:
        res.note += f"; без ответа {len(failures)} из {len(resumes) * len(vacancies)} запросов"
    return res


def retrieval_recall(k: int = 8, embeddings: bool = False) -> tuple[int, int]:
    """Полнота поиска доказательств: доля пунктов эталона с фрагментами, у которых хотя бы один
    фрагмент эталона есть в первых k результатах поиска по тексту требования (без LLM).
    embeddings=True — гибрид BM25 + эмбеддинги, если extra установлен; иначе (0, 0)."""
    from aihr.fallback import extract_requirements_fallback
    from aihr.retrieve import Retriever, roles_for

    hit = total = 0
    reqs_gold = golden_requirements()
    for (resume_file, vfile), g in golden_pairs().items():
        path = ROOT / "data" / "case" / resume_file
        doc = mask_document(
            load_document(path.read_bytes(), path.name, DocKind.resume, "R"), PrivacyContext()
        )
        retriever = Retriever(doc, embeddings=embeddings)
        if embeddings and not retriever.uses_embeddings:
            return 0, 0
        vpath = ROOT / "data" / "case" / vfile
        vac = mask_document(
            load_document(vpath.read_bytes(), vfile, DocKind.vacancy, vacancy_id(vfile)),
            PrivacyContext(),
        )
        reqs = extract_requirements_fallback(vac)
        score = evaluate(reqs_gold[vfile], reqs)
        for gi, item in enumerate(g["items"]):
            if not item["fragment_ids"] or gi not in score.matches:
                continue
            req = reqs[score.matches[gi]]
            found = {
                fid
                for fid, _ in retriever.search(
                    req.text, req.canonical_terms, k=k, section_roles=roles_for(req.kind)
                )
            }
            total += 1
            hit += bool(found & set(item["fragment_ids"]))
    return hit, total


def fairness(settings: Settings) -> list[tuple[str, float]]:
    """Сдвиг балла при замене имени, пола и возраста в одном и том же резюме (режим без LLM)."""
    base = (ROOT / "tests" / "fixtures" / "resume_cook.txt").read_text(encoding="utf-8")
    vacancy = (ROOT / "tests" / "fixtures" / "vacancy_cook.txt").read_bytes()
    variants = {
        "исходное": base,
        "другое имя": base.replace("Смирнова Анна Викторовна", "Ахмедов Рустам Ильдарович"),
        "пол и возраст": base.replace(
            "Повар горячего цеха\n", "Повар горячего цеха\nМужчина, 52 года\n", 1
        ),
    }
    scores = {}
    for name, text in variants.items():
        r = run((text.encode(), "resume.txt"), [(vacancy, "v.txt")], settings=settings, save=False)
        scores[name] = r.ranking.items[0].score if r.ranking and r.ranking.items else 0.0
    return [
        (name, round(s - scores["исходное"], 1)) for name, s in scores.items() if name != "исходное"
    ]


def llm_available(settings: Settings) -> bool:
    from pydantic import BaseModel

    class Ping(BaseModel):
        ok: bool
        word: str

    if not settings.llm_configured:
        return False
    try:
        LLMClient(settings).structured("llm/ping", {"word": "проверка"}, Ping)
        return True
    except Exception:
        return False


def confusion(res: MethodResult) -> list[str]:
    lines = [
        "| эталон \\ ответ | " + " | ".join(RU[s] for s in STATUSES) + " |",
        "|---|" + "---|" * 4,
    ]
    counts = Counter(res.pairs)
    for g in STATUSES:
        lines.append(f"| **{RU[g]}** | " + " | ".join(str(counts[(g, p)]) for p in STATUSES) + " |")
    return lines


def main() -> int:
    offline = Settings(_env_file=None, llm_provider="none", today="2026-11")  # type: ignore[call-arg]
    online = Settings(_env_file=ROOT / ".env", today="2026-11")  # type: ignore[call-arg]
    methods = [score_keywords(), score_pipeline("Без LLM (режим T11)", offline)]
    if llm_available(online):
        methods.append(score_one_prompt(online))
        methods.append(score_pipeline("С LLM (полный пайплайн)", online, LLMClient(online)))
    else:
        for name in ("Один промпт (LLM)", "С LLM (полный пайплайн)"):
            methods.append(MethodResult(name, note="не посчитано: LLM недоступна при прогоне"))

    golden = golden_pairs()
    n_items = sum(len(g["items"]) for g in golden.values())
    n_reqs = sum(len(r["items"]) for r in golden_requirements().values())
    out = [
        "# Качество на золотом наборе",
        "",
        f"Эталон: требования 3 вакансий кейса ({n_reqs} пунктов), статусы {len(golden)} пар "
        f"резюме × вакансия ({n_items} пунктов), лучшая вакансия для 4 резюме. "
        "Разметка — `eval/golden/`, рубрика — T07. Пересчёт: `make eval`.",
        "",
        "| Метод | Полнота требований | Модальность | Macro-F1 статусов | Точность статусов | "
        "«Не соотв.» вместо «Не указано» | Цитаты проверены | Лучшая вакансия | Сек. на резюме |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for m in methods:
        if not m.pairs:
            out.append(f"| {m.name} | — | — | — | — | — | — | — | {m.note} |")
            continue
        req = f"{m.req_matched / m.req_total:.0%}" if m.req_total else "как без LLM"
        mod = f"{m.req_modality_ok / m.req_matched:.0%}" if m.req_matched else "—"
        quotes = f"{m.quotes_ok}/{m.quotes_total}" if m.quotes_total else "—"
        best = f"{m.best_ok} из {m.best_total}" if m.best_total else "—"
        secs = f"{sum(m.seconds) / len(m.seconds):.1f}" if m.seconds else "—"
        out.append(
            f"| {m.name} | {req} | {mod} | {m.macro_f1():.2f} | {m.accuracy():.0%} | "
            f"{m.wrong_mismatch()} | {quotes} | {best} | {secs} |"
        )
    notes = [f"- {m.name}: {m.note}." for m in methods if m.pairs and m.note]
    if notes:
        out += ["", *notes]
    if methods[-1].pairs:
        model = re.sub(r"^(\w+://)[^/]+/", r"\1<каталог>/", online.llm_model or "")
        out += ["", f"Модель в строках с LLM: `{model}`."]
        if online.llm_model_routes.strip():
            routes = re.sub(r"(\w+://)[^/,]+/", r"\1<каталог>/", online.llm_model_routes)
            out[-1] += f" Маршруты шагов (`LLM_MODEL_ROUTES`): `{routes}`."
        if online.llm_provider == "replay":
            out[-1] += (
                " Провайдер replay (D39): ответы модели из файлов. Время — ожидание исполнителя "
                "или чтение кэша, это не задержка API."
            )
    for m in methods:
        if m.pairs:
            out += ["", f"**Матрица ошибок — {m.name}**", "", *confusion(m)]
    hit, total = retrieval_recall()
    out += [
        "",
        "## Поиск доказательств",
        "",
        "Recall@8 — доля пунктов эталона, для которых нужный фрагмент резюме есть среди 8 "
        "найденных. Цель T06 — 90%.",
        "",
        f"- BM25 + синонимы: {hit} из {total} — {hit / max(total, 1):.0%}",
    ]
    e_hit, e_total = retrieval_recall(embeddings=True)
    if e_total:
        out.append(
            f"- BM25 + синонимы + эмбеддинги (`{offline.embeddings_model}`, RRF): {e_hit} из "
            f"{e_total} — {e_hit / e_total:.0%}"
        )
    else:
        out.append("- с эмбеддингами — не посчитано: extra `embeddings` не установлен")
    out += [
        "",
        "## Справедливость",
        "",
        "Одно и то же резюме, меняем только имя или добавляем пол и возраст (режим без LLM). "
        "Сдвиг балла:",
        "",
    ]
    out += [f"- {name}: {delta:+g}" for name, delta in fairness(offline)]
    out += [
        "",
        "Метод «ключевые слова» никогда не ставит «Частично» и «Не соответствует» — поэтому "
        "у него ноль ошибок главной метрики, но низкий macro-F1.",
    ]
    report = "\n".join(out) + "\n"
    (ROOT / "eval" / "report.md").write_text(report, encoding="utf-8", newline="\n")
    sys.stdout.write(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
