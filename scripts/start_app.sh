#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export UV_CACHE_DIR="${UV_CACHE_DIR:-$ROOT_DIR/.uv_cache}"
BACKEND_HOST="${SEGMENTATION_CHECKER_HOST:-127.0.0.1}"
BACKEND_PORT="${SEGMENTATION_CHECKER_DEV_PORT:-8016}"
FRONTEND_PORT="${SEGMENTATION_CHECKER_FRONTEND_PORT:-5176}"

cd "$ROOT_DIR"

cleanup() {
  if [[ -n "${BACKEND_PID:-}" ]]; then
    kill "$BACKEND_PID" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

uv run uvicorn segmentation_checker.backend.main:app \
  --host "$BACKEND_HOST" \
  --port "$BACKEND_PORT" \
  --reload &
BACKEND_PID="$!"

printf 'Backend:  http://%s:%s\n' "$BACKEND_HOST" "$BACKEND_PORT"
printf 'Frontend: http://127.0.0.1:%s\n' "$FRONTEND_PORT"

(cd "$ROOT_DIR/frontend" && npm run dev -- --host 127.0.0.1 --port "$FRONTEND_PORT")
