#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-run}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export UV_CACHE_DIR="${UV_CACHE_DIR:-$ROOT_DIR/.uv_cache}"
APP_MATCH="segmentation_checker.desktop"

cd "$ROOT_DIR"

pkill -f "$APP_MATCH" >/dev/null 2>&1 || true

uv sync --group dev
(cd "$ROOT_DIR/frontend" && npm install && npm run build)

case "$MODE" in
  run)
    uv run python -m segmentation_checker.desktop
    ;;
  --debug|debug)
    uv run python -m segmentation_checker.desktop --debug
    ;;
  --logs|logs)
    uv run python -m segmentation_checker.desktop --print-paths
    ;;
  --telemetry|telemetry)
    uv run python -m segmentation_checker.desktop --print-paths
    ;;
  --verify|verify)
    uv run python -m segmentation_checker.desktop --check
    ;;
  *)
    echo "usage: $0 [run|--debug|--logs|--telemetry|--verify]" >&2
    exit 2
    ;;
esac
