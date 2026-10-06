from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import config, db, main, savings


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "s.db")
    db.init_db()
    c = db.connect()
    yield c
    c.close()


def spend(conn, day, cents):
    conn.execute("INSERT INTO expenses (amount_cents, merchant_raw, merchant_norm, date) VALUES (?, 'x', 'x', ?)", (cents, day))


def set_monthly_limit(conn, cents):
    conn.execute("DELETE FROM budgets WHERE category_id IS NULL AND period = 'month'")
    conn.execute("INSERT INTO budgets (category_id, period, limit_cents) VALUES (NULL, 'month', ?)", (cents,))


def test_counting_starts_the_month_you_turn_it_on(conn):
    set_monthly_limit(conn, 60000)
    spend(conn, "2026-09-10", 50000)          # before savings started: not counted
    savings.save_config(conn, today=date(2026, 10, 7), enabled=True)
    spend(conn, "2026-10-10", 52000)
    assert savings.summary(conn, date(2026, 10, 20))["total_cents"] == 0     # October isn't over yet
    s = savings.summary(conn, date(2026, 11, 2))
    assert s["total_cents"] == 8000
    assert s["months"] == [{"month": "2026-10", "limit_cents": 60000, "spent_cents": 52000, "saved_cents": 8000}]


def test_a_finished_month_keeps_the_budget_it_had(conn):
    set_monthly_limit(conn, 60000)
    savings.save_config(conn, today=date(2026, 10, 1), enabled=True)
    spend(conn, "2026-10-05", 40000)
    savings.summary(conn, date(2026, 11, 1))
    set_monthly_limit(conn, 90000)            # raising the budget later...
    spend(conn, "2026-11-05", 100000)         # ...and overspending in November
    s = savings.summary(conn, date(2026, 12, 1))
    assert [m["saved_cents"] for m in s["months"]] == [-10000, 20000]
    assert s["total_cents"] == 10000


def test_moves_and_goal_through_the_api(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "api.db")
    with TestClient(main.app, client=("127.0.0.1", 50000)) as c:
        assert c.get("/api/savings").json()["enabled"] is False
        s = c.put("/api/savings", json={"enabled": True, "goal_name": "Lisbon", "goal": "500"}).json()
        assert (s["enabled"], s["goal_name"], s["goal_cents"]) == (True, "Lisbon", 50000)
        assert s["start_month"] == date.today().isoformat()[:7]
        s = c.post("/api/savings/moves", json={"amount": "200", "note": "Already saved"}).json()
        s = c.post("/api/savings/moves", json={"amount": "-45,50", "note": "Train tickets"}).json()
        assert s["total_cents"] == 15450
        assert c.post("/api/savings/moves", json={"amount": "0"}).status_code == 422
        assert s["moves"][0]["note"] == "Train tickets"           # newest first
        assert c.delete(f"/api/savings/moves/{s['moves'][0]['id']}").status_code == 204
        assert c.get("/api/savings").json()["total_cents"] == 20000
        s = c.put("/api/savings", json={"clear_goal": True}).json()
        assert s["goal_name"] is None and s["goal_cents"] is None and s["enabled"] is True
