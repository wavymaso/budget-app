"""Monthly bills: each one becomes an ordinary expense on its day every month."""
import calendar
import sqlite3
from datetime import date as Date

from .normalize import normalize_merchant

MAX_CATCH_UP = 24   # months added at most in one go (e.g. after a long break)


def on_day(year: int, month: int, day: int) -> Date:
    """`day` in that month, moved back to the last day for short months (31 -> 30 Apr)."""
    return Date(year, month, min(day, calendar.monthrange(year, month)[1]))


def next_month(d: Date, day: int) -> Date:
    y, m = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    return on_day(y, m, day)


def create(db: sqlite3.Connection, *, expense_id: int, merchant: str, amount_cents: int,
           category_id: int | None, note: str | None, first: Date) -> int:
    """Make a bill from an expense you just added: it repeats from next month."""
    cur = db.execute(
        "INSERT INTO recurring (merchant, amount_cents, category_id, note, day, next_date) VALUES (?, ?, ?, ?, ?, ?)",
        (merchant, amount_cents, category_id, note, first.day, next_month(first, first.day).isoformat()),
    )
    db.execute("UPDATE expenses SET recurring_id = ? WHERE id = ?", (cur.lastrowid, expense_id))
    return cur.lastrowid


def add_due(db: sqlite3.Connection, today: Date | None = None) -> int:
    """Add every bill whose date has come. Returns how many expenses were added."""
    today = today or Date.today()
    added = 0
    for r in db.execute("SELECT * FROM recurring WHERE next_date <= ?", (today.isoformat(),)).fetchall():
        nxt = Date.fromisoformat(r["next_date"])
        for _ in range(MAX_CATCH_UP):
            if nxt > today:
                break
            db.execute(
                """INSERT INTO expenses (amount_cents, merchant_raw, merchant_norm, category_id, date, note,
                                         source, category_source, recurring_id)
                   VALUES (?, ?, ?, ?, ?, ?, 'recurring', ?, ?)""",
                (r["amount_cents"], r["merchant"], normalize_merchant(r["merchant"]), r["category_id"],
                 nxt.isoformat(), r["note"], "manual" if r["category_id"] else "none", r["id"]),
            )
            added += 1
            nxt = next_month(nxt, r["day"])
        else:
            # Gone for years: skip ahead instead of filling in every missed month.
            while nxt <= today:
                nxt = next_month(nxt, r["day"])
        db.execute("UPDATE recurring SET next_date = ? WHERE id = ?", (nxt.isoformat(), r["id"]))
    if added:
        db.commit()
    return added


def month_bills(db: sqlite3.Connection, start: Date, end: Date, today: Date) -> dict:
    """Bills in a month: already added, and still to come before the month ends."""
    paid = db.execute(
        "SELECT COALESCE(SUM(amount_cents), 0) FROM expenses WHERE recurring_id IS NOT NULL AND date BETWEEN ? AND ?",
        (start.isoformat(), end.isoformat()),
    ).fetchone()[0]
    upcoming = db.execute(
        "SELECT COALESCE(SUM(amount_cents), 0) FROM recurring WHERE next_date > ? AND next_date BETWEEN ? AND ?",
        (today.isoformat(), start.isoformat(), end.isoformat()),
    ).fetchone()[0]
    return {"paid_cents": paid, "upcoming_cents": upcoming}
