# syntax=docker/dockerfile:1.7
# Многоступенчатая сборка: uv ставит зависимости в первом этапе, в итоговый образ попадает .venv.
# Эмбеддинги (sentence-transformers + torch CPU, D19) включены по умолчанию (D42).
# Образ без них (меньше на ~2,5 ГБ, только BM25): WITH_EMBEDDINGS=0 docker compose up --build

ARG PYTHON_IMAGE=python:3.12.16-slim-trixie

FROM ghcr.io/astral-sh/uv:0.12.21 AS uv

# ---------- 1. Зависимости и пакет ----------
FROM ${PYTHON_IMAGE} AS builder
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app
ARG WITH_EMBEDDINGS=1

# Сначала только зависимости: слой кэшируется, пока не меняется uv.lock
COPY pyproject.toml uv.lock .python-version README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    if [ "$WITH_EMBEDDINGS" = "1" ]; then extra="--extra embeddings"; else extra=""; fi; \
    uv sync --frozen --no-dev --no-install-project $extra

COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    if [ "$WITH_EMBEDDINGS" = "1" ]; then extra="--extra embeddings"; else extra=""; fi; \
    uv sync --frozen --no-dev --no-editable $extra

# ---------- 2. Тесты в Linux-контейнере: docker build --target test ----------
FROM builder AS test
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-editable
COPY config ./config
COPY data/case ./data/case
COPY data/synonyms.yaml ./data/synonyms.yaml
COPY examples ./examples
COPY scripts ./scripts
COPY tests ./tests
COPY ui ./ui
ENV PATH=/app/.venv/bin:$PATH PYTHONUTF8=1
CMD ["pytest", "-q"]

# ---------- 3. Итоговый образ ----------
FROM ${PYTHON_IMAGE} AS runtime
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUTF8=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/app/models
RUN groupadd --system --gid 1000 app \
    && useradd --system --uid 1000 --gid app --home-dir /app --shell /usr/sbin/nologin app
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY config ./config
COPY ui ./ui
COPY data/case ./data/case
COPY data/synonyms.yaml ./data/synonyms.yaml
COPY examples ./examples

# Модели — на этапе сборки, а не при первом запросе
RUN python -m aihr.warmup \
    && mkdir -p /app/data/runs /app/data/cache \
    && chown -R app:app /app/data
ENV HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1

USER app
EXPOSE 8000 8501
HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"]
CMD ["uvicorn", "aihr.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
