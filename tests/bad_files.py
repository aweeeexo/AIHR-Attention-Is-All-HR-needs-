"""Генератор плохих и нестандартных файлов для T01. Используют тесты и scripts/make_bad_files.py.

Каждый случай: имя файла, байты, ожидаемый код ошибки (или None) и подстрока предупреждения.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from dataclasses import dataclass

from aihr.contracts import DocKind, IngestErrorCode


@dataclass(frozen=True)
class BadFile:
    name: str
    make: Callable[[], bytes]
    kind: DocKind
    code: IngestErrorCode | None = None
    warning: str | None = None
    note: str = ""


# ---------- конструкторы ----------


def make_docx(
    paragraphs: list[str],
    table: list[list[str]] | None = None,
    header: str | None = None,
    textbox: str | None = None,
) -> bytes:
    import docx
    from docx.oxml import parse_xml

    d = docx.Document()
    for text in paragraphs:
        d.add_paragraph(text)
    if table:
        t = d.add_table(rows=len(table), cols=len(table[0]))
        for r, row in enumerate(table):
            for c, text in enumerate(row):
                t.cell(r, c).text = text
    if header:
        d.sections[0].header.paragraphs[0].text = header
    if textbox:
        box = parse_xml(
            '<w:r xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
            'xmlns:v="urn:schemas-microsoft-com:vml"><w:pict><v:shape><v:textbox>'
            f"<w:txbxContent><w:p><w:r><w:t>{textbox}</w:t></w:r></w:p></w:txbxContent>"
            "</v:textbox></v:shape></w:pict></w:r>"
        )
        d.add_paragraph()._p.append(box)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def make_pdf(lines: list[str]) -> bytes:
    """Минимальный PDF (латиница, Helvetica). Пустой список — страница без текста, как скан."""
    ops = ["BT", "/F1 12 Tf", "72 760 Td", "14 TL"]
    for line in lines:
        safe = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        ops.append(f"({safe}) Tj T*")
    ops.append("ET")
    stream = "\n".join(ops).encode("latin-1") if lines else b""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objects, 1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n".encode())
    out.write(f"startxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


def _zip_without_document() -> bytes:
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("xl/workbook.xml", "<workbook/>")
    return buf.getvalue()


_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64

RESUME_LINES = [
    "Кузнецова Мария",
    "Опыт работы",
    "2018 — 2024, клиника «Здоровье», медицинская сестра процедурного кабинета.",
    "Выполняла внутривенные инъекции, вела медицинскую документацию.",
    "Образование",
    "2018, медицинский колледж, сестринское дело.",
    "Навыки: забор крови, работа с медицинской информационной системой.",
]

PDF_RESUME = [
    "Work experience",
    "2019 - 2024 Logistics coordinator, Example Freight LLC.",
    "Planned routes for a fleet of 40 trucks and handled customs paperwork.",
    "Education",
    "2019 Bachelor of Transport Management.",
]

CONTRACT = (
    "ДОГОВОР ОКАЗАНИЯ УСЛУГ № 15\n"
    "г. Казань, 1 марта 2026 г.\n"
    "Общество с ограниченной ответственностью, именуемое в дальнейшем «Заказчик», и "
    "индивидуальный предприниматель, именуемый в дальнейшем «Исполнитель», заключили "
    "настоящий договор о нижеследующем.\n"
    "1. Предмет договора\n"
    "1.1. Исполнитель обязуется оказать услуги по уборке помещений, а Заказчик — оплатить их.\n"
    "2. Стоимость услуг и порядок расчётов\n"
    "2.1. Стоимость услуг составляет 50 000 рублей в месяц.\n"
)

PLAIN_VACANCY = (
    "Ищем водителя-экспедитора в сеть пекарен. Нужно развозить продукцию по точкам по утрам, "
    "иметь права категории C и стаж вождения от 3 лет, знать город. Работа 5/2, оплата "
    "раз в неделю, служебный автомобиль."
)

_BS = chr(92)  # обратная косая черта


def _rtf_unicode(text: str) -> str:
    return "".join(ch if ord(ch) < 128 else f"{_BS}u{ord(ch)}?" for ch in text)


def _rtf_cp1251(text: str) -> str:
    return "".join(ch if ord(ch) < 128 else f"{_BS}'{ch.encode('cp1251')[0]:02x}" for ch in text)


# Заголовки — байтами cp1251, остальное — escape-кодами Unicode: в rtf встречается и то и то
_PAR = f"{_BS}par "
RTF_RESUME = (
    f"{{{_BS}rtf1{_BS}ansi{_BS}ansicpg1251{_BS}deff0{{{_BS}fonttbl{{{_BS}f0 Arial;}}}}{_BS}f0 "
    + _rtf_cp1251("Опыт работы")
    + _PAR
    + _rtf_unicode("2020 - 2025 юрист в юридической фирме, вёл договорную работу и судебные дела.")
    + _PAR
    + _rtf_cp1251("Образование")
    + _PAR
    + _rtf_unicode("2020, юридический факультет.")
    + _PAR
    + "}"
)


def _long_resume() -> bytes:
    lines = ["Опыт работы"]
    for i in range(2500):
        lines.append(f"{2000 + i % 25} — {2001 + i % 25}: проект номер {i}, монтаж оборудования.")
    return "\n".join(lines).encode("utf-8")


def _truncated_pdf() -> bytes:
    full = make_pdf(PDF_RESUME)
    return full[: len(full) // 3]


BAD_FILES: list[BadFile] = [
    BadFile("zero_bytes.docx", lambda: b"", DocKind.resume, IngestErrorCode.empty_file),
    BadFile("empty.docx", lambda: make_docx([]), DocKind.resume, IngestErrorCode.no_text),
    BadFile(
        "broken_zip.docx",
        lambda: b"PK\x03\x04" + b"\x00junk" * 40,
        DocKind.resume,
        IngestErrorCode.corrupted,
    ),
    BadFile("picture.docx", lambda: _PNG, DocKind.resume, IngestErrorCode.type_mismatch),
    BadFile(
        "program.pdf",
        lambda: b"MZ\x90\x00" + b"\x00\x01" * 100,
        DocKind.vacancy,
        IngestErrorCode.type_mismatch,
    ),
    BadFile(
        "spreadsheet.docx", _zip_without_document, DocKind.vacancy, IngestErrorCode.type_mismatch
    ),
    BadFile(
        "password.docx",
        lambda: _OLE + "EncryptedPackage".encode("utf-16-le") + b"\x00" * 64,
        DocKind.resume,
        IngestErrorCode.encrypted,
    ),
    BadFile(
        "old_format.doc",
        lambda: _OLE + b"\x00" * 128,
        DocKind.resume,
        IngestErrorCode.unsupported_type,
    ),
    BadFile("scan.pdf", lambda: make_pdf([]), DocKind.resume, IngestErrorCode.no_text),
    BadFile("truncated.pdf", _truncated_pdf, DocKind.resume, IngestErrorCode.corrupted),
    BadFile("blank.txt", lambda: b"   \n\n\t  ", DocKind.vacancy, IngestErrorCode.no_text),
    BadFile(
        "archive.zip", _zip_without_document, DocKind.vacancy, IngestErrorCode.unsupported_type
    ),
    # ---------- читаются, иногда с предупреждением ----------
    BadFile(
        "resume_cp1251.txt",
        lambda: "\n".join(RESUME_LINES).encode("cp1251"),
        DocKind.resume,
        note="кодировка cp1251",
    ),
    BadFile(
        "resume_utf8_bom.txt",
        lambda: "\n".join(RESUME_LINES).encode("utf-8-sig"),
        DocKind.resume,
        note="UTF-8 с BOM",
    ),
    BadFile(
        "resume_utf16.txt",
        lambda: "\n".join(RESUME_LINES).encode("utf-16"),
        DocKind.resume,
        note="UTF-16",
    ),
    BadFile(
        "resume_two_columns.docx",
        lambda: make_docx(
            [],
            table=[
                ["Опыт работы", RESUME_LINES[2]],
                ["", RESUME_LINES[3]],
                ["Образование", RESUME_LINES[5]],
                ["Навыки", "Забор крови, работа с медицинской информационной системой."],
            ],
        ),
        DocKind.resume,
        note="резюме таблицей в две колонки",
    ),
    BadFile(
        "resume_header_textbox.docx",
        lambda: make_docx(
            RESUME_LINES[1:6],
            header="Кузнецова Мария, телефон +7 900 111-22-33",
            textbox="Навыки: забор крови, медицинская информационная система",
        ),
        DocKind.resume,
        note="контакты в колонтитуле, навыки в надписи",
    ),
    BadFile("resume.rtf", lambda: RTF_RESUME.encode("latin-1"), DocKind.resume, note="rtf"),
    BadFile("resume.pdf", lambda: make_pdf(PDF_RESUME), DocKind.resume, note="pdf"),
    BadFile(
        "resume_named_pdf.docx",
        lambda: make_pdf(PDF_RESUME),
        DocKind.resume,
        warning="не совпадает с содержимым",
        note="pdf с расширением docx",
    ),
    BadFile(
        "vacancy_plain_text.txt",
        lambda: PLAIN_VACANCY.encode("utf-8"),
        DocKind.vacancy,
        warning="не найдены разделы требований",
        note="вакансия сплошным текстом",
    ),
    BadFile(
        "resume_long.txt",
        _long_resume,
        DocKind.resume,
        warning="обрезан до 2000",
        note="очень длинное резюме",
    ),
    BadFile(
        "contract_instead_of_resume.txt",
        lambda: CONTRACT.encode("utf-8"),
        DocKind.resume,
        warning="не похож на резюме",
        note="вместо резюме загружен договор",
    ),
]
