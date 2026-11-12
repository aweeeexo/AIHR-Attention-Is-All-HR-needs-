"""Загрузка документов: байты → Document с фрагментами.

T00: минимальный разбор (txt, docx с таблицами, pdf построчно) и базовые коды ошибок.
T01: сигнатуры файлов, разделы, колонтитулы, текстовые поля, rtf, полная лестница проверок.
"""

from __future__ import annotations

import hashlib
import io
import logging
from pathlib import Path

from aihr.config import get_settings
from aihr.contracts import (
    DocKind,
    Document,
    Fragment,
    FragmentSource,
    IngestError,
    IngestErrorCode,
    IngestFailure,
)

log = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = (".docx", ".pdf", ".txt")


def _fail(code: IngestErrorCode, filename: str, message: str, hint: str) -> IngestFailure:
    return IngestFailure(IngestError(code=code, filename=filename, message=message, hint=hint))


def _lines_txt(data: bytes) -> list[tuple[str, FragmentSource]]:
    from charset_normalizer import from_bytes

    best = from_bytes(data).best()
    text = str(best) if best is not None else data.decode("utf-8", errors="replace")
    return [(line, FragmentSource.paragraph) for line in text.splitlines()]


def _lines_docx(data: bytes) -> list[tuple[str, FragmentSource]]:
    import docx

    d = docx.Document(io.BytesIO(data))
    out: list[tuple[str, FragmentSource]] = []
    for para in d.paragraphs:
        style = (para.style.name if para.style is not None else "") or ""
        source = FragmentSource.list_item if "List" in style else FragmentSource.paragraph
        out.append((para.text, source))
    for table in d.tables:
        for row in table.rows:
            seen: set[int] = set()
            for cell in row.cells:
                if id(cell._tc) in seen:  # объединённые ячейки повторяются
                    continue
                seen.add(id(cell._tc))
                out.append((cell.text, FragmentSource.table_cell))
    return out


def _lines_pdf(data: bytes) -> list[tuple[str, FragmentSource]]:
    import pdfplumber

    out: list[tuple[str, FragmentSource]] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            for line in (page.extract_text() or "").splitlines():
                out.append((line, FragmentSource.pdf_line))
    return out


_READERS = {".txt": _lines_txt, ".docx": _lines_docx, ".pdf": _lines_pdf}


def _normalize(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").split())


def load_document(data: bytes, filename: str, kind: DocKind, doc_id: str) -> Document:
    """Raises IngestFailure(IngestError) — пайплайн кладёт ошибку в MatchResult.errors."""
    settings = get_settings()
    if not data:
        raise _fail(
            IngestErrorCode.empty_file,
            filename,
            "Файл пустой.",
            "Проверьте, что выбран нужный файл.",
        )
    if len(data) > settings.max_file_bytes:
        raise _fail(
            IngestErrorCode.too_large,
            filename,
            f"Файл больше {settings.max_file_mb:g} МБ.",
            "Уменьшите файл или увеличьте MAX_FILE_MB.",
        )
    ext = Path(filename).suffix.lower()
    reader = _READERS.get(ext)
    if reader is None:
        raise _fail(
            IngestErrorCode.unsupported_type,
            filename,
            f"Формат {ext or 'без расширения'} не поддерживается.",
            "Сохраните документ в docx, pdf или txt.",
        )
    try:
        raw_lines = reader(data)
    except Exception as exc:
        log.info("%s: не удалось прочитать (%s)", doc_id, type(exc).__name__)
        raise _fail(
            IngestErrorCode.corrupted,
            filename,
            "Файл повреждён или не читается.",
            "Откройте файл и пересохраните его в docx или pdf.",
        ) from exc

    prefix = "R" if kind == DocKind.resume else f"{doc_id}."
    fragments: list[Fragment] = []
    for text, source in raw_lines:
        clean = _normalize(text)
        if not clean:
            continue
        n = len(fragments) + 1
        fragments.append(
            Fragment(
                id=f"{prefix}{n}",
                order=n,
                section=None,
                section_role=None,
                source=source,
                text=clean,
            )
        )
    if not fragments:
        raise _fail(
            IngestErrorCode.no_text,
            filename,
            "В документе нет текста.",
            "Если это скан, сохраните документ с текстовым слоем.",
        )

    normalized = "\n".join(f.text for f in fragments)
    content_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]
    title = fragments[0].text[:200] if kind == DocKind.vacancy else None
    return Document(
        id=doc_id,
        content_hash=content_hash,
        kind=kind,
        filename=filename,
        title=title,
        fragments=fragments,
    )
