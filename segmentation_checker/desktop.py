"""Desktop launcher for the segmentation checker."""

from __future__ import annotations

import argparse
import importlib.util
import os
import socket
import sys
import threading
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import uvicorn

from segmentation_checker import __version__

APP_NAME = "Aldridge Segmentation Checker"
APP_TITLE = f"Aldridge Segmentation Checker - v{__version__}"
CONFIG_DIR_NAME = "Segmentation Checker"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_WIDTH = 1380
DEFAULT_HEIGHT = 900


def _app_config_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / CONFIG_DIR_NAME
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / CONFIG_DIR_NAME
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "segmentation-checker"


def _bundle_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parents[1]


def _default_frontend_dist() -> Path:
    if os.environ.get("SEGMENTATION_CHECKER_FRONTEND_DIST"):
        return Path(os.environ["SEGMENTATION_CHECKER_FRONTEND_DIST"]).expanduser()
    return _bundle_root() / "frontend" / "dist"


def _configure_environment(
    config_path: Path | None,
    frontend_dist: Path | None,
) -> tuple[Path, Path]:
    resolved_config_path = (config_path or _app_config_dir() / "checker_config.json").expanduser()
    resolved_config_path.parent.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("SEGMENTATION_CHECKER_CONFIG_PATH", str(resolved_config_path))

    resolved_frontend_dist = (frontend_dist or _default_frontend_dist()).expanduser()
    os.environ.setdefault("SEGMENTATION_CHECKER_FRONTEND_DIST", str(resolved_frontend_dist))
    return resolved_config_path, resolved_frontend_dist


def _load_backend_app(frontend_dist: Path):
    from segmentation_checker.backend.main import app, mount_frontend_dist

    resolved_frontend_dist = mount_frontend_dist(frontend_dist)
    return app, resolved_frontend_dist


def _choose_port(host: str, requested_port: int) -> int:
    if requested_port > 0:
        return requested_port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def _wait_for_backend(url: str, timeout_seconds: float = 10.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    health_url = f"{url}/api/health"
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urlopen(health_url, timeout=0.5) as response:
                if response.status == 200:
                    return
        except (OSError, URLError) as exc:
            last_error = exc
        time.sleep(0.1)
    raise RuntimeError(f"Backend did not start at {health_url}: {last_error}")


def _ensure_webview_available() -> None:
    if importlib.util.find_spec("webview") is None:
        raise RuntimeError("pywebview is not installed. Run `uv sync` before starting the desktop app.")


def run_desktop(args: argparse.Namespace) -> int:
    _ensure_webview_available()
    config_path, frontend_dist = _configure_environment(args.config_path, args.frontend_dist)
    backend_app, resolved_frontend_dist = _load_backend_app(frontend_dist)

    port = _choose_port(args.host, args.port)
    base_url = f"http://{args.host}:{port}"
    server = uvicorn.Server(
        uvicorn.Config(
            backend_app,
            host=args.host,
            port=port,
            log_level=args.log_level,
            access_log=False,
        )
    )
    thread = threading.Thread(target=server.run, name="segmentation-checker-backend", daemon=True)
    thread.start()
    _wait_for_backend(base_url)

    import webview

    webview.create_window(
        APP_TITLE,
        base_url,
        width=args.width,
        height=args.height,
        min_size=(1040, 680),
    )
    try:
        webview.start(debug=args.debug)
    finally:
        server.should_exit = True
        thread.join(timeout=5)

    if args.print_paths:
        print(f"config_path={config_path}")
        print(f"frontend_dist={resolved_frontend_dist}")
    return 0


def check_desktop(args: argparse.Namespace) -> int:
    _ensure_webview_available()
    config_path, frontend_dist = _configure_environment(args.config_path, args.frontend_dist)
    _, resolved_frontend_dist = _load_backend_app(frontend_dist)
    print("desktop_check=ok")
    print(f"config_path={config_path}")
    print(f"frontend_dist={resolved_frontend_dist}")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=f"Launch {APP_NAME} as a desktop app.")
    parser.add_argument("--host", default=os.environ.get("SEGMENTATION_CHECKER_HOST", DEFAULT_HOST))
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("SEGMENTATION_CHECKER_PORT", "0")),
        help="Backend port. Use 0 to pick a free local port.",
    )
    parser.add_argument("--frontend-dist", type=Path, default=None)
    parser.add_argument("--config-path", type=Path, default=None)
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    parser.add_argument("--log-level", default=os.environ.get("SEGMENTATION_CHECKER_LOG_LEVEL", "warning"))
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--print-paths", action="store_true")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate desktop dependencies and frontend build without opening a window.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.check:
            return check_desktop(args)
        return run_desktop(args)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
