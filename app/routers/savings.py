"""Savings: turn it on, set a goal, add or take out money."""
import sqlite3
from datetime import date as Date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, field_validator

from .. import savings
from ..db import get_db
from ..models import parse_amount, to_cents

router = APIRouter(prefix="/api/savings", tags=["savings"])


def _amount(v):
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    return parse_amount(v) if isinstance(v, (str, int, float)) else v


class SavingsIn(BaseModel):
    enabled: bool | None = None
    goal_name: str | None = Field(None, max_length=60)
    goal: Decimal | None = None          # euros; send "" or null with clear_goal to remove
    clear_goal: bool = False

    @field_validator("goal", mode="before")
    @classmethod
    def _goal(cls, v):
        return _amount(v)


class MoveIn(BaseModel):
    amount: Decimal                      # positive = add, negative = take out
    note: str | None = Field(None, max_length=200)
    date: Date | None = None

    @field_validator("amount", mode="before")
    @classmethod
    def _amt(cls, v):
        value = _amount(v)
        if value is None or value == 0:
            raise ValueError("enter an amount")
        return value


@router.get("")
def get_savings(db: sqlite3.Connection = Depends(get_db)):
    return savings.summary(db)


@router.put("")
def update_savings(body: SavingsIn, db: sqlite3.Connection = Depends(get_db)):
    changes = {}
    if body.enabled is not None:
        changes["enabled"] = body.enabled
    if body.clear_goal:
        changes.update(goal_name=None, goal_cents=None)
    else:
        if body.goal_name is not None:
            changes["goal_name"] = body.goal_name.strip() or None
        if body.goal is not None:
            if body.goal <= 0:
                raise HTTPException(422, "The goal must be above 0")
            changes["goal_cents"] = to_cents(body.goal)
    savings.save_config(db, **changes)
    return savings.summary(db)


@router.post("/moves", status_code=201)
def add_move(body: MoveIn, db: sqlite3.Connection = Depends(get_db)):
    db.execute("INSERT INTO savings_moves (date, amount_cents, note) VALUES (?, ?, ?)",
               ((body.date or Date.today()).isoformat(), to_cents(body.amount), (body.note or "").strip() or None))
    db.commit()
    return savings.summary(db)


@router.delete("/moves/{move_id}", status_code=204)
def delete_move(move_id: int, db: sqlite3.Connection = Depends(get_db)):
    if not db.execute("DELETE FROM savings_moves WHERE id = ?", (move_id,)).rowcount:
        raise HTTPException(404, "Not found")
    db.commit()
    return Response(status_code=204)
