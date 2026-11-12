"""Словарь ошибок загрузки: код → текст для пользователя и подсказка. Без трассировок."""

from __future__ import annotations

from aihr.contracts import IngestError, IngestErrorCode, IngestFailure

_MESSAGES: dict[IngestErrorCode, tuple[str, str]] = {
    IngestErrorCode.empty_file: (
        "Файл пустой.",
        "Проверьте, что выбран нужный файл.",
    ),
    IngestErrorCode.too_large: (
        "Файл слишком большой.",
        "Уменьшите файл или увеличьте MAX_FILE_MB.",
    ),
    IngestErrorCode.unsupported_type: (
        "Формат файла не поддерживается.",
        "Сохраните документ в docx, pdf, rtf или txt.",
    ),
    IngestErrorCode.type_mismatch: (
        "Расширение файла не совпадает с содержимым.",
        "Похоже, файл переименован. Сохраните документ в docx, pdf, rtf или txt.",
    ),
    IngestErrorCode.corrupted: (
        "Файл повреждён или не читается.",
        "Откройте файл и пересохраните его в docx или pdf.",
    ),
    IngestErrorCode.encrypted: (
        "Файл защищён паролем.",
        "Снимите пароль или пересохраните документ в docx без защиты.",
    ),
    IngestErrorCode.no_text: (
        "В документе нет текста.",
        "Если это скан, нужен файл с текстовым слоем (docx или pdf с текстом).",
    ),
    IngestErrorCode.no_requirements: (
        "Из вакансии не извлечено ни одного требования.",
        "Проверьте, что в файле есть требования к кандидату.",
    ),
}


def make_error(
    code: IngestErrorCode, filename: str, message: str | None = None, hint: str | None = None
) -> IngestError:
    default_message, default_hint = _MESSAGES[code]
    return IngestError(
        code=code,
        filename=filename,
        message=message or default_message,
        hint=hint or default_hint,
    )


def fail(
    code: IngestErrorCode, filename: str, message: str | None = None, hint: str | None = None
) -> IngestFailure:
    return IngestFailure(make_error(code, filename, message, hint))
