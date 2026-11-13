"""Чтение форматов в последовательность блоков текста. Без нормализации и без ролей разделов."""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from typing import Any

from aihr.contracts import FragmentSource
from aihr.ingest.hidden import docx_run_hidden, hidden_warnings, pdf_char_hidden
from aihr.ingest.text import join_wrapped_lines

MAX_PDF_PAGES = 200


_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_NS = {
    "w": _W,
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
}
_TAG_P, _TAG_TBL, _TAG_SDT = f"{{{_W}}}p", f"{{{_W}}}tbl", f"{{{_W}}}sdt"
_TAG_T, _TAG_TAB, _TAG_BR, _TAG_CR = (f"{{{_W}}}{n}" for n in ("t", "tab", "br", "cr"))
_CONTAINERS = {f"{{{_W}}}{n}" for n in ("customXml", "ins", "smartTag", "sdtContent")}


def _xp(expr: str) -> Any:
    from lxml import etree

    return etree.XPath(expr, namespaces=_NS)


_XP_TEXT = _xp(".//*[self::w:t or self::w:tab or self::w:br or self::w:cr]")
_XP_BOXES_ABOVE = _xp("count(ancestor::w:txbxContent | ancestor::mc:Fallback)")
_XP_TEXTBOX = _xp(".//w:txbxContent[not(ancestor::mc:Fallback)]")
_XP_RUNS = _xp("./w:r | ./w:hyperlink/w:r")
_XP_RUN_TEXT = _xp(".//w:t/text()")
_XP_BOLD = _xp("./w:rPr/w:b")
_XP_NUMPR = _xp("./w:pPr/w:numPr")
_XP_CELLS = _xp("./w:tr/w:tc")
_XP_SDT_CONTENT = _xp("./w:sdtContent")


@dataclass
class Block:
    text: str
    source: FragmentSource
    list_item: bool = False
    heading_style: bool = False
    bold: bool = False


@dataclass
class ReadResult:
    blocks: list[Block]
    warnings: list[str]


# ---------- docx ----------


def _style_name(p: Any, doc: Any) -> str:
    from docx.text.paragraph import Paragraph

    try:
        style = Paragraph(p, doc).style
        return (style.name or "") if style is not None else ""
    except Exception:
        return ""


def _is_bold(p: Any) -> bool:
    runs = [r for r in _XP_RUNS(p) if "".join(_XP_RUN_TEXT(r))]
    if not runs:
        return False
    for r in runs:
        b = _XP_BOLD(r)
        if not b or b[0].get(f"{{{_W}}}val") in ("0", "false"):
            return False
    return True


def _paragraph_text(p: Any, hidden: list[tuple[str, str]] | None = None) -> str:
    parts: list[str] = []
    # Текст вложенных надписей и запасных копий (mc:Fallback) не берём: надписи читаются
    # отдельно. Сравниваем глубину, а не наличие предка — абзац сам может быть в надписи
    depth = _XP_BOXES_ABOVE(p)
    for node in _XP_TEXT(p):
        if _XP_BOXES_ABOVE(node) != depth:
            continue
        if node.tag == _TAG_T:
            reason = docx_run_hidden(node.getparent())
            if reason:  # невидимый человеку текст в анализ не берём (D52)
                if hidden is not None:
                    hidden.append((reason, node.text or ""))
                continue
            parts.append(node.text or "")
        elif node.tag == _TAG_TAB:
            parts.append(" ")
        else:
            parts.append("\n")
    return "".join(parts)


def _walk(
    container: Any,
    doc: Any,
    out: list[Block],
    source: FragmentSource,
    hidden: list[tuple[str, str]] | None = None,
) -> None:
    for child in container.iterchildren():
        tag = child.tag
        if tag == _TAG_P:
            style = _style_name(child, doc)
            numbered = bool(_XP_NUMPR(child))
            list_item = numbered or "List" in style or "Список" in style
            heading = style.startswith(("Heading", "Заголовок", "Title", "Название"))
            bold = _is_bold(child)
            # Ручные переносы строк внутри абзаца: продолжение предложения склеиваем
            for line in join_wrapped_lines(_paragraph_text(child, hidden).split("\n")):
                if line.strip():
                    out.append(Block(line, source, list_item, heading, bold))
            for box in _XP_TEXTBOX(child):
                _walk(box, doc, out, FragmentSource.textbox, hidden)
        elif tag == _TAG_TBL:
            for tc in _XP_CELLS(child):
                _walk(tc, doc, out, FragmentSource.table_cell, hidden)
        elif tag == _TAG_SDT or tag in _CONTAINERS:
            target = _XP_SDT_CONTENT(child) if tag == _TAG_SDT else [child]
            for node in target:
                _walk(node, doc, out, source, hidden)


