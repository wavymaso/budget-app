"""Weekly and monthly limits, overall and per category."""
import sqlite3
from datetime import date as Date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from .. import budgets, recurring
from ..db import get_db
from ..models import parse_amount, to_cents

router = APIRouter(prefix="/api/budgets", tags=["budgets"])


class LimitIn(BaseModel):
    category_id: int | None = None      # None = overall limit
    period: str
    limit: Decimal | None = None        # euros; None or empty removes the limit

    @field_validator("period")
    @classmethod
    def _period(cls, v: str) -> str:
        if v not in ("week", "month"):
            raise ValueError("period must be 'week' or 'month'")
        return v

    @field_validator("limit", mode="before")
    @classmethod
    def _limit(cls, v):
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        value = parse_amount(v) if isinstance(v, (str, int, float)) else v
        if value < 0:
            raise ValueError("limit can't be negative")
        return value


@router.get("")
def list_limits(db: sqlite3.Connection = Depends(get_db)):
    return [
        {"category_id": cid, "period": period, "limit_cents": cents}
        for (cid, period), cents in budgets.get_limits(db).items()
    ]


@router.put("")
def set_limit(body: LimitIn, db: sqlite3.Connection = Depends(get_db)):
    if body.category_id is not None and not db.execute(
        "SELECT 1 FROM categories WHERE id = ?", (body.category_id,)
    ).fetchone():
        raise HTTPException(422, "That category doesn't exist")
    db.execute(
        "DELETE FROM budgets WHERE COALESCE(category_id, 0) = COALESCE(?, 0) AND period = ?",
        (body.category_id, body.period),
    )
    if body.limit is not None:
        db.execute(
            "INSERT INTO budgets (category_id, period, limit_cents) VALUES (?, ?, ?)",
            (body.category_id, body.period, to_cents(body.limit)),
        )
    db.commit()
    return {"category_id": body.category_id, "period": body.period,
            "limit_cents": to_cents(body.limit) if body.limit is not None else None}


@router.get("/status")
def status(date: Date | None = None, db: sqlite3.Connection = Depends(get_db)):
    today = Date.today()
    ref = date or today
    recurring.add_due(db, today)
    month = budgets.period_status(db, "month", ref, today)
    month["bills"] = recurring.month_bills(db, Date.fromisoformat(month["start"]), Date.fromisoformat(month["end"]), today)
    return {
        "today": today.isoformat(),
        "week": budgets.period_status(db, "week", ref, today),
        "month": month,
    }
