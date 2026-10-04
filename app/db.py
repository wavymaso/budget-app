"""SQLite storage. The database file and tables are created automatically."""
import json
import logging
import shutil
import sqlite3
from pathlib import Path

from . import config, seed
from .normalize import normalize_merchant

SCHEMA = """
CREATE TABLE IF NOT EXISTS categories (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    color       TEXT NOT NULL DEFAULT '#64748b',
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS expenses (
    id              INTEGER PRIMARY KEY,
    amount_cents    INTEGER NOT NULL,          -- positive = spending, negative = refund
    merchant_raw    TEXT NOT NULL,
    merchant_norm   TEXT NOT NULL,
    category_id     INTEGER REFERENCES categories(id) ON DELETE SET NULL,  -- NULL = Uncategorized
    date            TEXT NOT NULL,             -- ISO YYYY-MM-DD
    note            TEXT,
    source          TEXT NOT NULL DEFAULT 'manual',   -- manual | csv | api
    category_source TEXT NOT NULL DEFAULT 'none',     -- learned | rule | fuzzy | ai | manual | none
    import_hash     TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_expenses_date ON expenses(date);
CREATE INDEX IF NOT EXISTS idx_expenses_category ON expenses(category_id);
CREATE INDEX IF NOT EXISTS idx_expenses_merchant ON expenses(merchant_norm);

-- Your own choices: normalized merchant -> category. These always win.
CREATE TABLE IF NOT EXISTS merchant_rules (
    merchant_norm TEXT PRIMARY KEY,
    category_id   INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    hit_count     INTEGER NOT NULL DEFAULT 1,
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Built-in keywords (seeded), matched as whole words.
CREATE TABLE IF NOT EXISTS keyword_rules (
    keyword     TEXT PRIMARY KEY,
    category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE
);

-- Claude's guesses, cached so the same merchant isn't sent twice.
CREATE TABLE IF NOT EXISTS ai_cache (
    merchant_norm TEXT PRIMARY KEY,
    category_id   INTEGER REFERENCES categories(id) ON DELETE CASCADE,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- category_id NULL = overall limit.
CREATE TABLE IF NOT EXISTS budgets (
    id          INTEGER PRIMARY KEY,
    category_id INTEGER REFERENCES categories(id) ON DELETE CASCADE,
    period      TEXT NOT NULL CHECK (period IN ('week', 'month')),
    limit_cents INTEGER NOT NULL CHECK (limit_cents >= 0)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_budgets ON budgets(COALESCE(category_id, 0), period);

-- One row per Apple Pay email seen in Gmail (keyed by Message-ID, so nothing imports twice).
CREATE TABLE IF NOT EXISTS email_messages (
    id              INTEGER PRIMARY KEY,
    message_id      TEXT NOT NULL UNIQUE,
    uid             INTEGER,
    status          TEXT NOT NULL,   -- imported | review | accepted | dismissed | refused
    reason          TEXT,
    sender          TEXT,
    line            TEXT,            -- the transaction line (or an excerpt if none was found)
    date            TEXT,
    merchant        TEXT,
    amount_cents    INTEGER,
    currency        TEXT,
    category_id     INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    category_source TEXT,
    duplicate_of    INTEGER REFERENCES expenses(id) ON DELETE SET NULL,
    expense_id      INTEGER REFERENCES expenses(id) ON DELETE SET NULL,
    received_at     TEXT,
    processed_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_email_status ON email_messages(status);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


log = logging.getLogger("budget.db")


def migrate_legacy_data() -> str | None:
    """Move data/budget.db (the old location inside the project) to Application Support.

    Runs only when there is no database in the new place yet. The old files are
    left untouched; once you've checked everything is there you can delete data/.
    Returns a short description of what was moved, or None.
    """
    if config.DB_PATH.exists() or config.LEGACY_DATA_DIR is None:
        return None
    old_db = config.LEGACY_DATA_DIR / "budget.db"
    if not old_db.exists():
        return None
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = config.DB_PATH.with_suffix(".db.migrating")
    src = sqlite3.connect(f"file:{old_db}?mode=ro", uri=True)
    dst = sqlite3.connect(tmp)
    try:
        src.backup(dst)   # also picks up anything still in the -wal file
    finally:
        dst.close()
        src.close()
    tmp.replace(config.DB_PATH)
    copied = 0
    old_backups = config.LEGACY_DATA_DIR / "backups"
    if old_backups.is_dir():
        config.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        for f in old_backups.glob("*.db"):
            if not (config.BACKUP_DIR / f.name).exists():
                shutil.copy2(f, config.BACKUP_DIR / f.name)
                copied += 1
    msg = f"Moved {old_db} to {config.DB_PATH}" + (f" (+{copied} backups)" if copied else "")
    log.info(msg)
    return msg


def db_path() -> Path:
    return config.DB_PATH


def connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_db():
    """FastAPI dependency: one connection per request."""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    conn = connect()
    try:
        # WAL keeps the file consistent even if the server is killed mid-write.
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
        if get_setting(conn, "seeded") is None:
            _seed(conn)
        conn.commit()
    finally:
        conn.close()


def _seed(conn: sqlite3.Connection) -> None:
    for i, (name, color) in enumerate(seed.DEFAULT_CATEGORIES):
        conn.execute(
            "INSERT OR IGNORE INTO categories (name, color, sort_order) VALUES (?, ?, ?)",
            (name, color, i),
        )
    ids = {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM categories")}
    for cat_name, keywords in seed.KEYWORD_RULES.items():
        for kw in keywords:
            norm = normalize_merchant(kw)
            if norm and cat_name in ids:
                conn.execute(
                    "INSERT OR IGNORE INTO keyword_rules (keyword, category_id) VALUES (?, ?)",
                    (norm, ids[cat_name]),
                )
    set_setting(conn, "seeded", True)


def get_setting(conn: sqlite3.Connection, key: str, default=None):
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def set_setting(conn: sqlite3.Connection, key: str, value) -> None:
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, json.dumps(value)),
    )
