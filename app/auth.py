"""Phone access: a password for devices on your Wi-Fi, and their sign-in sessions.

The Mac's own window (127.0.0.1) never needs to sign in. Other devices must sign
in with the phone password; they then get a session cookie that lasts 30 days.

- The password is stored only as a salted scrypt hash (never readable).
- Sessions are random tokens; only their SHA-256 hash is stored.
- Repeated wrong passwords from one address are slowed down.
"""
import hashlib
import hmac
import secrets
import sqlite3
import threading
import time

from . import config
from .db import get_setting, set_setting

COOKIE = "budget_session"
SESSION_DAYS = 30
MIN_PASSWORD_LENGTH = 6
MAX_FAILURES, FAILURE_WINDOW = 5, 10 * 60      # 5 wrong tries per 10 minutes per address

LOCAL_CLIENTS = {"127.0.0.1", "::1", "localhost"}

def is_local(host: str | None) -> bool:
    return (host or "") in LOCAL_CLIENTS


# --- settings ------------------------------------------------------------------

def phone_settings(conn: sqlite3.Connection) -> dict:
    return {"enabled": False, "port": config.lan_port(), **(get_setting(conn, "phone_access") or {})}


def save_phone_settings(conn: sqlite3.Connection, **changes) -> dict:
    cfg = {**phone_settings(conn), **changes}
    set_setting(conn, "phone_access", cfg)
    conn.commit()
    return cfg


# --- password ------------------------------------------------------------------

def _hash(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)


def has_password(conn: sqlite3.Connection) -> bool:
    return get_setting(conn, "phone_password") is not None


def set_password(conn: sqlite3.Connection, password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Use at least {MIN_PASSWORD_LENGTH} characters")
    salt = secrets.token_bytes(16)
    set_setting(conn, "phone_password", {"salt": salt.hex(), "hash": _hash(password, salt).hex()})
    sign_out_everyone(conn)          # a new password signs out every phone
    conn.commit()


def check_password(conn: sqlite3.Connection, password: str) -> bool:
    stored = get_setting(conn, "phone_password")
    if not stored:
        return False
    actual = _hash(password, bytes.fromhex(stored["salt"]))
    return hmac.compare_digest(actual, bytes.fromhex(stored["hash"]))


# --- sessions ------------------------------------------------------------------

def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(conn: sqlite3.Connection, user_agent: str, ip: str) -> str:
    token = secrets.token_urlsafe(32)
    conn.execute("INSERT INTO sessions (token_hash, user_agent, ip) VALUES (?, ?, ?)",
                 (_token_hash(token), (user_agent or "")[:300], ip))
    conn.commit()
    return token


def valid_session(conn: sqlite3.Connection, token: str | None) -> bool:
    if not token:
        return False
    h = _token_hash(token)
    row = conn.execute(
        f"SELECT 1 FROM sessions WHERE token_hash = ? AND last_seen > datetime('now', '-{SESSION_DAYS} days')",
        (h,)).fetchone()
    if row:
        conn.execute("UPDATE sessions SET last_seen = datetime('now') WHERE token_hash = ?", (h,))
        conn.commit()
    return row is not None


def end_session(conn: sqlite3.Connection, token: str | None) -> None:
    if token:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))
        conn.commit()


def sign_out_everyone(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM sessions")


def list_sessions(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        f"SELECT user_agent, ip, created_at, last_seen FROM sessions "
        f"WHERE last_seen > datetime('now', '-{SESSION_DAYS} days') ORDER BY last_seen DESC").fetchall()
    return [dict(r) for r in rows]


# --- slowing down guessing -----------------------------------------------------------

_failures: dict[str, list[float]] = {}
_failures_lock = threading.Lock()


def seconds_locked_out(ip: str) -> int:
    now = time.monotonic()
    with _failures_lock:
        recent = [t for t in _failures.get(ip, []) if now - t < FAILURE_WINDOW]
        _failures[ip] = recent
        if len(recent) < MAX_FAILURES:
            return 0
        return int(FAILURE_WINDOW - (now - recent[0])) + 1


def record_failure(ip: str) -> None:
    with _failures_lock:
        _failures.setdefault(ip, []).append(time.monotonic())


def clear_failures(ip: str) -> None:
    with _failures_lock:
        _failures.pop(ip, None)
