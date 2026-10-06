"""Copies of the database: on demand, and one automatic copy a day when Budget opens.

Backups live in a `backups` folder next to the database. Automatic ones are named
budget-auto-YYYY-MM-DD.db and only the newest AUTO_KEEP are kept; ones you make
yourself (budget-YYYY-MM-DD_HH-MM-SS.db) are never deleted.
"""
import logging
import sqlite3
from datetime import date as Date
from datetime import datetime
from pathlib import Path

from .db import connect, db_path

AUTO_KEEP = 14
log = logging.getLogger("budget.backups")


def backup_dir() -> Path:
    return db_path().parent / "backups"


def _copy_to(target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".db.part")
    src = connect()
    dst = sqlite3.connect(tmp)
    try:
        src.backup(dst)   # consistent copy even while the app is running
    finally:
        dst.close()
        src.close()
    tmp.replace(target)
    return target


def make_backup() -> Path:
    return _copy_to(backup_dir() / f"budget-{datetime.now():%Y-%m-%d_%H-%M-%S}.db")


def auto_backup(today: Date | None = None) -> Path | None:
    """Make today's automatic backup if there isn't one yet, then prune old ones."""
    if not db_path().exists():
        return None
    target = backup_dir() / f"budget-auto-{(today or Date.today()).isoformat()}.db"
    made = None
    if not target.exists():
        made = _copy_to(target)
        log.info("Automatic backup: %s", made.name)
    for old in sorted(backup_dir().glob("budget-auto-*.db"), reverse=True)[AUTO_KEEP:]:
        old.unlink(missing_ok=True)
    return made


def list_backups() -> list[dict]:
    if not backup_dir().exists():
        return []
    files = sorted(backup_dir().glob("budget-*.db"), key=lambda f: f.stat().st_mtime, reverse=True)
    return [{"file": f.name, "path": str(f), "size_bytes": f.stat().st_size, "automatic": f.name.startswith("budget-auto-"),
             "created": datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec="seconds")} for f in files]
