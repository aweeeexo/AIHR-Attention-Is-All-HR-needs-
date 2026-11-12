"""UI-заглушка (T00): загрузка файлов, пример из кейса, JSON результата. Полный UI — T12.

UI не вызывает пайплайн сам, а ходит в API по адресу API_URL.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import streamlit as st

API_URL = os.environ.get("API_URL", "http://localhost:8000").rstrip("/")
TIMEOUT_S = 600

LABEL_RU = {
    "fits": "подходит",
    "fits_with_caveats": "подходит с оговорками",
    "not_fit": "не подходит",
}

st.set_page_config(page_title="AIHR — резюме и вакансии", layout="wide")
st.title("AIHR: сопоставление резюме с вакансиями")


def _health() -> dict[str, Any] | None:
    try:
        return httpx.get(f"{API_URL}/health", timeout=5).json()
    except (httpx.HTTPError, ValueError):
        return None


def _show(result: dict[str, Any]) -> None:
    st.caption(f"Прогон {result['run_id']} · режим: {result['mode']}")
    for err in result.get("errors", []):
        st.error(f"{err['filename']}: {err['message']} {err['hint']}")
    for warning in result.get("warnings", []):
        st.warning(warning)
    ranking = result.get("ranking") or {}
    items = ranking.get("items", [])
    if items:
        st.subheader("Рейтинг вакансий")
        st.table(
            [
                {
                    "Место": i,
                    "Вакансия": f"{s['vacancy_id']}: {s.get('title') or ''}",
                    "Балл": s["score"],
                    "Интервал": f"{s['score_min']}–{s['score_max']}",
                    "Метка": LABEL_RU.get(s["label"], s["label"]),
                }
                for i, s in enumerate(items, 1)
            ]
        )
    with st.expander("Полный результат (JSON)", expanded=not items):
        st.json(result)


def _post(path: str, **kwargs: Any) -> None:
    try:
        with st.spinner("Считаем…"):
            response = httpx.post(f"{API_URL}{path}", timeout=TIMEOUT_S, **kwargs)
    except httpx.HTTPError as exc:
        st.error(f"API недоступен: {type(exc).__name__}")
        return
    if response.status_code != 200:
        st.error(f"Ошибка API {response.status_code}: {response.text[:500]}")
        return
    st.session_state["result"] = response.json()


health = _health()
if health is None:
    st.error(f"API по адресу {API_URL} не отвечает.")
else:
    st.caption(f"API: {health['status']} · LLM: {health['llm']}")

left, right = st.columns(2)
with left:
    resume = st.file_uploader("Резюме (docx, pdf, txt)", type=["docx", "pdf", "txt"])
with right:
    vacancies = st.file_uploader(
        "Вакансии (одна или несколько)", type=["docx", "pdf", "txt"], accept_multiple_files=True
    )

col_run, col_example = st.columns(2)
if col_run.button("Сопоставить", type="primary", disabled=not (resume and vacancies)):
    files = [("resume", (resume.name, resume.getvalue()))]  # type: ignore[union-attr]
    files += [("vacancies", (v.name, v.getvalue())) for v in vacancies]
    _post("/match", files=files)
if col_example.button("Пример из кейса"):
    _post("/match/example")

if "result" in st.session_state:
    _show(st.session_state["result"])
