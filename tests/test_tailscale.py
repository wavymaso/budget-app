"""Publishing the phone server through Tailscale, with a pretend `tailscale` command."""
import json
import subprocess

from app import tailscale as ts


def fake(monkeypatch, responses):
    calls = []

    def run(args, timeout=8):
        calls.append(args)
        key = " ".join(args[:2])
        out, code = responses.get(key, ("", 0))
        return subprocess.CompletedProcess(args, code, stdout=out, stderr="")
    monkeypatch.setattr(ts, "cli", lambda: "/usr/local/bin/tailscale")
    monkeypatch.setattr(ts, "_run", run)
    return calls


def test_not_installed(monkeypatch):
    monkeypatch.setattr(ts, "cli", lambda: None)
    s = ts.publish(8000)
    assert not s.installed and s.url is None and s.error is None


def test_installed_but_signed_out(monkeypatch):
    fake(monkeypatch, {"status --json": (json.dumps({"BackendState": "NeedsLogin"}), 0)})
    s = ts.publish(8000)
    assert s.installed and not s.connected and "sign in" in s.error


def test_publishes_and_reads_the_address(monkeypatch):
    calls = fake(monkeypatch, {
        "status --json": (json.dumps({"BackendState": "Running"}), 0),
        "serve status": (json.dumps({"Web": {"marcels-mac.tail1234.ts.net:443": {}}}), 0),
    })
    s = ts.publish(8123)
    assert s.url == "https://marcels-mac.tail1234.ts.net" and s.error is None
    assert ["serve", "--bg", "--yes", "http://127.0.0.1:8123"] in calls


def test_https_not_turned_on_yet(monkeypatch):
    fake(monkeypatch, {
        "status --json": (json.dumps({"BackendState": "Running"}), 0),
        "serve --bg": ("Serve is not enabled on your tailnet.\nTo enable, visit:\n\n  https://login.tailscale.com/f/serve?node=abc123\n", 1),
    })
    s = ts.publish(8000)
    assert s.enable_url == "https://login.tailscale.com/f/serve?node=abc123"
    assert s.url is None and "HTTPS" in s.error
