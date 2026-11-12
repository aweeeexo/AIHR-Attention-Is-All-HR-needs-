"""Загрузка документов: байты → Document с фрагментами и ролями разделов, или IngestFailure.

Лестница проверок (T01): пустой → размер → тип по сигнатуре → пароль и старый .doc →
совпадение расширения → чтение без исключений → есть ли текст → похоже ли на нужный документ.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from aihr.config import get_settings
from aihr.contracts import DocKind, Document, IngestErrorCode, IngestFailure
from aihr.ingest.detect import EXTENSION_KIND, SUPPORTED_KINDS, sniff
from aihr.ingest.errors import fail, make_error
from aihr.ingest.filenames import fix_filename
from aihr.ingest.readers import READERS
from aihr.ingest.sections import build_fragments, find_title, kind_warnings

__all__ = ["SUPPORTED_EXTENSIONS", "fix_filename", "load_document", "make_error"]

log = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = (".docx", ".pdf", ".rtf", ".txt")
MIN_TEXT_CHARS = 50

_KIND_RU = {
    "docx": "документ Word",
    "pdf": "PDF",
    "rtf": "RTF",
    "txt": "текст",
    "image": "картинка",
    "zip": "архив",
    "binary": "двоичные данные",
}


def _is_encryption_error(exc: BaseException) -> bool:
    seen: BaseException | None = exc
    while seen is not None:
        name = type(seen).__name__.lower()
        if "password" in name or "encrypt" in name:
            return True
        seen = seen.__cause__ or seen.__context__
    return False


def load_document(data: bytes, filename: str, kind: DocKind, doc_id: str) -> Document:
    """Raises IngestFailure(IngestError) — пайплайн кладёт ошибку в MatchResult.errors."""
    settings = get_settings()
    if not data:
        raise fail(IngestErrorCode.empty_file, filename)
    if len(data) > settings.max_file_bytes:
        raise fail(
            IngestErrorCode.too_large,
            filename,
            f"Файл больше {settings.max_file_mb:g} МБ ({len(data) / 1024 / 1024:.1f} МБ).",
        )

    ext = Path(filename).suffix.lower()
    content = sniff(data)
    if content == "encrypted_office":
        raise fail(IngestErrorCode.encrypted, filename)
    if content == "doc":
        raise fail(
            IngestErrorCode.unsupported_type,
            filename,
            "Старый формат Word (.doc) не поддерживается.",
            "Откройте файл в Word и сохраните как .docx.",
        )
    if content == "broken_zip":
        raise fail(IngestErrorCode.corrupted, filename)
    if content not in SUPPORTED_KINDS:
        if ext in EXTENSION_KIND:
            raise fail(
                IngestErrorCode.type_mismatch,
                filename,
                f"Файл называется {ext}, но внутри {_KIND_RU.get(content, content)}.",
            )
        raise fail(IngestErrorCode.unsupported_type, filename)

    warnings: list[str] = []
    expected = EXTENSION_KIND.get(ext)
    if expected != content:
        warnings.append(
            f"Расширение «{ext or 'нет'}» не совпадает с содержимым: файл прочитан как "
            f"{_KIND_RU[content]}."
        )

    try:
        read = READERS[content](data)
    except IngestFailure:
        raise
    except Exception as exc:
        log.info("%s: не удалось прочитать %s (%s)", doc_id, content, type(exc).__name__)
        if _is_encryption_error(exc):
            raise fail(IngestErrorCode.encrypted, filename) from exc
        raise fail(IngestErrorCode.corrupted, filename) from exc
    warnings.extend(read.warnings)

    fragments, frag_warnings = build_fragments(read.blocks, kind, doc_id)
    warnings.extend(frag_warnings)
    if sum(len(f.text) for f in fragments) < MIN_TEXT_CHARS:
        hint = (
            "Похоже на скан: нужен файл с текстовым слоем (docx или pdf с текстом)."
            if content == "pdf"
            else "Проверьте, что в документе есть текст."
        )
        raise fail(IngestErrorCode.no_text, filename, hint=hint)
    warnings.extend(kind_warnings(fragments, kind))

    normalized = "\n".join(f.text for f in fragments)
    content_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]
    return Document(
        id=doc_id,
        content_hash=content_hash,
        kind=kind,
        filename=filename,
        title=find_title(fragments) if kind == DocKind.vacancy else None,
        fragments=fragments,
        warnings=warnings,
    )
