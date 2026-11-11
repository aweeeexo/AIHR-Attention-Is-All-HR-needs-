# T00. Каркас: репозиторий, Docker, заглушки

**Владелец:** B · **Зависит от:** — · **Критерии:** 6 (8 баллов за Docker, основа для всего) · **Веха:** M0, 12.11 до 12:00

## Цель

Сквозной прогон на заглушках: `docker compose up` поднимает API и UI, загрузка файлов возвращает `MatchResult`, который проходит валидацию по контрактам. После этого A и B работают параллельно и заменяют заглушки настоящими модулями.

## Шаги

1. **Репозиторий.** Структура из `CLAUDE.md`. `uv init --package`, Python 3.12, файл `.python-version`. В папке уже есть файлы от PyCharm: `main.py`-образец удалить, `.venv` на 3.14 uv пересоздаст сам. `.gitignore` уже лежит в корне — дополнить, если нужно. `.gitattributes` с `* text=auto eol=lf` тоже уже есть (D19).
2. **Зависимости** в `pyproject.toml` с закреплёнными версиями: pydantic, pydantic-settings, fastapi, uvicorn, python-multipart, streamlit, httpx, openai, python-docx, pdfplumber, charset-normalizer, natasha, rank-bm25, snowballstemmer, diskcache, pyyaml, jinja2, typer. Dev: pytest, ruff, poethepoet. `sentence-transformers` и torch вынести в extra `embeddings`. torch брать из CPU-индекса PyTorch через `[[tool.uv.index]]` с `explicit = true` и `[tool.uv.sources]`, чтобы ни на Windows, ни в образе не тянулась CUDA (D19).
3. **Контракты.** Перенести `docs/contracts.md` в `src/aihr/contracts.py` один в один. Тест: каждая модель строится из примера и сериализуется туда и обратно.
4. **Конфиг.** `config.py` на pydantic-settings. Все настройки из окружения:

   | Переменная | По умолчанию | Назначение |
   |---|---|---|
   | `LLM_PROVIDER` | `openai_compatible` | `openai_compatible` или `none` (режим без LLM) |
   | `LLM_BASE_URL` | — | Адрес OpenAI-совместимого API |
   | `LLM_API_KEY` | — | Ключ |
   | `LLM_MODEL` | — | Имя модели |
   | `LLM_PROJECT` | — | ID проекта или каталога для провайдеров, которым он нужен (Yandex AI Studio). Передаётся в `openai.OpenAI(project=...)`. Пусто — не передаётся |
   | `LLM_TIMEOUT_S` | `60` | Таймаут запроса |
   | `LLM_MAX_RETRIES` | `3` | Повторы при сетевых ошибках |
   | `LLM_CONCURRENCY` | `4` | Параллельных запросов |
   | `EMBEDDINGS_MODEL` | `intfloat/multilingual-e5-small` | Пусто — эмбеддинги выключены |
   | `MAX_FILE_MB` | `10` | Лимит размера файла |
   | `RUNS_DIR` | `data/runs` | Результаты и журнал исходящих |
   | `TODAY` | — | Фиксированная дата для воспроизводимых тестов (`2026-11`) |
   | `LOG_LEVEL` | `INFO` | |

   Плюс `config/scoring.yaml` для весов и порогов (T08).

5. **Заглушки модулей.** Функции из раздела «Интерфейсы модулей» в `docs/contracts.md` с правильными сигнатурами. Возвращают правдоподобные данные: 3 требования на вакансию, по одному каждого статуса, фрагменты с реальными id. Цель — валидный `MatchResult`, а не смысл.
6. **Минимальный LLM-клиент** `llm/client.py` с финальным интерфейсом `structured(prompt_id, variables, schema)`. Внутри: загрузка промпта из файла, подстановка переменных, вызов через `openai` SDK с `base_url`, разбор JSON, валидация pydantic. Без guard и кэша — их добавит T03. **A начинает работать именно с ним, поэтому это первые полчаса задачи.**
7. **Оркестратор** `pipeline.run()`: загрузка → маскирование → извлечение → сопоставление → балл → рейтинг → отчёт. Каждый шаг в `try`, ошибка документа попадает в `MatchResult.errors`, прогон продолжается. Время шагов в `timings_ms`. Результат сохраняется в `data/runs/<run_id>/result.json`.
8. **API** (FastAPI):
   - `GET /health` → `{"status": "ok", "llm": "configured" | "none", "contracts_version": 1}`
   - `POST /match` — multipart: `resume` (один файл), `vacancies` (несколько) → `MatchResult`
   - `POST /match/example` — прогон на `data/case/` → `MatchResult`
   - `GET /runs/{run_id}/outbound` — журнал исходящих запросов (заглушка до T02)
