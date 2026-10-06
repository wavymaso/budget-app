"""Savings: whatever is left of each month's budget, plus money you add or take out.

A month is counted once it has ended, using the monthly budget at that moment,
so later budget changes don't rewrite the past. Counting starts with the month
savings was turned on.
"""
import sqlite3
from datetime import date as Date

from . import budgets
from .db import get_setting, set_setting

DEFAULTS = {"enabled": False, "start_month": None, "goal_name": None, "goal_cents": None}


def get_config(db: sqlite3.Connection) -> dict:
    return {**DEFAULTS, **(get_setting(db, "savings") or {})}


def save_config(db: sqlite3.Connection, today: Date | None = None, **changes) -> dict:
    cfg = {**get_config(db), **changes}
    if cfg["enabled"] and not cfg["start_month"]:
        cfg["start_month"] = (today or Date.today()).isoformat()[:7]
    set_setting(db, "savings", cfg)
    db.commit()
    return cfg


def _month_start(key: str) -> Date:
    return Date.fromisoformat(key + "-01")


def close_months(db: sqlite3.Connection, today: Date | None = None) -> int:
    """Store the result of every finished month since savings started. Returns how many."""
    cfg = get_config(db)
    if not cfg["start_month"]:
        return 0
    today = today or Date.today()
    this_month = budgets.month_bounds(today)[0]
    month = _month_start(cfg["start_month"])
    limit = budgets.get_limits(db).get((None, "month"))
    closed = 0
    while month < this_month:
        key = month.isoformat()[:7]
        if not db.execute("SELECT 1 FROM savings_months WHERE month = ?", (key,)).fetchone():
            start, end = budgets.month_bounds(month)
            spent = sum(budgets.spent_by_category(db, start, end).values())
            saved = (limit - spent) if limit is not None else 0
            db.execute("INSERT INTO savings_months (month, limit_cents, spent_cents, saved_cents) VALUES (?, ?, ?, ?)",
                       (key, limit, spent, saved))
            closed += 1
        month = budgets.shift_period("month", month, 1)
    if closed:
        db.commit()
    return closed


def summary(db: sqlite3.Connection, today: Date | None = None) -> dict:
    today = today or Date.today()
    cfg = get_config(db)
    if cfg["enabled"]:
        close_months(db, today)
    months = [dict(r) for r in db.execute("SELECT * FROM savings_months ORDER BY month DESC")]
    moves = [dict(r) for r in db.execute("SELECT id, date, amount_cents, note FROM savings_moves ORDER BY date DESC, id DESC")]
    total = sum(m["saved_cents"] for m in months) + sum(m["amount_cents"] for m in moves)
    return {**cfg, "total_cents": total, "months": months, "moves": moves}
