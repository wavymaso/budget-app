from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import config, main, recurring
from app.recurring import next_month, on_day


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "bills.db")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with TestClient(main.app, client=("127.0.0.1", 50000)) as c:
        yield c


def test_short_months_use_their_last_day():
    assert on_day(2026, 2, 31) == date(2026, 2, 28)
    assert on_day(2028, 2, 30) == date(2028, 2, 29)
    # The 31st comes back after a short month.
    assert next_month(date(2026, 2, 28), 31) == date(2026, 3, 31)
    assert next_month(date(2026, 12, 15), 15) == date(2027, 1, 15)


def test_repeat_monthly_creates_a_bill_that_starts_next_month(client):
    r = client.post("/api/expenses", json={"amount": "10,99", "merchant": "Spotify", "date": date.today().isoformat(),
                                            "repeat_monthly": True})
    assert r.status_code == 201, r.text
    assert r.json()["recurring_id"] is not None
    bills = client.get("/api/recurring").json()
    assert len(bills) == 1
    assert (bills[0]["merchant"], bills[0]["amount_cents"], bills[0]["day"]) == ("Spotify", 1099, date.today().day)
    assert bills[0]["next_date"] > date.today().isoformat()
    assert client.get("/api/expenses").json()["count"] == 1   # nothing extra added yet


def test_missed_months_are_added_on_their_days(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "m.db")
    from app import db
    db.init_db()
    conn = db.connect()
    try:
        conn.execute("INSERT INTO expenses (amount_cents, merchant_raw, merchant_norm, date) VALUES (2499, 'Basic-Fit', 'basic fit', '2026-07-31')")
        recurring.create(conn, expense_id=1, merchant="Basic-Fit", amount_cents=2499, category_id=None, note=None,
                         first=date(2026, 7, 31))
        assert recurring.add_due(conn, date(2026, 11, 5)) == 3
        dates = [r[0] for r in conn.execute("SELECT date FROM expenses ORDER BY date")]
        assert dates == ["2026-07-31", "2026-08-31", "2026-09-30", "2026-10-31"]
        assert conn.execute("SELECT next_date FROM recurring").fetchone()[0] == "2026-11-30"
    finally:
        conn.close()


def test_add_due_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "b.db")
    from app import db
    db.init_db()
    conn = db.connect()
    try:
        conn.execute("INSERT INTO expenses (amount_cents, merchant_raw, merchant_norm, date) VALUES (500, 'Gym', 'gym', '2026-08-03')")
        recurring.create(conn, expense_id=1, merchant="Gym", amount_cents=500, category_id=None, note=None,
                         first=date(2026, 8, 3))
        assert recurring.add_due(conn, date(2026, 10, 7)) == 2     # 3 Sep and 3 Oct
        assert recurring.add_due(conn, date(2026, 10, 7)) == 0
        bills = recurring.month_bills(conn, date(2026, 10, 1), date(2026, 10, 31), date(2026, 10, 7))
        assert bills == {"paid_cents": 500, "upcoming_cents": 0}
        nov = recurring.month_bills(conn, date(2026, 11, 1), date(2026, 11, 30), date(2026, 10, 7))
        assert nov["upcoming_cents"] == 500
    finally:
        conn.close()


def test_upcoming_bills_count_toward_this_month(client):
    today = date.today()
    first = date(today.year - (today.month == 1), (today.month - 2) % 12 + 1, 28)   # the 28th of last month
    client.post("/api/expenses", json={"amount": "50", "merchant": "Rent share", "date": first.isoformat(), "repeat_monthly": True})
    bills = client.get("/api/budgets/status").json()["month"]["bills"]
    if today.day < 28:
        assert bills == {"paid_cents": 0, "upcoming_cents": 5000}
    else:
        assert bills == {"paid_cents": 5000, "upcoming_cents": 0}


def test_changing_and_stopping_a_bill(client):
    e = client.post("/api/expenses", json={"amount": "8", "merchant": "Netflix", "repeat_monthly": True}).json()
    bill = client.get("/api/recurring").json()[0]
    assert client.patch(f"/api/recurring/{bill['id']}", json={"amount": "9,99"}).status_code == 200
    assert client.get("/api/recurring").json()[0]["amount_cents"] == 999
    assert client.delete(f"/api/recurring/{bill['id']}").status_code == 204
    assert client.get("/api/recurring").json() == []
    # The expense it already made stays, just no longer linked.
    assert client.get(f"/api/expenses/{e['id']}").json()["recurring_id"] is None