9. **CLI** (typer): `aihr match --resume <файл> --vacancies <папка или файлы> [--out result.json]`. Плюс команды отладки для A: `extract-requirements <файл>`, `extract-profile <файл>`.
10. **UI-заглушка** (Streamlit): загрузка файлов, кнопка «Пример из кейса», вывод JSON результата. Полный UI — в T12.
11. **Docker.**
    - `Dockerfile`: многоступенчатая сборка на `python:3.12-slim` с uv, `uv sync --frozen --no-dev`, пользователь не root, `HEALTHCHECK` на `/health`. Модели Natasha (и эмбеддингов, если включены) скачиваются на этапе сборки, а не при первом запросе.
    - `docker-compose.yml`: сервисы `api` (8000) и `ui` (8501, зависит от `api` по `condition: service_healthy`). `env_file: .env`. Том для `data/runs`. Профиль `local` с сервисом локальной LLM (Ollama или любой OpenAI-совместимый сервер) — пока закомментирован, включается в T03.
    - `.dockerignore`: `.git`, `.env`, `data/runs`, `scratch`, `.venv`.
12. **Команды.** Задачи poethepoet в `pyproject.toml` (`[tool.poe.tasks]`): `up`, `down`, `test`, `lint`, `eval`, `demo`, `check-leak`. Makefile с теми же целями, каждая вызывает `uv run poe <цель>`. На Windows запускаем `uv run poe test`, на Linux и у жюри — `make test` или прямые команды из README. Скрипты пишем на Python, а не на bash, чтобы они работали на обеих системах.
13. **check-leak.** Скрипт ищет в `src/` (код и промпты) слова из вакансий кейса. Список стоп-слов в `scripts/leak_words.txt` — заполняется по факту из трёх вакансий (должности, ключевые термины). Ненулевой результат — ошибка. `data/synonyms.yaml` не проверяется: это общий словарь по многим областям, и учётные или ИТ-термины в нём законны.
14. **Тесты:** контракты, `/health`, `/match/example` на заглушках возвращает валидный `MatchResult`.
15. **README-скелет:** что это, быстрый старт (`cp .env.example .env`, `docker compose up --build`, адреса API и UI), команды для Windows и Linux. Полный README — в T12, но запуск описан с первого дня.
16. **Docker на Windows.** Проверить `docker version`. Если Docker Desktop не установлен или не запущен — сказать пользователю и пока проверять всё через `uv run`, а сборку образа сделать, когда он запустит Docker.

## Критерии готовности

- [ ] В чистом клоне `cp .env.example .env && make up` (на Windows `uv run poe up`) поднимает оба сервиса без ручных правок.
- [ ] `uv run poe test` зелёный на Windows, `make test` — в Linux-контейнере.
- [ ] `http://localhost:8501` → «Пример из кейса» → на экране валидный JSON.
- [ ] `curl -F resume=@... -F vacancies=@... localhost:8000/match` возвращает `MatchResult`.
- [ ] `make test` зелёный.
- [ ] A может вызвать `LLMClient().structured(...)` со своим промптом и получить pydantic-объект.
- [ ] Время сборки образа записано в `docs/decisions.md` (нужно для решения по эмбеддингам).

## Не делаем

- Настоящий разбор документов (T01), маскирование (T02), кэш (T03).
- Базу данных и векторное хранилище: документов мало, хватает памяти и файлового кэша.
