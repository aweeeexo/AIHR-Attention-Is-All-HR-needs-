"""Интерфейс рекрутера (T12): загрузка → рейтинг → вакансия подробно → что ушло наружу.

UI не вызывает пайплайн сам, а ходит в API по адресу API_URL. Отрисовка опирается только на
структуру MatchResult, поэтому работает и в режиме LLM, и без него.
"""

from __future__ import annotations

import html
import json
import os
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


# ---------- отрисовка ----------


def _health() -> dict[str, Any] | None:
    try:
        return httpx.get(f"{API_URL}/health", timeout=5).json()
    except (httpx.HTTPError, ValueError):
        return None


def _post(path: str, **kwargs: Any) -> None:
    try:
        with st.status("Считаем: " + " → ".join(STEPS), expanded=False) as status:
            response = httpx.post(f"{API_URL}{path}", timeout=TIMEOUT_S, **kwargs)
            status.update(label="Готово", state="complete")
    except httpx.HTTPError as exc:
        st.error(f"API недоступен: {type(exc).__name__}")
        return
    if response.status_code != 200:
        st.error(f"Ошибка API {response.status_code}: {response.text[:500]}")
        return
    st.session_state["result"] = response.json()
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
    for line in ranking.get("comparison", []):
        st.caption(line)
    with st.expander("Как посчитано"):
        st.write(ranking.get("formula", ""))


def _show_vacancy(result: dict[str, Any], vacancy_id: str) -> None:
    report = result["reports"].get(vacancy_id)
    if report is None:
        st.info("Для этой вакансии отчёт не собран.")
        return
    tabs = st.tabs(["Требования", "Профиль кандидата", "Требования вакансии", "Отчёт"])
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
        st.caption(f"API: {health['status']} · LLM: {llm}")

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
    if not result:
        return
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
            "Вакансия", list(names), format_func=names.get, horizontal=True, key="selected_vacancy"
        )
        _show_vacancy(result, vid)

    with st.expander("Что ушло наружу (журнал запросов к LLM)"):
        _show_outbound(result["run_id"])
    st.download_button(
        "Скачать результат (JSON)",
        json.dumps(result, ensure_ascii=False, indent=2),
        file_name=f"aihr_{result['run_id']}.json",
        mime="application/json",
    )


if __name__ == "__main__":
    main()
