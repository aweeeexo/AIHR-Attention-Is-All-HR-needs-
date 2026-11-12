"""Тип файла по сигнатуре, а не по расширению."""

from __future__ import annotations

import io
import zipfile
from typing import Literal

FileKind = Literal[
    "docx", "pdf", "rtf", "txt", "doc", "encrypted_office", "broken_zip", "zip", "image", "binary"
]

SUPPORTED_KINDS = {"docx", "pdf", "rtf", "txt"}
EXTENSION_KIND = {".docx": "docx", ".pdf": "pdf", ".rtf": "rtf", ".txt": "txt"}

_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_ENCRYPTED_PACKAGE = "EncryptedPackage".encode("utf-16-le")
_IMAGE_SIGNATURES = (
    b"\x89PNG",
    b"\xff\xd8\xff",
    b"GIF87a",
    b"GIF89a",
    b"BM",
    b"II*\x00",
    b"MM\x00*",
    b"RIFF",
)


def _looks_like_text(data: bytes) -> bool:
    sample = data[:16384]
    # NUL встречается только в бинарных файлах и в UTF-16 (у него есть BOM)
    if b"\x00" in sample and not sample.startswith((b"\xff\xfe", b"\xfe\xff")):
        return False
    from charset_normalizer import from_bytes

    best = from_bytes(sample).best()
    if best is None:
        return False
    text = str(best)
    if not text.strip():
        return True
    printable = sum(1 for ch in text if ch.isprintable() or ch in "\r\n\t")
    return printable / len(text) > 0.97


def sniff(data: bytes) -> FileKind:
    head = data[:8]
    if head.startswith(b"PK\x03\x04") or head.startswith(b"PK\x05\x06"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                names = set(zf.namelist())
        except (zipfile.BadZipFile, OSError, ValueError):
            return "broken_zip"
        return "docx" if "word/document.xml" in names else "zip"
    if head.startswith(_OLE):
        return "encrypted_office" if _ENCRYPTED_PACKAGE in data else "doc"
    if b"%PDF-" in data[:1024]:
        return "pdf"
    if data.lstrip()[:5] == b"{\\rtf":
        return "rtf"
    if head.startswith(_IMAGE_SIGNATURES):
        return "image"
    return "txt" if _looks_like_text(data) else "binary"
