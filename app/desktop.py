"""Run Budget as a desktop app: the API on a free local port, shown in a native window.

Startup:  move old data if needed -> create tables -> start the server in a
          background thread -> open the window (on the main thread, as macOS requires).
Shutdown: closing the window (or Cmd+Q) returns from webview.start(), then the
          server is told to exit and we wait for it.
"""
import logging
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import uvicorn
import webview

from . import config
from .db import connect, init_db, migrate_legacy_data

log = logging.getLogger("budget")


class BackgroundServer:
    def __init__(self, host: str, port: int):
        # Bind first so we know the port (0 = let macOS pick a free one).
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((host, port))
        self.port = self.sock.getsockname()[1]
        from .main import app
        self.server = uvicorn.Server(uvicorn.Config(
            app, log_config=None, log_level="warning",
            loop="asyncio", http="h11", ws="none", lifespan="on",
        ))
        self.thread = threading.Thread(target=self.server.run, kwargs={"sockets": [self.sock]},
                                       name="budget-server", daemon=True)

    def start(self, timeout: float = 20) -> None:
        self.thread.start()
        deadline = time.monotonic() + timeout
        while not self.server.started:
            if not self.thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("The Budget server didn't start; see the log for details.")
            time.sleep(0.02)

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=5)
        self.sock.close()


class DesktopApi:
    """Native features the page can call as window.pywebview.api.<name>()."""

    def __init__(self):
        self._window = None   # underscore: pywebview doesn't expose it to JavaScript

    def export_csv(self) -> str | None:
        from .routers.io import build_export_csv, export_filename
        chosen = self._window.create_file_dialog(
            webview.FileDialog.SAVE,
            directory=str(Path.home() / "Downloads"),
            save_filename=export_filename(),
            file_types=("CSV files (*.csv)",),
        )
        if not chosen:
            return None
        path = Path(chosen if isinstance(chosen, str) else chosen[0])
        conn = connect()
        try:
            path.write_text(build_export_csv(conn), encoding="utf-8")
        finally:
            conn.close()
        return str(path)

    def show_data_folder(self) -> None:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        subprocess.run(["open", str(config.DATA_DIR)], check=False)

    def show_in_finder(self, path: str) -> None:
        target = Path(path).resolve()
        if config.DATA_DIR.resolve() in target.parents and target.exists():
            subprocess.run(["open", "-R", str(target)], check=False)


def setup_logging() -> None:
    if config.FROZEN:
        # A double-clicked app has nowhere to print to; keep a log in ~/Library/Logs/Budget.
        config.LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_file = open(config.LOG_DIR / "budget.log", "a", buffering=1, encoding="utf-8")
        sys.stdout = sys.stderr = log_file
    logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def set_dev_dock_icon() -> None:
    """When run from source, show the Budget icon in the Dock instead of Python's."""
    icon = config.BASE_DIR / "macos" / "icon.png"
    if config.FROZEN or not icon.exists():
        return
    try:
        from AppKit import NSApplication, NSImage
        NSApplication.sharedApplication().setApplicationIconImage_(
            NSImage.alloc().initWithContentsOfFile_(str(icon)))
    except Exception:  # cosmetic only
        pass


def main(lan: bool | None = None, port: int | None = None, debug: bool = False) -> None:
    setup_logging()
    migrate_legacy_data()
    init_db()

    lan = config.lan_enabled() if lan is None else lan
    host = "0.0.0.0" if lan else "127.0.0.1"
    port = (config.lan_port() if lan else 0) if port is None else port
    server = BackgroundServer(host, port)
    server.start()
    log.info("Budget started on port %s (lan=%s), data in %s", server.port, lan, config.DATA_DIR)

    api = DesktopApi()
    window = webview.create_window(
        config.APP_NAME, f"http://127.0.0.1:{server.port}/", js_api=api,
        width=1200, height=820, min_size=(380, 560),
        text_select=True, background_color="#F8FAFC",
    )
    api._window = window

    stopped = threading.Event()

    def shutdown():
        if not stopped.is_set():
            stopped.set()
            log.info("Window closed, shutting down")
            server.stop()
            log.info("Server stopped")

    # Cmd+Q ends the process without returning from webview.start(), so stop
    # the server while the window is closing, whichever way that happens.
    window.events.closing += shutdown   # pywebview waits for "closing" handlers
    set_dev_dock_icon()
    try:
        webview.start(debug=debug)
    finally:
        shutdown()
