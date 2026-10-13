"""Reaching Budget from your phone anywhere, through Tailscale.

Tailscale (free for personal use) puts your Mac and your phone on a private,
encrypted network that works over any Wi-Fi or 4G. When phone access is on and
Tailscale is installed, Budget asks it to publish the phone server at your Mac's
private HTTPS address, e.g. https://marcels-macbook-air.tail1234.ts.net. Only
devices signed in to your Tailscale account can reach that address, and phones
still need Budget's phone password.

HTTPS matters: it's what lets the phone keep Budget as an installed app that
opens without the Mac and saves expenses until it can send them.
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("budget.tailscale")

CANDIDATES = {
    "darwin": ["/Applications/Tailscale.app/Contents/MacOS/Tailscale", "/usr/local/bin/tailscale", "/opt/homebrew/bin/tailscale"],
    "win32": [r"C:\Program Files\Tailscale\tailscale.exe"],
}


def cli() -> str | None:
    found = shutil.which("tailscale")
    if found:
        return found
    for path in CANDIDATES.get(sys.platform, []):
        if Path(path).exists():
            return path
    return None


def _run(args: list[str], timeout: float = 8) -> subprocess.CompletedProcess:
    exe = cli()
    if not exe:
        raise FileNotFoundError("Tailscale isn't installed")
    return subprocess.run([exe, *args], capture_output=True, text=True, timeout=timeout)


@dataclass
class Status:
    installed: bool = False
    connected: bool = False
    url: str | None = None            # https://<machine>.<tailnet>.ts.net
    error: str | None = None
    enable_url: str | None = None     # where to turn on HTTPS / Serve for your tailnet
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"installed": self.installed, "connected": self.connected, "url": self.url,
                "error": self.error, "enable_url": self.enable_url}


def status() -> Status:
    s = Status(installed=cli() is not None)
    if not s.installed:
        return s
    try:
        r = _run(["status", "--json"])
        data = json.loads(r.stdout or "{}")
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        s.error = f"Couldn't ask Tailscale for its status: {exc}"
        return s
    s.connected = data.get("BackendState") == "Running"
    if not s.connected:
        s.error = "Tailscale is installed but not connected. Open Tailscale and sign in."
    return s


_URL = re.compile(r"https://login\.tailscale\.com/\S+")


def publish(port: int) -> Status:
    """Serve http://127.0.0.1:<port> at this Mac's private HTTPS address."""
    s = status()
    if not s.connected:
        return s
    try:
        r = _run(["serve", "--bg", "--yes", f"http://127.0.0.1:{port}"], timeout=15)
        out = (r.stdout or "") + (r.stderr or "")
        if "unknown flag" in out and "--yes" in out:
            r = _run(["serve", "--bg", f"http://127.0.0.1:{port}"], timeout=15)
            out = (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired as exc:
        out = ((exc.stdout or b"").decode(errors="ignore") if isinstance(exc.stdout, bytes) else (exc.stdout or "")) + \
              ((exc.stderr or b"").decode(errors="ignore") if isinstance(exc.stderr, bytes) else (exc.stderr or ""))
        r = None
    except OSError as exc:
        s.error = f"Couldn't start Tailscale Serve: {exc}"
        return s
    found = _URL.search(out)
    if found and (r is None or r.returncode != 0):
        s.enable_url = found.group(0).rstrip(".")
        s.error = "Turn on HTTPS for your Tailscale network once, then switch phone access off and on."
        return s
    if r is not None and r.returncode != 0:
        s.error = f"Tailscale Serve didn't start: {out.strip()[:200]}"
        return s
    s.url = address()
    if not s.url:
        s.error = "Tailscale Serve started, but Budget couldn't read the address. See the Tailscale app."
    return s


def address() -> str | None:
    """The https:// address `tailscale serve` is publishing, if any."""
    try:
        data = json.loads(_run(["serve", "status", "--json"]).stdout or "{}")
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    for host in (data.get("Web") or {}):
        name = host.rsplit(":", 1)[0]
        return f"https://{name}" if host.endswith(":443") else f"https://{host}"
    return None


def unpublish() -> None:
    try:
        _run(["serve", "--https=443", "off"])
    except (OSError, subprocess.SubprocessError) as exc:
        log.info("Couldn't stop Tailscale Serve: %s", exc)
