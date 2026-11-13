"""Интерфейс рекрутера (T12): загрузка → рейтинг → вакансия подробно → что ушло наружу.

UI не вызывает пайплайн сам, а ходит в API по адресу API_URL. Отрисовка опирается только на
структуру MatchResult, поэтому работает и в режиме LLM, и без него.
"""

from __future__ import annotations

import html
import json
import os
import time
from typing import Any

import httpx
import pandas as pd
import streamlit as st

API_URL = os.environ.get("API_URL", "http://localhost:8000").rstrip("/")
TIMEOUT_S = 900

LABEL_RU = {
    "fits": "подходит",
    "fits_with_caveats": "подходит с оговорками",
    "not_fit": "не подходит",
}
LABEL_COLOR = {"fits": "green", "fits_with_caveats": "orange", "not_fit": "red"}
STATUS_COLOR = {
    "match": "#d4edda",
    "partial": "#fff3cd",
    "mismatch": "#f8d7da",
    "not_stated": "#e2e3e5",
}
EVIDENCE_RU = {"direct": "прямое", "indirect": "косвенное", "adjacent": "смежное"}
MODALITY_RU = {"must": "обязательное", "nice": "желательное"}
STEPS = ["загрузка", "обезличивание", "извлечение", "сопоставление", "балл и рейтинг", "отчёт"]
STEP_KEYS = {
    "ingest": "загрузка",
    "mask": "обезличивание",
    "extract_profile": "извлечение профиля",
    "extract_requirements": "извлечение требований",
    "match": "сопоставление",
    "score": "балл",
    "rank": "рейтинг",
    "report": "отчёт",
}


# ---------- данные для отрисовки (чистые функции, проверяются тестами) ----------


def months_text(months: int | None) -> str:
    if months is None:
        return "не указано"
    years, rest = divmod(int(months), 12)
    parts = [f"{years} г."] if years else []
    if rest or not years:
        parts.append(f"{rest} мес.")
    return " ".join(parts)


def ym_text(ym: dict[str, Any] | None) -> str:
    if not ym:
        return "?"
    return f"{ym['month']:02d}.{ym['year']}" if ym.get("month") else str(ym["year"])


