"""The iPhone app's sync: tracking changes on the Mac and applying the phone's."""
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import config, main, recurring
from app.db import connect

def _stamp(hours):
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


T1, T2, T3 = _stamp(-2), _stamp(-1), _stamp(1)   # two edits in the past, one "just now" on a fast phone clock


@pytest.fixture
def mac(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "sync.db")
    with TestClient(main.app, client=("127.0.0.1", 50000)) as c:
        yield c


def pull(mac, since=0):
    return mac.get("/api/sync", params={"since": since}).json()


def push(mac, changes=None, deleted=None):
    r = mac.post("/api/sync", json={"changes": changes or {}, "deleted": deleted or []})
    assert r.status_code == 200, r.text
    return r.json()


def by_uid(rows):
    return {r["uid"]: r for r in rows}


def test_first_pull_has_everything_with_permanent_ids(mac):
    mac.post("/api/expenses", json={"amount": "4.50", "merchant": "Mercadona", "date": "2026-10-12"})
    s = pull(mac)
    assert s["rev"] > 0 and s["deleted"] == []
    exp = s["tables"]["expenses"][0]
    assert len(exp["uid"]) == 32 and exp["amount_cents"] == 450 and exp["modified_at"].endswith("Z")
    cats = by_uid(s["tables"]["categories"])
    assert exp["category_uid"] in cats and cats[exp["category_uid"]]["name"] == "Groceries"
    assert s["tables"]["keyword_rules"], "the phone gets the keyword rules to categorize offline"


def test_only_changes_since_last_time_and_deletions(mac):
    e = mac.post("/api/expenses", json={"amount": "10", "merchant": "Zara", "date": "2026-10-12"}).json()
    rev = pull(mac)["rev"]
    assert pull(mac, rev)["tables"]["expenses"] == []
    mac.put(f"/api/expenses/{e['id']}", json={"amount": "12", "merchant": "Zara", "date": "2026-10-12"})
    changed = pull(mac, rev)
    assert [x["amount_cents"] for x in changed["tables"]["expenses"]] == [1200]
    uid = changed["tables"]["expenses"][0]["uid"]
    rev = changed["rev"]
    mac.delete(f"/api/expenses/{e['id']}")
    assert pull(mac, rev)["deleted"] == [{"table": "expenses", "key": uid, "deleted_at": pull(mac, rev)["deleted"][0]["deleted_at"]}]


def test_private_settings_never_leave_the_mac(mac):
    mac.put("/api/phone", json={"enabled": False, "port": 8000, "password": "secret123"})
    mac.put("/api/preferences", json={"theme": "noir"})
    keys = {r["key"] for r in pull(mac)["tables"]["settings"]}
    assert "preferences" in keys and not keys & {"phone_password", "phone_access", "email"}
    push(mac, {"settings": [{"key": "phone_password", "value": "x", "modified_at": T3}]})
    conn = connect()
    assert "x" not in conn.execute("SELECT value FROM settings WHERE key = 'phone_password'").fetchone()[0]


def test_expense_added_on_the_phone(mac):
    groceries = next(c for c in pull(mac)["tables"]["categories"] if c["name"] == "Groceries")
    push(mac, {"expenses": [
        {"uid": "p1", "amount_cents": 1240, "merchant": "Carrefour", "date": "2026-10-13", "category_uid": groceries["uid"],
         "category_source": "manual", "modified_at": T1},
        {"uid": "p2", "amount_cents": 990, "merchant": "MERCADONA 1234", "date": "2026-10-13", "modified_at": T1},
    ]})
    items = {x["merchant"]: x for x in mac.get("/api/expenses").json()["items"]}
    assert items["Carrefour"]["category_name"] == "Groceries"
    assert items["MERCADONA 1234"]["category_name"] == "Groceries", "the Mac categorizes what the phone couldn't"
    # Sending the same thing again changes nothing.
    push(mac, {"expenses": [{"uid": "p1", "amount_cents": 1240, "merchant": "Carrefour", "date": "2026-10-13", "modified_at": T1}]})
    assert mac.get("/api/expenses").json()["count"] == 2


