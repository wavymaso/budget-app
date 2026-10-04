"""Numbers for the dashboard charts."""
import sqlite3
from datetime import date as Date
from datetime import timedelta

from fastapi import APIRouter, Depends, Query

from .. import budgets
from ..db import get_db

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("")
def dashboard(
    period: str = Query("month", pattern="^(week|month)$"),
    date: Date | None = None,
    months: int = Query(12, ge=1, le=36),
    db: sqlite3.Connection = Depends(get_db),
):
    today = Date.today()
    ref = date or today
    status = budgets.period_status(db, period, ref, today)
    start, end = Date.fromisoformat(status["start"]), Date.fromisoformat(status["end"])

    # Daily totals for every day in the period (zeros included).
    per_day = dict(db.execute(
        "SELECT date, SUM(amount_cents) FROM expenses WHERE date BETWEEN ? AND ? GROUP BY date",
        (start.isoformat(), end.isoformat()),
    ).fetchall())
    daily = []
    d = start
    while d <= end:
        daily.append({"date": d.isoformat(), "cents": per_day.get(d.isoformat(), 0)})
        d += timedelta(days=1)

    # Month-by-month trend ending with the month of the selected period.
    last_month = budgets.month_bounds(ref)[0]
    first_month = budgets.shift_period("month", last_month, -(months - 1))
    totals = dict(db.execute(
        "SELECT substr(date, 1, 7), SUM(amount_cents) FROM expenses "
        "WHERE date BETWEEN ? AND ? GROUP BY substr(date, 1, 7)",
        (first_month.isoformat(), budgets.month_bounds(last_month)[1].isoformat()),
    ).fetchall())
    trend = []
    for i in range(months):
        m = budgets.shift_period("month", first_month, i)
        trend.append({"month": m.isoformat()[:7], "cents": totals.get(m.isoformat()[:7], 0)})

    top = db.execute(
        """SELECT e.merchant_norm,
                  (SELECT merchant_raw FROM expenses x WHERE x.merchant_norm = e.merchant_norm
                   ORDER BY x.date DESC, x.id DESC LIMIT 1) AS merchant,
                  SUM(e.amount_cents) AS cents, COUNT(*) AS count,
                  c.name AS category_name, c.color AS category_color
           FROM expenses e LEFT JOIN categories c ON c.id = e.category_id
           WHERE e.date BETWEEN ? AND ?
           GROUP BY e.merchant_norm ORDER BY cents DESC LIMIT 8""",
        (start.isoformat(), end.isoformat()),
    ).fetchall()

    prev_start, prev_end = budgets.period_bounds(period, budgets.shift_period(period, ref, -1))
    prev_total = db.execute(
        "SELECT COALESCE(SUM(amount_cents), 0) FROM expenses WHERE date BETWEEN ? AND ?",
        (prev_start.isoformat(), prev_end.isoformat()),
    ).fetchone()[0]

    return {
        **status,
        "today": today.isoformat(),
        "prev_date": budgets.shift_period(period, ref, -1).isoformat(),
        "next_date": budgets.shift_period(period, ref, 1).isoformat(),
        "prev_total_cents": prev_total,
        "monthly_limit_cents": budgets.get_limits(db).get((None, "month")),
        "daily": daily,
        "trend": trend,
        "top_merchants": [dict(r) for r in top],
    }
