"""Monthly bills: list them, change the amount, or stop one."""
import sqlite3
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, field_validator

from .. import recurring
from ..db import get_db
from ..models import parse_amount, to_cents

router = APIRouter(prefix="/api/recurring", tags=["recurring"])


@router.get("")
def list_bills(db: sqlite3.Connection = Depends(get_db)):
    recurring.add_due(db)
    rows = db.execute(
        """SELECT r.*, c.name AS category_name, c.color AS category_color
           FROM recurring r LEFT JOIN categories c ON c.id = r.category_id
           ORDER BY r.day, r.merchant COLLATE NOCASE"""
    ).fetchall()
    return [{"id": r["id"], "merchant": r["merchant"], "amount_cents": r["amount_cents"], "day": r["day"],
             "next_date": r["next_date"], "note": r["note"], "category_id": r["category_id"],
             "category_name": r["category_name"], "category_color": r["category_color"]} for r in rows]


class BillUpdate(BaseModel):
    amount: Decimal

    @field_validator("amount", mode="before")
    @classmethod
    def _amount(cls, v):
        value = parse_amount(v) if isinstance(v, (str, int, float)) else v
        if value <= 0:
            raise ValueError("amount must be above 0")
        return value


@router.patch("/{bill_id}")
def update_bill(bill_id: int, body: BillUpdate, db: sqlite3.Connection = Depends(get_db)):
    """A new price applies from the next time the bill is added."""
    if not db.execute("UPDATE recurring SET amount_cents = ? WHERE id = ?", (to_cents(body.amount), bill_id)).rowcount:
        raise HTTPException(404, "Bill not found")
    db.commit()
    return {"ok": True}


@router.delete("/{bill_id}", status_code=204)
def stop_bill(bill_id: int, db: sqlite3.Connection = Depends(get_db)):
    """Stop repeating. Expenses it already added stay."""
    db.execute("UPDATE expenses SET recurring_id = NULL WHERE recurring_id = ?", (bill_id,))
    if not db.execute("DELETE FROM recurring WHERE id = ?", (bill_id,)).rowcount:
        raise HTTPException(404, "Bill not found")
    db.commit()
    return Response(status_code=204)
