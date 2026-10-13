"""Apple Pay emails read by both the Mac and the iPhone: one expense, never two."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import config, email_sync, main
from app.db import connect
from tests.test_email import LINE, ME, make_email

MID = "<1@mail.gmail.com>"
UID = email_sync.expense_uid(MID)


def now(later=0):
    return (datetime.now(timezone.utc) + timedelta(seconds=later)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


@pytest.fixture
def mac(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "both.db")
    with TestClient(main.app, client=("127.0.0.1", 50000)) as c:
        yield c


def phone_expense(**kw):
    return {"uid": UID, "amount_cents": 1245, "merchant": "MERCADONA", "date": "2026-10-04", "note": None,
            "category_uid": None, "category_source": "none", "source": "email", "recurring_uid": None,
            "modified_at": now(), **kw}


def push(mac, expenses):
    r = mac.post("/api/sync", json={"changes": {"expenses": expenses}, "deleted": []})
    assert r.status_code == 200, r.text
    return r.json()


def import_on_mac(raw=None):
    with connect() as conn:
        return email_sync.process_email(conn, raw or make_email(LINE, msg_id=MID), ME, uid=1, use_ai=False)


def expenses():
    with connect() as conn:
        return conn.execute("SELECT uid, source FROM expenses WHERE amount_cents = 1245").fetchall()


def test_uid_is_stable_and_looks_like_the_others():
    assert UID == email_sync.expense_uid(MID) and len(UID) == 32 and UID != email_sync.expense_uid("<2@x>")
    # The phone computes the same thing (Swift: SHA256 of "email:<Message-ID>", first 32 hex digits).
    assert UID == __import__("hashlib").sha256(b"email:<1@mail.gmail.com>").hexdigest()[:32]


def test_mac_imports_with_the_shared_uid(mac):
    assert import_on_mac() == "imported"
    assert [r["uid"] for r in expenses()] == [UID]


def test_phone_first_then_mac(mac):
    push(mac, [phone_expense()])
    assert import_on_mac() == "skipped"
    assert len(expenses()) == 1
    with connect() as conn:
        assert conn.execute("SELECT status FROM email_messages").fetchone()["status"] == "imported"


def test_mac_first_then_phone(mac):
    import_on_mac()
    push(mac, [phone_expense()])          # the phone imported it too, before syncing
    assert len(expenses()) == 1


def test_deleted_on_phone_is_not_imported_by_the_mac(mac):
    push(mac, [phone_expense()])
    mac.post("/api/sync", json={"changes": {}, "deleted": [{"table": "expenses", "key": UID, "deleted_at": now(later=5)}]})
    assert expenses() == []
    assert import_on_mac() == "skipped"
    assert expenses() == []


def test_deleted_on_mac_is_not_brought_back_by_the_phone(mac):
    import_on_mac()
    with connect() as conn:
        conn.execute("DELETE FROM expenses WHERE uid = ?", (UID,))
        conn.commit()
    answer = push(mac, [phone_expense()])
    assert answer["dropped"] == [UID] and expenses() == []


def test_typed_expenses_with_a_deleted_uid_still_come_back(mac):
    # Only email expenses are refused: an expense typed on the phone and edited after a delete wins.
    import_on_mac()
    with connect() as conn:
        conn.execute("DELETE FROM expenses WHERE uid = ?", (UID,))
        conn.commit()
    assert push(mac, [phone_expense(source="phone")])["dropped"] == []
    assert len(expenses()) == 1


def test_phone_import_settles_the_macs_review_item(mac):
    # The Mac put it in review (looked like a typed expense); the phone imported it anyway.
    mac.post("/api/expenses", json={"amount": "12.45", "merchant": "Mercadona", "date": "2026-10-04"})
    assert import_on_mac() == "review"
    push(mac, [phone_expense()])
    with connect() as conn:
        row = conn.execute("SELECT status, expense_id FROM email_messages").fetchone()
    assert row["status"] == "imported" and row["expense_id"] is not None


def test_pull_tells_the_phone_which_gmail_to_read(mac):
    assert mac.get("/api/sync").json()["gmail"] is None
    with connect() as conn:
        email_sync.save_config(conn, address=ME, label="Budget", enabled=True)
    assert mac.get("/api/sync").json()["gmail"] == {"address": ME, "label": "Budget"}
