"""Run the web app in a background thread (used by the desktop window and phone access)."""
import os
import socket
import subprocess
import sys
import threading
import time

import uvicorn


def mark_remote(app):
    """Everything arriving through the phone server is a phone, even when it comes
    from 127.0.0.1 (Tailscale forwards phone traffic from the Mac itself)."""
    async def wrapped(scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            scope = {**scope, "budget_remote": True}
        await app(scope, receive, send)
    return wrapped


class BackgroundServer:
    def __init__(self, host: str, port: int, name: str = "budget-server", remote: bool = False):
        # Bind first so we know the port (0 = let the system pick a free one) and so a
        # busy port fails here, with a clear OSError, rather than inside the thread.
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.sock.bind((host, port))
        except OSError:
            self.sock.close()
            raise
        self.host, self.port = host, self.sock.getsockname()[1]
        from .main import app
        self.server = uvicorn.Server(uvicorn.Config(
            mark_remote(app) if remote else app, log_config=None, log_level="warning",
            loop="asyncio", http="h11", ws="none", lifespan="on",
            proxy_headers=False,   # the client address must be the real one (used for access control)
        ))
        self.thread = threading.Thread(target=self.server.run, kwargs={"sockets": [self.sock]},
                                       name=name, daemon=True)

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


def lan_ip() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))  # no packet is sent; just picks the Wi-Fi interface
            ip = s.getsockname()[0]
            return None if ip.startswith("127.") else ip
    except OSError:
        return None


def local_hostname() -> str | None:
    """The Mac's Bonjour name, e.g. "Marias-MacBook-Air.local" (stays the same when the IP changes)."""
    if sys.platform != "darwin":
        return None   # Windows and Linux: phones use the IP address
    try:
        name = subprocess.run(["scutil", "--get", "LocalHostName"], capture_output=True,
                              text=True, timeout=3).stdout.strip()
        return f"{name}.local" if name else None
    except (OSError, subprocess.SubprocessError):
        return None


class PhoneAccess:
    """Starts/stops a second server on 0.0.0.0 so phones on the same Wi-Fi can connect."""

    def __init__(self):
        self._server: BackgroundServer | None = None
        self._lock = threading.Lock()
        self.error: str | None = None
        self.tailscale: dict = {"installed": False, "connected": False, "url": None, "error": None, "enable_url": None}
        self._awake: subprocess.Popen | None = None

    @property
    def running(self) -> bool:
        return self._server is not None

    @property
    def port(self) -> int | None:
        return self._server.port if self._server else None

    def apply(self, enabled: bool, port: int, keep_awake: bool = True, tailscale: bool = True) -> None:
        with self._lock:
            was_running = self._server is not None
            if self._server and (not enabled or self._server.port != port):
                self._server.stop()
                self._server = None
            self.error = None
            if enabled and self._server is None:
                try:
                    server = BackgroundServer("0.0.0.0", port, name="budget-phone-server", remote=True)
                    server.start()
                    self._server = server
                except OSError as exc:
                    self.error = (f"Port {port} is already in use by another program. Pick another port."
                                  if getattr(exc, "errno", None) in (48, 98, 10048) else f"Couldn't open port {port}: {exc}")
                except RuntimeError as exc:
                    self.error = str(exc)
            self._set_awake(enabled and keep_awake and self._server is not None)
        if tailscale and self._server is not None:
            self.tailscale = {**self.tailscale, "pending": True}
            threading.Thread(target=self._publish, args=(self._server.port,), name="budget-tailscale", daemon=True).start()
        elif tailscale and was_running and not enabled:
            from . import tailscale as ts
            threading.Thread(target=ts.unpublish, name="budget-tailscale", daemon=True).start()
            self.tailscale = {**self.tailscale, "url": None, "pending": False}

    def _publish(self, port: int) -> None:
        from . import tailscale as ts
        try:
            self.tailscale = {**ts.publish(port).as_dict(), "pending": False}
        except Exception as exc:  # never let Tailscale trouble break phone access on Wi-Fi
            self.tailscale = {"installed": True, "connected": False, "url": None,
                              "error": f"Tailscale: {exc}", "enable_url": None, "pending": False}

    def _set_awake(self, on: bool) -> None:
        """Keep the Mac from sleeping while it's plugged in and phone access is on
        (macOS `caffeinate -s`, which only applies on mains power)."""
        if on and self._awake is None and sys.platform == "darwin":
            try:
                self._awake = subprocess.Popen(["caffeinate", "-s", "-w", str(os.getpid())])
            except OSError:
                self._awake = None
        elif not on and self._awake is not None:
            self._awake.terminate()
            self._awake = None

    def stop(self) -> None:
        # Leave Tailscale Serve set up: while Budget is closed the phone simply sees
        # "Mac not reachable" and keeps working offline. It's republished on launch.
        self.apply(False, 0, tailscale=False)

    def refresh_tailscale(self) -> None:
        """Tailscale installed or set up after Budget started: pick up the address
        it's already publishing for us instead of saying "install Tailscale"."""
        if not self.running or self.tailscale.get("url") or self.tailscale.get("pending"):
            return
        from . import tailscale as ts
        try:
            published = ts.address(port=self.port)
        except Exception:
            return
        if published:
            self.tailscale = {"installed": True, "connected": True, "url": published, "error": None, "enable_url": None}
        elif ts.cli() and not self.tailscale.get("installed"):
            self.tailscale = {**self.tailscale, "pending": True}
            threading.Thread(target=self._publish, args=(self.port,), name="budget-tailscale", daemon=True).start()

    def urls(self) -> list[str]:
        if not self.running:
            return []
        hosts = [h for h in (local_hostname(), lan_ip()) if h]
        anywhere = [self.tailscale["url"]] if self.tailscale.get("url") else []
        return anywhere + [f"http://{h}:{self.port}" for h in hosts]


# Set by the desktop app; None when running without a window (run.py --browser).
phone_access: PhoneAccess | None = None
