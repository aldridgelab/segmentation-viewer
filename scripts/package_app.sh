#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export UV_CACHE_DIR="${UV_CACHE_DIR:-$ROOT_DIR/.uv_cache}"
export PYINSTALLER_CONFIG_DIR="${PYINSTALLER_CONFIG_DIR:-$ROOT_DIR/.pyinstaller}"
APP_VERSION="${SEGMENTATION_CHECKER_APP_VERSION:-$(sed -n 's/^version = "\(.*\)"/\1/p' "$ROOT_DIR/pyproject.toml" | head -1)}"
APP_NAME="${SEGMENTATION_CHECKER_APP_NAME:-Aldridge Segmentation Checker}"
DMG_NAME="${SEGMENTATION_CHECKER_DMG_NAME:-AldridgeSegmentationChecker-v$APP_VERSION}"
DIST_DIR="$ROOT_DIR/dist"
FRONTEND_DIST="$ROOT_DIR/frontend/dist"
ICON_PATH="${SEGMENTATION_CHECKER_ICON_PATH:-$ROOT_DIR/assets/app-icon.icns}"
STAGE_DIR="$DIST_DIR/dmg-stage"
DMG_PATH="$DIST_DIR/$DMG_NAME.dmg"
APP_BUNDLE="$DIST_DIR/$APP_NAME.app"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "macOS packaging requires hdiutil and must be run on macOS." >&2
  exit 1
fi

if [[ -z "$APP_VERSION" ]]; then
  echo "Could not determine app version from pyproject.toml." >&2
  exit 1
fi

cd "$ROOT_DIR"

if [[ "${SEGMENTATION_CHECKER_SKIP_INSTALL:-0}" != "1" ]]; then
  uv sync --group dev
  (cd "$ROOT_DIR/frontend" && npm install)
fi

(cd "$ROOT_DIR/frontend" && npm run build)

if [[ ! -f "$FRONTEND_DIST/index.html" ]]; then
  echo "Frontend build missing at $FRONTEND_DIST." >&2
  exit 1
fi

if [[ ! -f "$ICON_PATH" ]]; then
  uv run python "$ROOT_DIR/scripts/generate_app_icon.py" --output-dir "$ROOT_DIR/assets"
fi

uv run pyinstaller \
  --noconfirm \
  --clean \
  --windowed \
  --icon "$ICON_PATH" \
  --name "$APP_NAME" \
  --osx-bundle-identifier "edu.aldridgelab.segmentationchecker" \
  --distpath "$DIST_DIR" \
  --workpath "$ROOT_DIR/build/pyinstaller" \
  --specpath "$ROOT_DIR/build/pyinstaller" \
  --add-data "$FRONTEND_DIST:frontend/dist" \
  --collect-all webview \
  --hidden-import webview.platforms.cocoa \
  --hidden-import uvicorn.logging \
  --hidden-import uvicorn.loops.auto \
  --hidden-import uvicorn.protocols.http.auto \
  --hidden-import uvicorn.protocols.websockets.auto \
  --hidden-import uvicorn.lifespan.on \
  "$ROOT_DIR/segmentation_checker/desktop.py"

if [[ ! -d "$APP_BUNDLE" ]]; then
  echo "Expected app bundle was not created: $APP_BUNDLE" >&2
  exit 1
fi

INFO_PLIST="$APP_BUNDLE/Contents/Info.plist"
set_plist_key() {
  local key="$1"
  local value="$2"
  /usr/libexec/PlistBuddy -c "Set :$key $value" "$INFO_PLIST" 2>/dev/null \
    || /usr/libexec/PlistBuddy -c "Add :$key string $value" "$INFO_PLIST"
}

set_plist_key "CFBundleShortVersionString" "$APP_VERSION"
set_plist_key "CFBundleVersion" "$APP_VERSION"
set_plist_key "CFBundleDisplayName" "$APP_NAME"
codesign --force --deep --sign - "$APP_BUNDLE"

rm -rf "$STAGE_DIR" "$DMG_PATH"
mkdir -p "$STAGE_DIR"
cp -R "$APP_BUNDLE" "$STAGE_DIR/"
ln -s /Applications "$STAGE_DIR/Applications"

hdiutil create \
  -volname "$APP_NAME v$APP_VERSION" \
  -srcfolder "$STAGE_DIR" \
  -ov \
  -format UDZO \
  "$DMG_PATH"

rm -rf "$STAGE_DIR"
rm -rf "$DIST_DIR/$APP_NAME"

printf 'App bundle: %s\n' "$APP_BUNDLE"
printf 'DMG:        %s\n' "$DMG_PATH"
