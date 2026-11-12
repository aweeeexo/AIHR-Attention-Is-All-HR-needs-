"""Имя файла из multipart. Некоторые клиенты (curl в Windows) шлют его в cp1251, а сервер
читает байты как latin-1: «Вакансия» превращается в «Âàêàíñèÿ». Возвращаем как было.
"""

from __future__ import annotations


def fix_filename(name: str) -> str:
    try:
        raw = name.encode("latin-1")
    except UnicodeEncodeError:
        return name  # уже нормальный Unicode
    high = sum(1 for b in raw if b >= 0x80)
    if not high:
        return name
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    letters = sum(1 for ch in name if ch.isalpha())
    # Русское имя почти целиком из «высоких» байтов; «café.docx» или «Müller.pdf» — нет
    if high >= 3 and high >= letters / 2:
        decoded = raw.decode("cp1251", errors="replace")
        cyrillic = sum(1 for ch in decoded if "Ѐ" <= ch <= "ӿ")
        if cyrillic >= high * 0.8:
            return decoded
    return name