def test_newer_edit_wins(mac):
    push(mac, {"expenses": [{"uid": "e1", "amount_cents": 100, "merchant": "Bar", "date": "2026-10-13", "modified_at": T2}]})
    push(mac, {"expenses": [{"uid": "e1", "amount_cents": 999, "merchant": "Bar", "date": "2026-10-13", "modified_at": T1}]})
    assert mac.get("/api/expenses").json()["items"][0]["amount_cents"] == 100, "an older phone edit loses"
    push(mac, {"expenses": [{"uid": "e1", "amount_cents": 250, "merchant": "Bar", "date": "2026-10-13", "modified_at": T3}]})
    assert mac.get("/api/expenses").json()["items"][0]["amount_cents"] == 250


def test_deleting_from_the_phone_unless_edited_here_since(mac):
    push(mac, {"expenses": [{"uid": "d1", "amount_cents": 100, "merchant": "A", "date": "2026-10-13", "modified_at": T1},
                            {"uid": "d2", "amount_cents": 100, "merchant": "B", "date": "2026-10-13", "modified_at": T3}]})
    push(mac, deleted=[{"table": "expenses", "key": "d1", "deleted_at": T2}, {"table": "expenses", "key": "d2", "deleted_at": T2}])
    assert [x["merchant"] for x in mac.get("/api/expenses").json()["items"]] == ["B"]


def test_category_made_on_both_devices_is_merged(mac):
    mac.post("/api/categories", json={"name": "Gym", "color": "#112233"})
    r = push(mac, {"categories": [{"uid": "phone-gym", "name": "gym", "color": "#445566", "modified_at": T1}],
                   "expenses": [{"uid": "x1", "amount_cents": 3000, "merchant": "Basic-Fit", "date": "2026-10-13",
                                 "category_uid": "phone-gym", "category_source": "manual", "modified_at": T1}]})
    mac_gym = next(c for c in pull(mac)["tables"]["categories"] if c["name"] == "Gym")
    assert r["remap"] == {"phone-gym": mac_gym["uid"]}
    assert mac.get("/api/expenses").json()["items"][0]["category_name"] == "Gym"
    assert len([c for c in mac.get("/api/categories").json() if c["name"].lower() == "gym"]) == 1


def test_bill_added_by_both_devices_counts_once(mac):
    e = mac.post("/api/expenses", json={"amount": "11.99", "merchant": "Spotify", "date": "2026-09-05", "repeat_monthly": True}).json()
    bill = pull(mac)["tables"]["recurring"][0]
    # The phone added October's Spotify first, with the shared occurrence id...
    push(mac, {"expenses": [{"uid": f"rec:{bill['uid']}:2026-10-05", "amount_cents": 1199, "merchant": "Spotify",
                             "date": "2026-10-05", "recurring_uid": bill["uid"], "modified_at": T1}]})
    # ...then the Mac catches up on bills.
    conn = connect()
    recurring.add_due(conn, date(2026, 10, 13))
    n = conn.execute("SELECT COUNT(*) FROM expenses WHERE merchant_raw = 'Spotify' AND date = '2026-10-05'").fetchone()[0]
    assert n == 1 and e["id"]


def test_budgets_keep_their_id_and_merge(mac):
    mac.put("/api/budgets", json={"category_id": None, "period": "month", "limit": "600"})
    uid = pull(mac)["tables"]["budgets"][0]["uid"]
    mac.put("/api/budgets", json={"category_id": None, "period": "month", "limit": "650"})
    assert pull(mac)["tables"]["budgets"][0]["uid"] == uid
    r = push(mac, {"budgets": [{"uid": "phone-b", "category_uid": None, "period": "month", "limit_cents": 70000, "modified_at": "2099-01-01T00:00:00.000Z"}]})
    assert r["remap"] == {"phone-b": uid}
    assert pull(mac)["tables"]["budgets"][0]["limit_cents"] == 70000


def test_rows_from_before_sync_existed_are_in_the_first_pull(mac):
    conn = connect()
    conn.execute("INSERT INTO expenses (amount_cents, merchant_raw, merchant_norm, date) VALUES (500, 'Old', 'old', '2025-01-01')")
    conn.execute("UPDATE expenses SET rev = 0")   # as if made before sync existed (triggers skip: rev changes)
    conn.commit()
    assert "Old" in [e["merchant"] for e in pull(mac)["tables"]["expenses"]]
