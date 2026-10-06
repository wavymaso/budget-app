"""Run Budget as a desktop app: the API on a free local port, shown in a native window.

Startup:  move old data if needed -> create tables -> start the server in a
          background thread -> open the window (on the main thread, as macOS requires).
Shutdown: closing the window (or Cmd+Q) returns from webview.start(), then the
          server is told to exit and we wait for it.
"""
import logging
import subprocess
import sys
import threading
from pathlib import Path

import webview

from . import config, server as server_mod
from .backups import auto_backup
from .db import connect, get_setting, init_db, migrate_legacy_data
from .email_sync import Poller
from .server import BackgroundServer, PhoneAccess

log = logging.getLogger("budget")


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
    try:
        auto_backup()
    except Exception:   # a failed backup must never stop the app from opening
        log.exception("Automatic backup failed")

    # The window always talks to a private server on 127.0.0.1.
    server = BackgroundServer("127.0.0.1", 0)
    server.start()
    log.info("Budget started on port %s, data in %s", server.port, config.DATA_DIR)

    # Phone access: a second server on the Wi-Fi, switched on in Settings
    # (or for this run with `run.py --lan` / BUDGET_LAN=1 in .env).
    phone = server_mod.phone_access = PhoneAccess()
    conn = connect()
    try:
        saved = {"enabled": False, "port": config.lan_port(), **(get_setting(conn, "phone_access") or {})}
    finally:
        conn.close()
    lan = config.lan_enabled() if lan is None else lan
    if saved["enabled"] or lan:
        phone.apply(True, port or saved["port"])
        log.info("Phone access on port %s%s", phone.port, f" (error: {phone.error})" if phone.error else "")

    poller = Poller()   # checks Gmail now, then every few minutes (if set up)
    poller.start()

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
            poller.stop()
            phone.stop()
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
