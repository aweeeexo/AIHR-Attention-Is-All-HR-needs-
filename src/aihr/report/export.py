"""Экспорт отчёта по вакансии в DOCX (D37) — готовый файл для отправки заказчику.

Порядок для нанимающего менеджера (D36): вывод, балл, таблица требований с цитатами, сильные
стороны, пробелы, риски. Отдельный раздел для рекрутера: рекомендация, вопросы, черновик письма.
Цитаты — из исходных документов, расчёты — кода; это видно в подписи таблицы.
"""

from __future__ import annotations

import io

from aihr.contracts import STATUS_RU, MatchResult, Modality, Point, Status

_STATUS_FILL = {
    Status.match: "D4EDDA",
    Status.partial: "FFF3CD",
    Status.mismatch: "F8D7DA",
    Status.not_stated: "E2E3E5",
}
LABEL_RU = {
    "fits": "подходит",
    "fits_with_caveats": "подходит с оговорками",
    "not_fit": "не подходит",
}


def _shade(cell, hex_fill: str) -> None:
    from docx.oxml import parse_xml
    from docx.oxml.ns import nsdecls

    cell._tc.get_or_add_tcPr().append(parse_xml(f'<w:shd {nsdecls("w")} w:fill="{hex_fill}"/>'))


def _points(doc, title: str, points: list[Point]) -> None:
    if not points:
        return
    doc.add_heading(title, level=2)
    for p in points:
        refs = f" [{', '.join(p.fragment_ids)}]" if p.fragment_ids else ""
        doc.add_paragraph(f"{p.text}{refs}", style="List Bullet")


def report_docx(result: MatchResult, vacancy_id: str) -> bytes:
    import docx
    from docx.shared import Pt

    report = result.reports[vacancy_id]
    vacancy = next(v for v in result.vacancies if v.id == vacancy_id)
    score = next(
        (s for s in (result.ranking.items if result.ranking else []) if s.vacancy_id == vacancy_id),
        None,
    )

    doc = docx.Document()
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(10)

    doc.add_heading(f"Оценка кандидата: {vacancy.title or vacancy.filename}", level=1)
    if result.resume:
        doc.add_paragraph(
            f"Резюме: {result.resume.filename} · вакансия: {vacancy.filename} · "
            f"прогон {result.run_id}"
        )
    if report.summary:
        doc.add_paragraph(report.summary)
    if score:
        doc.add_paragraph(
            f"Итог: {LABEL_RU[score.label.value]}. Балл {score.score:g} из 100 "
            f"(от {score.score_min:g} до {score.score_max:g} — смотря что окажется за тем, что "
            f"не указано в резюме). {score.explanation}"
        )

    doc.add_heading("Требования вакансии", level=2)
    table = doc.add_table(rows=1, cols=5)
    table.style = "Table Grid"
    for cell, title in zip(
        table.rows[0].cells,
        ["Требование", "Тип", "Статус", "Подтверждение в резюме", "Комментарий"],
        strict=True,
    ):
        cell.text = title
        cell.paragraphs[0].runs[0].bold = True
    for row in report.rows:
        cells = table.add_row().cells
        cells[0].text = row.requirement
        cells[1].text = "обязательное" if row.modality == Modality.must else "желательное"
        cells[2].text = STATUS_RU[row.status]
        _shade(cells[2], _STATUS_FILL[row.status])
        quotes = " … ".join(f"«{e.quote}» [{e.fragment_id}]" for e in row.resume_evidence)
        cells[3].text = quotes or "—"
        comment = row.comment
        if row.computed:
            comment += f" Расчёт: {row.computed}"
        cells[4].text = comment
    doc.add_paragraph(
        "Цитаты подставлены из исходных документов, номера в скобках — фрагменты "
        "резюме. Стаж и пороги посчитаны кодом."
    ).runs[0].italic = True

    _points(doc, "Сильные стороны", report.strengths)
    _points(doc, "Сверх требований", report.beyond_requirements)
    _points(doc, "Пробелы", report.gaps)
    _points(doc, "Что стоит уточнить", report.risks)
    if result.ranking and result.ranking.summary:
        doc.add_heading("Итог по всем вакансиям", level=2)
        doc.add_paragraph(result.ranking.summary)

    doc.add_page_break()
    doc.add_heading("Для рекрутера", level=1)
    doc.add_heading("Рекомендация", level=2)
    doc.add_paragraph(report.recruiter_recommendation)
    if report.questions:
        doc.add_heading("Вопросы кандидату", level=2)
        for q in report.questions:
            doc.add_paragraph(f"{q.text} — {q.why}", style="List Number")
    doc.add_heading("Черновик письма кандидату", level=2)
    for line in report.candidate_message.split("\n"):
        doc.add_paragraph(line)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