def requirement_rows(report: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for row in report["rows"]:
        quotes = " … ".join(e["quote"] for e in row["resume_evidence"]) or "—"
        rows.append(
            {
                "id": row["requirement_id"],
                "Требование": row["requirement"],
                "Тип": MODALITY_RU.get(row["modality"], row["modality"]),
                "Статус": row["status_ru"],
                "Подтверждение в резюме": quotes,
                "Доказательство": EVIDENCE_RU.get(row.get("evidence_type") or "", "—"),
                "Комментарий": row["comment"],
                "Расчёт": row.get("computed") or "",
                "_status": row["status"],
            }
        )
    return pd.DataFrame(rows)


def profile_tables(profile: dict[str, Any]) -> dict[str, pd.DataFrame]:
    positions = pd.DataFrame(
        [
            {
                "Должность": p["title"],
                "Организация": p.get("organization") or "—",
                "Даты в резюме": p.get("raw_dates") or "—",
                "Период": f"{ym_text(p.get('start'))} – "
                f"{'н.в.' if p.get('is_current') else ym_text(p.get('end'))}"
                + (" (≈)" if p.get("dates_approximate") else ""),
                "Длительность": months_text(p.get("duration_months")),
                "Уровень задач": p.get("level") or "—",
                "Фрагменты": ", ".join(p["fragment_ids"]),
            }
            for p in profile.get("positions", [])
        ]
    )
    education = pd.DataFrame(
        [
            {
                "Уровень": e.get("level") or "не распознан",
                "Учебное заведение": e.get("institution") or "—",
                "Специальность": e.get("field") or "—",
                "Год окончания": e.get("year_end") or "—",
            }
            for e in profile.get("education", [])
        ]
    )
    skills = pd.DataFrame(
        [
            {
                "Навык": s["name"],
                "Упоминание": "подтверждён опытом"
                if s["mention_type"] == "evidenced"
                else "только в списке",
                "Лет": s.get("years") if s.get("years") is not None else "—",
                "Последний раз": s.get("last_used_year") or "—",
            }
            for s in profile.get("skills", [])
        ]
    )
    languages = pd.DataFrame(
        [
            {
                "Язык": lang["name"],
                "Как написано": lang.get("level_raw") or "—",
                "CEFR": lang.get("cefr") or "не указан",
            }
            for lang in profile.get("languages", [])
        ]
    )
    return {
        "positions": positions,
        "education": education,
        "skills": skills,
        "languages": languages,
    }


def resume_html(resume: dict[str, Any], highlight: set[str]) -> str:
    """Текст резюме по фрагментам; фрагменты-доказательства подсвечены."""
    parts = []
    section = None
    for frag in resume["fragments"]:
        if frag.get("section") != section:
            section = frag.get("section")
            if section:
                parts.append(
                    f"<div style='margin-top:.6em;font-weight:600'>{html.escape(section)}</div>"
                )
        text = html.escape(frag["text"])
        fid = html.escape(frag["id"])
        if frag["id"] in highlight:
            text = f"<mark style='background:#ffe58f'>{text}</mark>"
        parts.append(f"<div><span style='color:#999;font-size:.8em'>[{fid}]</span> {text}</div>")
    return "<div style='font-size:.9em;line-height:1.45'>" + "".join(parts) + "</div>"


def stage_lines(timings: dict[str, int]) -> list[str]:
    return [f"{STEP_KEYS[k]}: {v} мс" for k, v in timings.items() if k in STEP_KEYS]


def batch_matrix(batch: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(значения, метки) матрицы «кандидат × вакансия» для пакета (D38)."""
    vac_cols = {
        v["vacancy_id"]: f"{v['vacancy_id']} · {(v.get('title') or v['filename'])[:40]}"
        for v in batch["vacancies"]
    }
    rows = {r["resume_id"]: f"{r['resume_id']} · {r['filename']}" for r in batch["resumes"]}
    values = pd.DataFrame("—", index=list(rows.values()), columns=list(vac_cols.values()))
    labels = pd.DataFrame("", index=values.index, columns=values.columns)
    for c in batch["cells"]:
        row, col = rows[c["resume_id"]], vac_cols[c["vacancy_id"]]
        values.loc[row, col] = f"{c['score']:g} · {LABEL_RU[c['label']]}"
        labels.loc[row, col] = c["label"]
    return values, labels


def retrieval_text(health: dict[str, Any]) -> str:
    mode = health.get("retrieval")
    if mode == "bm25+embeddings":
        return "поиск доказательств: BM25 + эмбеддинги"
    if mode == "bm25":
        return "поиск доказательств: BM25"
    return ""


# ---------- отрисовка ----------


def _health() -> dict[str, Any] | None:
    try:
        return httpx.get(f"{API_URL}/health", timeout=5).json()
    except (httpx.HTTPError, ValueError):
        return None


POLL_S = 0.7


def _run_job(path: str, **kwargs: Any) -> dict[str, Any] | None:
    """Асинхронная задача API с живым прогрессом: этап и процент вместо долгого ожидания."""
    try:
        response = httpx.post(f"{API_URL}{path}", timeout=60, **kwargs)
    except httpx.HTTPError as exc:
        st.error(f"API недоступен: {type(exc).__name__}")
        return None
    if response.status_code not in (200, 202):
        st.error(f"Ошибка API {response.status_code}: {response.text[:500]}")
        return None
    job = response.json()
    bar = st.progress(0.0, text="В очереди")
    deadline = time.monotonic() + TIMEOUT_S * 4
    while job["status"] in ("queued", "running"):
        if time.monotonic() > deadline:
            st.error("Расчёт идёт слишком долго — проверьте API и LLM.")
            return None
        time.sleep(POLL_S)
        try:
            job = httpx.get(f"{API_URL}/jobs/{job['job_id']}", timeout=10).json()
        except (httpx.HTTPError, ValueError) as exc:
            st.error(f"API недоступен: {type(exc).__name__}")
            return None
        bar.progress(float(job["progress"]), text=f"{job['stage']} · {job['progress']:.0%}")
    bar.empty()
    if job["status"] == "failed":
        st.error(f"Расчёт не удался: {job.get('error') or 'неизвестная ошибка'}")
        return None
    return job


def _post(path: str, **kwargs: Any) -> None:
    job = _run_job("/jobs" + path, **kwargs)
    if job is None:
        return
    try:
        st.session_state["result"] = httpx.get(f"{API_URL}/runs/{job['run_id']}", timeout=30).json()
    except (httpx.HTTPError, ValueError) as exc:
        st.error(f"Не удалось получить результат: {type(exc).__name__}")
        return
    st.session_state.pop("selected_vacancy", None)


def _show_errors_and_warnings(result: dict[str, Any]) -> None:
    if result["mode"] == "fallback":
        st.warning("LLM недоступна или выключена: упрощённый режим без LLM.")
    for warning in result.get("warnings", []):
        st.warning(warning)
    for err in result.get("errors", []):
        with st.container(border=True):
            st.markdown(f"**{err['filename']}** · `{err['code']}`")
            st.markdown(f"{err['message']} {err['hint']}")


def _show_ranking(result: dict[str, Any]) -> None:
    ranking = result.get("ranking") or {}
    items = ranking.get("items", [])
    if not items:
        st.info("Рейтинг не построен: нет ни одной обработанной вакансии.")
        return
    st.subheader("Рейтинг вакансий")
    for place, s in enumerate(items, 1):
        with st.container(border=True):
            left, right = st.columns([3, 1])
            left.markdown(f"**{place}. {s['vacancy_id']} · {s.get('title') or 'без названия'}**")
            color = LABEL_COLOR[s["label"]]
            left.markdown(f":{color}[{LABEL_RU[s['label']]}]")
            right.metric("Балл", f"{s['score']:g}", help="«Не указано» считается как 0.5")
            right.caption(f"от {s['score_min']:g} до {s['score_max']:g}")
            must, nice = s["must"], s["nice"]
            left.caption(
                f"Обязательные: закрыто {must['match']} из {must['total']} · желательные: "
                f"{nice['match']} из {nice['total']} · не указано: "
                f"{must['not_stated'] + nice['not_stated']}"
            )
            left.write(s["explanation"])
    if ranking.get("summary"):
        st.info(ranking["summary"])
    for line in ranking.get("comparison", []):
        st.caption(line)
    with st.expander("Как посчитано"):
        st.write(ranking.get("formula", ""))


def _show_vacancy(result: dict[str, Any], vacancy_id: str) -> None:
    report = result["reports"].get(vacancy_id)
    if report is None:
        st.info("Для этой вакансии отчёт не собран.")
        return
    if report.get("summary"):
        st.markdown(f"**Вывод:** {report['summary']}")
    try:
        docx_bytes = httpx.get(
            f"{API_URL}/runs/{result['run_id']}/report/{vacancy_id}.docx", timeout=30
        ).content
    except httpx.HTTPError:
        docx_bytes = None
    if docx_bytes:
        st.download_button(
            "Скачать отчёт (DOCX)",
            docx_bytes,
            file_name=f"aihr_{result['run_id']}_{vacancy_id}.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            key=f"docx_{vacancy_id}",
        )
    tabs = st.tabs(["Требования", "Профиль кандидата", "Требования вакансии", "Отчёт", "Что если"])
    with tabs[0]:
        table = requirement_rows(report)
        left, right = st.columns([3, 2])
        with left:
            shown = table.drop(columns=["id", "_status"])
            colors = table["_status"].map(STATUS_COLOR)
            styled = shown.style.apply(
                lambda col: [
                    f"background-color: {c}" if col.name == "Статус" else "" for c in colors
                ]
            )
            event = st.dataframe(
                styled,
                hide_index=True,
                width="stretch",
                on_select="rerun",
                selection_mode="single-row",
                key=f"table_{vacancy_id}",
            )
        selected = event.selection.rows if event and hasattr(event, "selection") else []
        highlight: set[str] = set()
        if selected:
            rid = table.iloc[selected[0]]["id"]
            row = next(r for r in report["rows"] if r["requirement_id"] == rid)
            highlight = {e["fragment_id"] for e in row["resume_evidence"]}
            verdict = next(v for v in result["verdicts"][vacancy_id] if v["requirement_id"] == rid)
            with left:
                st.markdown(f"**Цитата из вакансии:** {row['vacancy_quote']}")
                if verdict.get("inference"):
                    st.markdown(f"**Цепочка вывода:** {verdict['inference']}")
                if verdict.get("missing"):
                    st.markdown(f"**Чего не хватает:** {verdict['missing']}")
        with right:
            st.caption("Резюме. Выберите строку таблицы — фрагменты-доказательства подсветятся.")
            if result.get("resume"):
                st.markdown(resume_html(result["resume"], highlight), unsafe_allow_html=True)
    with tabs[1]:
        profile = result.get("profile") or {}
        st.metric("Общий стаж", months_text(profile.get("total_experience_months")))
        tables = profile_tables(profile)
        for title, key in (
            ("Места работы", "positions"),
            ("Образование", "education"),
            ("Навыки", "skills"),
            ("Языки", "languages"),
        ):
            st.markdown(f"**{title}**")
            if tables[key].empty:
                st.caption("в резюме не найдено")
            else:
                st.dataframe(tables[key], hide_index=True, width="stretch")
        if profile.get("gaps_months"):
            gaps = ", ".join(f"{ym_text(a)} – {ym_text(b)}" for a, b in profile["gaps_months"])
            st.caption(f"Перерывы больше 6 месяцев: {gaps}")
    with tabs[2]:
        reqs = result["requirements"].get(vacancy_id, [])
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "id": r["id"],
                        "Требование": r["text"],
                        "Тип": MODALITY_RU.get(r["modality"], r["modality"]),
                        "Вид": r["kind"],
                        "Почему так": r["modality_reason"],
                        "Порог": (
                            f"{r['threshold']['kind']}: {r['threshold']['value']}"
                            if r.get("threshold")
                            else "—"
                        ),
                        "Проверяемо по резюме": "да" if r.get("verifiable", True) else "нет",
                    }
                    for r in reqs
                ]
            ),
            hide_index=True,
            width="stretch",
        )
    with tabs[3]:
        st.markdown("**Рекомендация рекрутеру**")
        st.write(report["recruiter_recommendation"])
        for title, key in (
            ("Сильные стороны", "strengths"),
            ("Сверх требований", "beyond_requirements"),
            ("Пробелы", "gaps"),
            ("Риски", "risks"),
        ):
            points = report.get(key, [])
            if points:
                st.markdown(f"**{title}**")
                for p in points:
                    refs = ", ".join(p.get("fragment_ids", []))
                    st.markdown(f"- {p['text']}" + (f" _({refs})_" if refs else ""))
        if report.get("questions"):
            st.markdown("**Вопросы кандидату**")
            for q in report["questions"]:
                st.markdown(f"- {q['text']}  \n  _{q['why']}_")
        st.markdown("**Письмо кандидату**")
        st.code(report["candidate_message"], language=None)  # у блока кода есть кнопка «Копировать»
        stats = report["verification"]
        st.caption(
            f"Проверка: цитат {stats['quotes_verified']} из {stats['quotes_total']} совпадают с "
            f"резюме; непроверенных сущностей в тексте: {stats['generated_entities_unverified']}"
        )
    with tabs[4]:
        _what_if(result, vacancy_id, report)


ANSWER_OPTIONS = {"не отвечал": None, "Соответствует": "match", "Частично": "partial",
                  "Не соответствует": "mismatch"}  # fmt: skip


def what_if_text(change: dict[str, Any]) -> str:
    """Строка итога «что если» для одной вакансии."""
    lo, hi = change["interval_after"]
    place = (
        f"место {change['place_before']} → {change['place_after']}"
        if change["place_before"] != change["place_after"]
        else f"место {change['place_after']} не изменилось"
    )
    return (
        f"Балл {change['score_before']:g} → **{change['score_after']:g}** (от {lo:g} до {hi:g}), "
        f"{LABEL_RU[change['label_before']]} → **{LABEL_RU[change['label_after']]}**, {place}."
    )


def _what_if(result: dict[str, Any], vacancy_id: str, report: dict[str, Any]) -> None:
    open_rows = [r for r in report["rows"] if r["status"] in ("not_stated", "partial")]
    if not open_rows:
        st.info("Все требования уже подтверждены или опровергнуты резюме — уточнять нечего.")
        return
    st.caption(
        "Кандидат ответил на уточняющий вопрос — отметьте ответ, и балл с рейтингом пересчитаются "
        "той же формулой, без LLM. Сам результат прогона не меняется."
    )
    answers = []
    for row in open_rows:
        choice = st.selectbox(
            f"{row['requirement']} · сейчас «{row['status_ru']}»",
            list(ANSWER_OPTIONS),
            key=f"whatif_{result['run_id']}_{row['requirement_id']}",
        )
        if ANSWER_OPTIONS[choice]:
            answers.append(
                {
                    "vacancy_id": vacancy_id,
                    "requirement_id": row["requirement_id"],
                    "status": ANSWER_OPTIONS[choice],
                }
            )
    if not st.button("Пересчитать", key=f"whatif_btn_{vacancy_id}", disabled=not answers):
        return
    try:
        response = httpx.post(
            f"{API_URL}/runs/{result['run_id']}/whatif", json={"answers": answers}, timeout=30
        )
    except httpx.HTTPError as exc:
        st.error(f"API недоступен: {type(exc).__name__}")
        return
    if response.status_code != 200:
        st.error(f"Ошибка API {response.status_code}: {response.text[:300]}")
        return
    data = response.json()
    change = next(c for c in data["changes"] if c["vacancy_id"] == vacancy_id)
    st.success(what_if_text(change))
    order = " → ".join(s["vacancy_id"] for s in data["ranking"]["items"])
    st.caption(f"Новый порядок вакансий: {order}")
    if data["ranking"].get("summary"):
        st.info(data["ranking"]["summary"])


def _show_outbound(run_id: str) -> None:
    try:
        data = httpx.get(f"{API_URL}/runs/{run_id}/outbound", timeout=10).json()
    except (httpx.HTTPError, ValueError):
        st.error("Журнал недоступен.")
        return
    entries = data.get("entries", [])
    if not entries:
        st.info("В этом прогоне во внешний API не ушло ни одного запроса.")
        return
    st.caption(
        "Каждый запрос к LLM: что именно ушло наружу. Текст уже обезличен; заблокированные "
        "запросы записаны без текста."
    )
    for e in entries:
        label = (
            f"{e.get('ts', '')} · {e.get('prompt_id')} v{e.get('prompt_version')} · "
            f"{e.get('status')}{' · из кэша' if e.get('cached') else ''}"
        )
        with st.expander(label):
            if e.get("reason"):
                st.write(e["reason"])
            for m in e.get("messages", []):
                st.markdown(f"**{m['role']}**")
                st.text(m["content"])


def main() -> None:
    st.set_page_config(page_title="AIHR — резюме и вакансии", layout="wide")
    st.title("AIHR: сопоставление резюме с вакансиями")
    health = _health()
    if health is None:
        st.error(f"API по адресу {API_URL} не отвечает.")
    else:
        llm = "подключена" if health["llm"] == "configured" else "не настроена (режим без LLM)"
        parts = [f"API: {health['status']}", f"LLM: {llm}", retrieval_text(health)]
        st.caption(" · ".join(p for p in parts if p))

    mode = st.radio(
        "Режим", ["Одно резюме", "Пакет резюме"], horizontal=True, label_visibility="collapsed"
    )
    if mode == "Пакет резюме":
        _batch_page()
        return

    with st.container(border=True):
        left, right = st.columns(2)
        with left:
            resume = st.file_uploader(
                "Резюме (docx, pdf, rtf, txt)", type=["docx", "pdf", "rtf", "txt"]
            )
            resume_text = st.text_area("…или вставьте текст резюме", height=100)
        with right:
            vacancies = st.file_uploader(
                "Вакансии (одна или несколько)",
                type=["docx", "pdf", "rtf", "txt"],
                accept_multiple_files=True,
            )
            vacancy_text = st.text_area("…или вставьте текст вакансии", height=100)
        has_resume = bool(resume or resume_text.strip())
        has_vacancy = bool(vacancies or vacancy_text.strip())
        col_run, col_example, col_pick = st.columns([1, 1, 2])
        if col_run.button("Сопоставить", type="primary", disabled=not (has_resume and has_vacancy)):
            files = (
                [("resume", (resume.name, resume.getvalue()))]
                if resume
                else [("resume", ("резюме.txt", resume_text.encode("utf-8")))]
            )
            files += [("vacancies", (v.name, v.getvalue())) for v in vacancies or []]
            if vacancy_text.strip():
                files.append(("vacancies", ("вакансия.txt", vacancy_text.encode("utf-8"))))
            _post("/match", files=files)
        try:
            example = httpx.get(f"{API_URL}/example/files", timeout=5).json()["resumes"]
        except (httpx.HTTPError, ValueError, KeyError):
            example = []
        pick = (
            col_pick.selectbox("Резюме из примера", example, label_visibility="collapsed")
            if example
            else None
        )
        if col_example.button("Пример из кейса", disabled=not example):
            _post("/match/example", params={"resume": pick} if pick else None)

    result = st.session_state.get("result")
    if result:
        _show_result(result)


def _show_result(result: dict[str, Any], key: str = "") -> None:
    st.caption(f"Прогон {result['run_id']} · режим: {result['mode']}")
    _show_errors_and_warnings(result)
    timings = stage_lines(result.get("timings_ms", {}))
    if timings:
        st.caption("Этапы: " + " · ".join(timings))
    _show_ranking(result)

    ranking = (result.get("ranking") or {}).get("items", [])
    if ranking:
        names = {s["vacancy_id"]: f"{s['vacancy_id']} · {s.get('title') or ''}" for s in ranking}
        st.subheader("Вакансия подробно")
        vid = st.radio(
            "Вакансия",
            list(names),
            format_func=names.get,
            horizontal=True,
            key=f"selected_vacancy{key}",
        )
        _show_vacancy(result, vid)

    with st.expander("Что ушло наружу (журнал запросов к LLM)"):
        _show_outbound(result["run_id"])
    st.download_button(
        "Скачать результат (JSON)",
        json.dumps(result, ensure_ascii=False, indent=2),
        file_name=f"aihr_{result['run_id']}.json",
        mime="application/json",
        key=f"download{key}",
    )


def _post_batch(path: str, **kwargs: Any) -> None:
    job = _run_job(path.replace("/match/batch", "/jobs/batch"), **kwargs)
    if job is None:
        return
    try:
        batch = httpx.get(f"{API_URL}/batches/{job['batch_id']}", timeout=30).json()
    except (httpx.HTTPError, ValueError) as exc:
        st.error(f"Не удалось получить результат: {type(exc).__name__}")
        return
    st.session_state["batch"] = batch
    st.session_state.pop("batch_candidate", None)


def _batch_page() -> None:
    with st.container(border=True):
        left, right = st.columns(2)
        resumes = left.file_uploader(
            "Резюме (несколько файлов)",
            type=["docx", "pdf", "rtf", "txt"],
            accept_multiple_files=True,
            key="batch_resumes",
        )
        vacancies = right.file_uploader(
            "Вакансии (одна или несколько)",
            type=["docx", "pdf", "rtf", "txt"],
            accept_multiple_files=True,
            key="batch_vacancies",
        )
        col_run, col_example, _ = st.columns([1, 1, 2])
        ready_to_run = bool(resumes and vacancies)
        if col_run.button("Сопоставить пакет", type="primary", disabled=not ready_to_run):
            files = [("resumes", (r.name, r.getvalue())) for r in resumes or []]
            files += [("vacancies", (v.name, v.getvalue())) for v in vacancies or []]
            _post_batch("/match/batch", files=files)
        if col_example.button("Пакет из кейса"):
            _post_batch("/match/batch/example")

    batch = st.session_state.get("batch")
    if not batch:
        st.caption(
            "Каждое резюме сопоставляется со всеми вакансиями той же формулой, что и в режиме "
            "одного резюме. Полный отчёт по каждому кандидату — ниже, после матрицы."
        )
        return
    st.caption(f"Пакет {batch['batch_id']}")
    st.info(batch["summary"])
    for warning in batch.get("warnings", []):
        st.warning(warning)
    resume_errors = [r["error"] for r in batch["resumes"] if r.get("error")]
    for err in batch.get("errors", []) + resume_errors:
        with st.container(border=True):
            st.markdown(f"**{err['filename']}** · `{err['code']}`")
            st.markdown(f"{err['message']} {err['hint']}")

    st.subheader("Кандидаты × вакансии")
    values, labels = batch_matrix(batch)
    colors = {"fits": "#d4edda", "fits_with_caveats": "#fff3cd", "not_fit": "#f8d7da"}
    styled = values.style.apply(
        lambda col: [f"background-color: {colors.get(v, '')}" for v in labels[col.name]], axis=0
    )
    st.dataframe(styled, use_container_width=True)

    names = {r["resume_id"]: r["filename"] for r in batch["resumes"]}
    scores = {(c["resume_id"], c["vacancy_id"]): c for c in batch["cells"]}
    st.subheader("Лучшие кандидаты по вакансиям")
    for vac in batch["vacancies"]:
        with st.container(border=True):
            st.markdown(f"**{vac['vacancy_id']} · {vac.get('title') or vac['filename']}**")
            st.write(vac["summary"])
            for place, rid in enumerate(vac["candidates"][:5], 1):
                c = scores[(rid, vac["vacancy_id"])]
                st.caption(
                    f"{place}. {rid} · {names[rid]} — {c['score']:g} "
                    f"(от {c['score_min']:g} до {c['score_max']:g}), {LABEL_RU[c['label']]}"
                )

    ready = [r for r in batch["resumes"] if r.get("run_id") and not r.get("error")]
    if not ready:
        return
    st.subheader("Кандидат подробно")
    rid = st.selectbox(
        "Кандидат",
        [r["resume_id"] for r in ready],
        format_func=lambda x: f"{x} · {names[x]}",
        key="batch_candidate",
    )
    run_id = next(r["run_id"] for r in ready if r["resume_id"] == rid)
    try:
        result = httpx.get(f"{API_URL}/runs/{run_id}", timeout=30).json()
    except (httpx.HTTPError, ValueError):
        st.error("Не удалось загрузить отчёт кандидата.")
        return
    _show_result(result, key=f"_{rid}")


if __name__ == "__main__":
    main()
