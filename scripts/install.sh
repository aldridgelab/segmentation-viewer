#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export UV_CACHE_DIR="${UV_CACHE_DIR:-$ROOT_DIR/.uv_cache}"

cd "$ROOT_DIR"
uv sync --group dev
(cd "$ROOT_DIR/frontend" && npm install)
