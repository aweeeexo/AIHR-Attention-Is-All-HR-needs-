# Плохие и нестандартные файлы

Сгенерированы `scripts/make_bad_files.py`.

| Файл | Как загружать | Ожидаем |
|---|---|---|
| `zero_bytes.docx` | resume | E_EMPTY_FILE  |
| `empty.docx` | resume | E_NO_TEXT  |
| `broken_zip.docx` | resume | E_CORRUPTED  |
| `picture.docx` | resume | E_TYPE_MISMATCH  |
| `program.pdf` | vacancy | E_TYPE_MISMATCH  |
| `spreadsheet.docx` | vacancy | E_TYPE_MISMATCH  |
| `password.docx` | resume | E_ENCRYPTED  |
| `old_format.doc` | resume | E_UNSUPPORTED_TYPE  |
| `scan.pdf` | resume | E_NO_TEXT  |
| `truncated.pdf` | resume | E_CORRUPTED  |
| `blank.txt` | vacancy | E_NO_TEXT  |
| `archive.zip` | vacancy | E_UNSUPPORTED_TYPE  |
| `resume_cp1251.txt` | resume | читается — кодировка cp1251 |
| `resume_utf8_bom.txt` | resume | читается — UTF-8 с BOM |
| `resume_utf16.txt` | resume | читается — UTF-16 |
| `resume_two_columns.docx` | resume | читается — резюме таблицей в две колонки |
| `resume_header_textbox.docx` | resume | читается — контакты в колонтитуле, навыки в надписи |
| `resume.rtf` | resume | читается — rtf |
| `resume.pdf` | resume | читается — pdf |
| `resume_named_pdf.docx` | resume | предупреждение «не совпадает с содержимым» — pdf с расширением docx |
| `vacancy_plain_text.txt` | vacancy | предупреждение «не найдены разделы требований» — вакансия сплошным текстом |
| `resume_long.txt` | resume | предупреждение «обрезан до 2000» — очень длинное резюме |
| `resume_hidden_text.docx` | resume | предупреждение «Скрытый текст» — белый шрифт, кегль 1 pt и скрытый формат с командой для ИИ (D52) |
| `resume_hidden_text.pdf` | resume | предупреждение «Скрытый текст» — белый текст и кегль 1 pt в pdf (D52) |
| `contract_instead_of_resume.txt` | resume | предупреждение «не похож на резюме» — вместо резюме загружен договор |
