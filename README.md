# AIHR — сопоставление резюме с вакансиями

Команда AIHR («Attention Is All HR Needs»), хакатон «ИИ в системе управления МФТИ», трек 3.

На входе одно резюме и набор вакансий (docx, pdf, txt). На выходе:

- рейтинг вакансий по соответствию кандидату с объяснением места каждой;
- для каждой вакансии таблица «требование · подтверждение в резюме · статус · комментарий» с четырьмя статусами: «Соответствует», «Частично», «Не соответствует», «Не указано»;
- сильные стороны, пробелы и риски, рекомендация рекрутеру и вопросы кандидату.

Выводы опираются только на текст документов. Цитаты подставляет код из исходного документа, а не модель. Балл и рейтинг считает код по одной формуле (`config/scoring.yaml`).

> Статус: каркас (T00). Модули извлечения и сопоставления пока заглушки: результат валиден по схеме, но смысла в нём нет. Полный README — в T12.

## Быстрый старт (Docker)

Нужны Docker 24+ и Docker Compose 2.24+.

```bash
cp .env.example .env          # вписать LLM_BASE_URL, LLM_API_KEY, LLM_MODEL; без них — режим без LLM
docker compose up --build     # или: make up
```

- UI: <http://localhost:8501>, кнопка «Пример из кейса».
- API: <http://localhost:8000>, документация — <http://localhost:8000/docs>.

Остановить: `docker compose down` (или `make down`).

Проверка одной командой: `make demo` прогоняет пример из `data/case/` в контейнере и сверяет результат со схемой.

## Команды

| Что | Linux, macOS | Windows |
|---|---|---|
| Поднять API и UI | `make up` | `uv run poe up` |
| Остановить | `make down` | `uv run poe down` |
| Пример в контейнере + проверка | `make demo` | `uv run poe demo` |
| Тесты | `make test` | `uv run poe test` |
| Тесты в Linux-контейнере | `make test-docker` | `uv run poe test-docker` |
| Линтер | `make lint` | `uv run poe lint` |
| Слова из вакансий кейса в коде | `make check-leak` | `uv run poe check-leak` |
| Метрики на золотом наборе | `make eval` | `uv run poe eval` |

`make up`, `make down`, `make demo` и `make test-docker` требуют только Docker. Остальные цели — [uv](https://docs.astral.sh/uv/).

### Без Docker

```bash
uv sync                                    # Python 3.12 и зависимости из uv.lock
uv run poe serve                           # API на :8000
uv run poe ui                              # UI на :8501 (в другом терминале)
uv run aihr match --resume data/case/<резюме>.docx --vacancies data/case/
uv run aihr demo                           # пример из кейса + проверка результата
```

Если `--vacancies` — папка, из неё берутся docx, pdf и txt, кроме файлов со словами «резюме», «resume» или «cv» в имени.

## API

| Метод | Путь | Что делает |
|---|---|---|
| GET | `/health` | `{"status": "ok", "llm": "configured" \| "none", "contracts_version": 1}` |
| POST | `/match` | multipart: `resume` (один файл), `vacancies` (несколько) → `MatchResult` |
| POST | `/match/example` | прогон на `data/case/` → `MatchResult`; `?resume=<часть имени>` выбирает резюме |
| GET | `/example/files` | файлы примера |
| GET | `/runs/{run_id}` | сохранённый результат прогона |
| GET | `/runs/{run_id}/outbound` | журнал запросов к внешней LLM |

```bash
curl -F resume=@resume.docx -F vacancies=@v1.docx -F vacancies=@v2.pdf localhost:8000/match
```

## Настройки

Все настройки — переменные окружения или `.env` (пример — `.env.example`).

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `LLM_PROVIDER` | `openai_compatible` | `openai_compatible` или `none` (режим без LLM) |
| `LLM_BASE_URL` | — | Адрес OpenAI-совместимого API |
| `LLM_API_KEY` | — | Ключ. Не попадает ни в лог, ни в результат |
| `LLM_MODEL` | — | Имя модели |
| `LLM_PROJECT` | — | ID проекта или каталога (Yandex AI Studio) |
| `LLM_TIMEOUT_S` | `60` | Таймаут запроса, с |
| `LLM_MAX_RETRIES` | `3` | Повторы при сетевых ошибках |
| `LLM_CONCURRENCY` | `4` | Параллельных запросов |
| `WITH_EMBEDDINGS` | `0` | `1` — собрать образ с sentence-transformers и torch (CPU) |
| `EMBEDDINGS_MODEL` | `intfloat/multilingual-e5-small` | Пусто — эмбеддинги выключены |
| `MAX_FILE_MB` | `10` | Лимит размера файла |
| `RUNS_DIR` | `data/runs` | Результаты прогонов и журнал исходящих |
| `TODAY` | — | «Сегодня» для расчёта стажа, `ГГГГ-ММ` |
| `LOG_LEVEL` | `INFO` | Уровень логов |

Без `LLM_BASE_URL` и `LLM_MODEL` решение работает в режиме без LLM и пишет об этом предупреждение в результат.

## Зависимости

Python 3.12. Все версии закреплены в `pyproject.toml` и `uv.lock`. torch (только для эмбеддингов, extra `embeddings`) ставится из CPU-индекса PyTorch: CUDA не нужна.

## Архитектура

```
1. Вход — локально, без LLM: загрузка и проверка файла → фрагменты с адресами → маскирование ПДн
2. Извлечение — LLM со строгой JSON-схемой: требования вакансии (must / nice), профиль кандидата
3. Сопоставление — по каждому требованию: фрагмент резюме или «Не указано»
4. Результат — собирает код: балл и рейтинг → отчёт рекрутеру → API, UI, JSON
```

Подробное описание модулей и потока данных — в T12.
