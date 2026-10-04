from datetime import date

import pytest

from app import budgets
from app.budgets import days_left, level, month_bounds, shift_period, summarize, week_bounds


def test_week_starts_on_monday():
    # Saturday 4 Oct 2026 -> Monday 28 Sep .. Sunday 4 Oct
    assert week_bounds(date(2026, 10, 4)) == (date(2026, 9, 28), date(2026, 10, 4))
    assert week_bounds(date(2026, 9, 28)) == (date(2026, 9, 28), date(2026, 10, 4))
    assert week_bounds(date(2026, 10, 5)) == (date(2026, 10, 5), date(2026, 10, 11))


@pytest.mark.parametrize("d, end", [
    (date(2026, 2, 10), date(2026, 2, 28)),
    (date(2028, 2, 1), date(2028, 2, 29)),   # leap year
    (date(2026, 12, 31), date(2026, 12, 31)),
    (date(2026, 4, 15), date(2026, 4, 30)),
])
def test_month_bounds(d, end):
    assert month_bounds(d) == (d.replace(day=1), end)


def test_shift_period():
    assert shift_period("week", date(2026, 10, 4), -1) == date(2026, 9, 21)
    assert shift_period("month", date(2026, 1, 31), -1) == date(2025, 12, 1)
    assert shift_period("month", date(2026, 12, 5), 1) == date(2027, 1, 1)


@pytest.mark.parametrize("spent, limit, expected", [
    (0, 10000, "green"),
    (7499, 10000, "green"),
    (7500, 10000, "amber"),    # 75% exactly -> amber
    (10000, 10000, "amber"),   # exactly at the limit is not over
    (10001, 10000, "red"),
    (500, 0, "red"),           # any spending over a 0 limit
    (0, 0, "green"),
    (-2000, 10000, "green"),   # refunds can push below zero
    (500, None, None),         # no limit set
])
def test_level(spent, limit, expected):
    assert level(spent, limit) == expected


def test_days_left_counts_today():
    start, end = date(2026, 9, 28), date(2026, 10, 4)
    assert days_left(start, end, date(2026, 9, 28)) == 7
    assert days_left(start, end, date(2026, 10, 4)) == 1
    assert days_left(start, end, date(2026, 10, 5)) == 0     # past period
    assert days_left(start, end, date(2026, 9, 1)) == 7      # future period


def test_left_and_per_day():
    # Wednesday of a Mon-Sun week: 5 days left including today.
    s = summarize(spent=4000, limit=10000, start=date(2026, 9, 28), end=date(2026, 10, 4),
                  today=date(2026, 9, 30))
    assert s["left_cents"] == 6000
    assert s["per_day_cents"] == 1200
    assert s["pct"] == 40.0
    assert s["level"] == "green"


def test_overspent_has_negative_left_and_zero_per_day():
    s = summarize(12000, 10000, date(2026, 10, 1), date(2026, 10, 31), date(2026, 10, 10))
    assert s["left_cents"] == -2000
    assert s["per_day_cents"] == 0
    assert s["level"] == "red"


def test_past_period_has_no_per_day():
    s = summarize(5000, 10000, date(2026, 9, 1), date(2026, 9, 30), date(2026, 10, 4))
    assert s["left_cents"] == 5000
    assert s["per_day_cents"] is None


def test_no_limit():
    s = summarize(5000, None, date(2026, 10, 1), date(2026, 10, 31), date(2026, 10, 4))
    assert s["left_cents"] is None and s["per_day_cents"] is None and s["level"] is None


def _add(conn, cents, day, category_id):
    conn.execute(
        "INSERT INTO expenses (amount_cents, merchant_raw, merchant_norm, category_id, date) "
        "VALUES (?, 'x', 'x', ?, ?)", (cents, category_id, day))


def test_period_status_from_database(conn, cat):
    g, t = cat("Groceries"), cat("Transport")
    conn.execute("INSERT INTO budgets (category_id, period, limit_cents) VALUES (NULL, 'week', 10000)")
    conn.execute("INSERT INTO budgets (category_id, period, limit_cents) VALUES (?, 'week', 4000)", (g,))
    _add(conn, 3500, "2026-09-28", g)   # Monday: in the week
    _add(conn, 1000, "2026-10-04", t)   # Sunday: in the week
    _add(conn, -500, "2026-10-01", g)   # refund
    _add(conn, 9999, "2026-09-27", g)   # previous Sunday: not in the week
    _add(conn, 700, "2026-10-02", None)  # uncategorized still counts toward overall

    st = budgets.period_status(conn, "week", date(2026, 10, 1), today=date(2026, 10, 1))
    assert (st["start"], st["end"], st["days_left"]) == ("2026-09-28", "2026-10-04", 4)
    assert st["overall"]["spent_cents"] == 3500 + 1000 - 500 + 700
    assert st["overall"]["left_cents"] == 10000 - 4700
    assert st["overall"]["per_day_cents"] == (10000 - 4700) // 4

    by_name = {c["name"]: c for c in st["categories"]}
    assert by_name["Groceries"]["spent_cents"] == 3000
    assert by_name["Groceries"]["level"] == "amber"          # 75%
    assert by_name["Transport"]["limit_cents"] is None
    assert by_name["Uncategorized"]["spent_cents"] == 700