def read_docx(data: bytes) -> ReadResult:
    import docx

    doc = docx.Document(io.BytesIO(data))
    hidden: list[tuple[str, str]] = []
    headers: list[Block] = []
    footers: list[Block] = []
    for section in doc.sections:
        for attr, target, src in (
            ("header", headers, FragmentSource.header),
            ("first_page_header", headers, FragmentSource.header),
            ("even_page_header", headers, FragmentSource.header),
            ("footer", footers, FragmentSource.footer),
            ("first_page_footer", footers, FragmentSource.footer),
            ("even_page_footer", footers, FragmentSource.footer),
        ):
            part = getattr(section, attr)
            if part.is_linked_to_previous:  # нет своего колонтитула; не создаём его
                continue
            _walk(part._element, doc, target, src, hidden)

    body: list[Block] = []
    _walk(doc.element.body, doc, body, FragmentSource.paragraph, hidden)

    def dedupe(blocks: list[Block]) -> list[Block]:
        seen: set[str] = set()
        uniq = []
        for b in blocks:
            key = b.text.strip()
            if key not in seen:
                seen.add(key)
                uniq.append(b)
        return uniq

    blocks = dedupe(headers) + body + dedupe(footers)
    for b in blocks:
        if b.source == FragmentSource.paragraph and b.list_item:
            b.source = FragmentSource.list_item
    return ReadResult(blocks, hidden_warnings(hidden))


# ---------- pdf ----------


def read_pdf(data: bytes) -> ReadResult:
    import pdfplumber

    warnings: list[str] = []
    lines: list[str] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        pages = pdf.pages
        if len(pages) > MAX_PDF_PAGES:
            warnings.append(f"Документ обрезан до {MAX_PDF_PAGES} страниц из {len(pages)}.")
            pages = pages[:MAX_PDF_PAGES]
        hidden: list[tuple[str, str]] = []
        for page in pages:
            width, height = float(page.width), float(page.height)
            page_hidden: dict[str, list[str]] = {}

            def visible(
                obj: dict[str, Any],
                w: float = width,
                h: float = height,
                found: dict[str, list[str]] = page_hidden,
            ) -> bool:
                if obj.get("object_type") != "char":
                    return True
                reason = pdf_char_hidden(obj, w, h)
                if reason:  # невидимый человеку текст в анализ не берём (D52)
                    found.setdefault(reason, []).append(obj.get("text") or "")
                    return False
                return True

            lines.extend((page.filter(visible).extract_text() or "").splitlines())
            hidden.extend((reason, "".join(chars)) for reason, chars in page_hidden.items())
            lines.append("")  # граница страницы — не склеиваем через неё
    warnings.extend(hidden_warnings(hidden))
    blocks = [Block(line, FragmentSource.pdf_line) for line in join_wrapped_lines(lines) if line]
    return ReadResult(blocks, warnings)


# ---------- txt и rtf ----------


def decode_text(data: bytes) -> str:
    from charset_normalizer import from_bytes

    best = from_bytes(data).best()
    return str(best) if best is not None else data.decode("utf-8", errors="replace")


def _lines_to_blocks(text: str) -> list[Block]:
    return [Block(line, FragmentSource.paragraph) for line in text.splitlines() if line.strip()]


def read_txt(data: bytes) -> ReadResult:
    return ReadResult(_lines_to_blocks(decode_text(data)), [])


_RTF_CODEPAGE = re.compile(r"\\ansicpg(\d+)")


def read_rtf(data: bytes) -> ReadResult:
    from striprtf.striprtf import rtf_to_text

    raw = data.decode("latin-1")
    m = _RTF_CODEPAGE.search(raw[:4000])
    encoding = f"cp{m.group(1)}" if m else "cp1252"
    try:
        "".encode(encoding)
    except LookupError:
        encoding = "cp1252"
    text = rtf_to_text(raw, encoding=encoding, errors="replace")
    return ReadResult(_lines_to_blocks(text), [])


READERS = {"docx": read_docx, "pdf": read_pdf, "txt": read_txt, "rtf": read_rtf}
