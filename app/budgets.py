"""Period math and budget calculations. Weeks run Monday to Sunday."""
import sqlite3
from datetime import date, timedelta

AMBER_AT = 75  # percent


def week_bounds(d: date) -> tuple[date, date]:
    start = d - timedelta(days=d.weekday())
    return start, start + timedelta(days=6)


def month_bounds(d: date) -> tuple[date, date]:
    start = d.replace(day=1)
    next_month = (start + timedelta(days=32)).replace(day=1)
    return start, next_month - timedelta(days=1)


def period_bounds(period: str, d: date) -> tuple[date, date]:
    if period == "week":
        return week_bounds(d)
    if period == "month":
        return month_bounds(d)
    raise ValueError(f"unknown period {period!r}")


def shift_period(period: str, d: date, steps: int) -> date:
    """A date inside the period `steps` periods before (-) or after (+) the one containing d."""
    start, _ = period_bounds(period, d)
    if period == "week":
        return start + timedelta(weeks=steps)
    month_index = start.year * 12 + (start.month - 1) + steps
    return date(month_index // 12, month_index % 12 + 1, 1)


def level(spent: int, limit: int | None) -> str | None:
    """green under 75%, amber from 75% up to 100%, red when over."""
    if limit is None:
        return None
    if limit <= 0:
        return "red" if spent > 0 else "green"
    pct = spent * 100 / limit
    if pct > 100:
        return "red"
    return "amber" if pct >= AMBER_AT else "green"


def days_left(start: date, end: date, today: date) -> int:
    """Days remaining in the period, counting today."""
    if today < start:
        return (end - start).days + 1
    if today > end:
        return 0
    return (end - today).days + 1


def summarize(spent: int, limit: int | None, start: date, end: date, today: date) -> dict:
    remaining_days = days_left(start, end, today)
    out = {
        "spent_cents": spent,
        "limit_cents": limit,
        "left_cents": None,
        "per_day_cents": None,
        "pct": None,
        "level": level(spent, limit),
    }
    if limit is not None:
        left = limit - spent
        out["left_cents"] = left
        out["pct"] = round(spent * 100 / limit, 1) if limit > 0 else (100.0 if spent <= 0 else None)
        if remaining_days > 0:
            out["per_day_cents"] = max(left, 0) // remaining_days
    return out


def get_limits(conn: sqlite3.Connection) -> dict[tuple[int | None, str], int]:
    return {
        (r["category_id"], r["period"]): r["limit_cents"]
        for r in conn.execute("SELECT category_id, period, limit_cents FROM budgets")
    }


def spent_by_category(conn: sqlite3.Connection, start: date, end: date) -> dict[int | None, int]:
    rows = conn.execute(
        "SELECT category_id, SUM(amount_cents) AS total FROM expenses "
        "WHERE date BETWEEN ? AND ? GROUP BY category_id",
        (start.isoformat(), end.isoformat()),
    )
    return {r["category_id"]: r["total"] for r in rows}


def period_status(conn: sqlite3.Connection, period: str, ref: date, today: date) -> dict:
    """Spending vs limits for the week/month that contains `ref`."""
    start, end = period_bounds(period, ref)
    limits = get_limits(conn)
    spent = spent_by_category(conn, start, end)
    total = sum(spent.values())

    categories = []
    for c in conn.execute("SELECT id, name, color FROM categories ORDER BY sort_order, name"):
        s = spent.get(c["id"], 0)
        lim = limits.get((c["id"], period))
        categories.append({
            "category_id": c["id"], "name": c["name"], "color": c["color"],
            **summarize(s, lim, start, end, today),
        })
    if spent.get(None):
        categories.append({
            "category_id": None, "name": "Uncategorized", "color": "#cbd5e1",
            **summarize(spent[None], None, start, end, today),
        })

    return {
        "period": period,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "is_current": start <= today <= end,
        "days_total": (end - start).days + 1,
        "days_left": days_left(start, end, today),
        "overall": summarize(total, limits.get((None, period)), start, end, today),
        "categories": categories,
    }
