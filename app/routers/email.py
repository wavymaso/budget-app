"""Gmail import: settings, test connection, manual check, and the "Needs review" list."""
import sqlite3
from datetime import date as Date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import categorizer, email_sync, gmail
from ..db import get_db, get_setting
from ..models import ExpenseIn, to_cents
from .expenses import fetch_expense, insert_expense

router = APIRouter(prefix="/api/email", tags=["gmail"])


class SettingsIn(BaseModel):
    address: str = Field("", max_length=200)
    label: str = Field("Budget", min_length=1, max_length=100)
    enabled: bool = True
    password: str | None = Field(None, max_length=200, description="Only sent when changing it")
    forget_password: bool = False


class TestIn(BaseModel):
    address: str | None = None
    label: str | None = None
    password: str | None = None


def _public_settings(db: sqlite3.Connection) -> dict:
    cfg = email_sync.get_config(db)
    return {**cfg, "has_password": gmail.get_password(cfg["address"]) is not None,
            "last_sync": get_setting(db, "email_last_sync"),
            "check_every_minutes": email_sync.CHECK_EVERY_SECONDS // 60}


@router.get("/settings")
def read_settings(db: sqlite3.Connection = Depends(get_db)):
    return _public_settings(db)


@router.put("/settings")
def write_settings(body: SettingsIn, db: sqlite3.Connection = Depends(get_db)):
    address = body.address.strip()
    if address and "@" not in address:
        raise HTTPException(422, "That doesn't look like an email address")
    old = email_sync.get_config(db)
    if body.forget_password or (old["address"] and old["address"].lower() != address.lower()):
        gmail.delete_password(old["address"])
    if body.password:
        if not address:
            raise HTTPException(422, "Enter your Gmail address before the app password")
        try:
            gmail.set_password(address, gmail.clean_app_password(body.password))
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(500, f"Couldn't save the password in the Keychain: {exc}")
    email_sync.save_config(db, address=address, label=body.label.strip(), enabled=body.enabled)
    return _public_settings(db)


@router.post("/test")
def test(body: TestIn, db: sqlite3.Connection = Depends(get_db)):
    cfg = email_sync.get_config(db)
    address = (body.address or cfg["address"]).strip()
    label = (body.label or cfg["label"]).strip()
    password = gmail.clean_app_password(body.password) if body.password else gmail.get_password(address)
    return gmail.test_connection(address, password or "", label)


@router.post("/sync")
def sync_now():
    return email_sync.sync()


@router.get("/status")
def status(db: sqlite3.Connection = Depends(get_db)):
    review = db.execute("SELECT COUNT(*) FROM email_messages WHERE status = 'review'").fetchone()[0]
    return {"enabled": email_sync.get_config(db)["enabled"],
            "last_sync": get_setting(db, "email_last_sync"), "review_count": review}


@router.get("/review")
def review_list(db: sqlite3.Connection = Depends(get_db)):
    rows = db.execute(
        """SELECT m.*, e.merchant_raw AS duplicate_merchant, e.date AS duplicate_date,
                  e.amount_cents AS duplicate_amount_cents
           FROM email_messages m LEFT JOIN expenses e ON e.id = m.duplicate_of
           WHERE m.status = 'review' ORDER BY COALESCE(m.date, m.received_at) DESC, m.id DESC"""
    ).fetchall()
    return [dict(r) for r in rows]


class AcceptIn(BaseModel):
    merchant: str
    amount: str | float
    date: Date
    category_id: int | None = None


def _pending(db: sqlite3.Connection, item_id: int) -> sqlite3.Row:
    row = db.execute("SELECT * FROM email_messages WHERE id = ? AND status = 'review'", (item_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "That item isn't waiting for review any more")
    return row


@router.post("/review/{item_id}/accept", status_code=201)
def accept(item_id: int, body: AcceptIn, db: sqlite3.Connection = Depends(get_db)):
    row = _pending(db, item_id)
    expense = ExpenseIn(amount=body.amount, merchant=body.merchant, date=body.date,
                        category_id=body.category_id)
    if expense.category_id is not None:
        if not db.execute("SELECT 1 FROM categories WHERE id = ?", (expense.category_id,)).fetchone():
            raise HTTPException(422, "That category doesn't exist")
        # Picked or confirmed by you in the review list, so remember it.
        categorizer.learn(db, expense.merchant, expense.category_id)
        source = "manual"
    else:
        s = categorizer.suggest(db, expense.merchant)
        expense.category_id, source = s.category_id, s.source
    expense_id = insert_expense(
        db, amount_cents=to_cents(expense.amount), merchant=expense.merchant, date=expense.date.isoformat(),
        note=None, category_id=expense.category_id, category_source=source, source="email",
        import_hash=f"email:{row['message_id']}",
    )
    db.execute("UPDATE email_messages SET status = 'accepted', expense_id = ? WHERE id = ?", (expense_id, item_id))
    db.commit()
    return fetch_expense(db, expense_id)


@router.post("/review/{item_id}/dismiss")
def dismiss(item_id: int, db: sqlite3.Connection = Depends(get_db)):
    _pending(db, item_id)
    db.execute("UPDATE email_messages SET status = 'dismissed' WHERE id = ?", (item_id,))
    db.commit()
    return {"ok": True}
