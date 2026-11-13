#!/usr/bin/env bash
# Проверка «как у жюри» (T12): чистый клон → .env из примера → сборка и запуск → health →
# пример из кейса через React-прокси → use cases в контейнере → остановка и уборка.
# Нужны git, Docker и curl. При конфликте задайте API_PORT, UI_PORT и FRONTEND_PORT.
#
#   bash scripts/clean_check.sh [репозиторий] [ветка или тег]
set -euo pipefail

REPO=${1:-https://github.com/aweeeexo/AIHR-Attention-Is-All-HR-needs-.git}
REF=${2:-main}
PROJECT=aihr-clean
DIR=$(mktemp -d)
API_URL="http://localhost:${API_PORT:-8000}"
STREAMLIT_URL="http://localhost:${UI_PORT:-8501}"
FRONTEND_URL="http://localhost:${FRONTEND_PORT:-3000}"

cleanup() {
  if [ -d "$DIR/aihr" ]; then
    (cd "$DIR/aihr" && docker compose -p "$PROJECT" down -v --remove-orphans >/dev/null 2>&1) || true
  fi
  rm -rf "$DIR"
}
trap cleanup EXIT

step() { printf '\n== %s\n' "$1"; }

step "клон $REF в $DIR"
git clone --quiet --depth 1 --branch "$REF" "$REPO" "$DIR/aihr"
cd "$DIR/aihr"
cp .env.example .env

step "сборка и запуск (docker compose up --build --wait)"
started=$(date +%s)
docker compose -p "$PROJECT" up --build --wait --wait-timeout 240
echo "собрано и запущено за $(( $(date +%s) - started )) с"

step "состояние API и обоих интерфейсов"
curl -fsS "$API_URL/health"
echo
curl -fsS "$STREAMLIT_URL/_stcore/health"
echo
curl -fsS "$FRONTEND_URL/" | grep -q '<div id="root">'
curl -fsS "$FRONTEND_URL/api/health"
echo

step "пример из кейса через React-прокси"
curl -fsS --max-time 720 -o /dev/null -X POST "$FRONTEND_URL/api/match/example"
echo "POST /api/match/example: 200"

step "use cases в контейнере (aihr demo)"
docker compose -p "$PROJECT" run --rm api aihr demo

printf '\nчистый запуск: всё в порядке (%s с)\n' "$(( $(date +%s) - started ))"
