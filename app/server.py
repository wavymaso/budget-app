"""Run the web app in a background thread (used by the desktop window and phone access)."""
import socket
import subprocess
import threading
import time

import uvicorn


class BackgroundServer:
    def __init__(self, host: str, port: int, name: str = "budget-server"):
        # Bind first so we know the port (0 = let macOS pick a free one) and so a
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
            app, log_config=None, log_level="warning",
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

    @property
    def running(self) -> bool:
        return self._server is not None

    @property
    def port(self) -> int | None:
        return self._server.port if self._server else None

    def apply(self, enabled: bool, port: int) -> None:
        with self._lock:
            if self._server and (not enabled or self._server.port != port):
                self._server.stop()
                self._server = None
            self.error = None
            if enabled and self._server is None:
                try:
                    server = BackgroundServer("0.0.0.0", port, name="budget-phone-server")
                    server.start()
                    self._server = server
                except OSError as exc:
                    self.error = (f"Port {port} is already in use by another program. Pick another port."
                                  if getattr(exc, "errno", None) == 48 else f"Couldn't open port {port}: {exc}")
                except RuntimeError as exc:
                    self.error = str(exc)

    def stop(self) -> None:
        self.apply(False, 0)

    def urls(self) -> list[str]:
        if not self.running:
            return []
        hosts = [h for h in (local_hostname(), lan_ip()) if h]
        return [f"http://{h}:{self.port}" for h in hosts]


# Set by the desktop app; None when running without a window (run.py --browser).
phone_access: PhoneAccess | None = None
