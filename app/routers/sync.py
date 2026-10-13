"""The iPhone app's connection: what changed here, and the phone's changes."""
import sqlite3

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from .. import recurring, sync
from ..db import get_db

router = APIRouter(prefix="/api/sync", tags=["sync"])


@router.get("")
def pull(since: int = Query(0, ge=0), db: sqlite3.Connection = Depends(get_db)):
    """Everything that changed on the Mac after `since` (0 = everything)."""
    recurring.add_due(db)   # bills due today, so the phone sees them
    return sync.changes_since(db, since)


class PushIn(BaseModel):
    changes: dict[str, list[dict]] = Field(default_factory=dict)
    deleted: list[dict] = Field(default_factory=list, max_length=5000)


@router.post("")
def push(body: PushIn, db: sqlite3.Connection = Depends(get_db)):
    """The phone's changes. The newer edit wins; returns the Mac's change counter."""
    result = sync.apply(db, {k: v for k, v in body.changes.items() if k in sync.PUSHABLE}, body.deleted)
    return {**result, "rev": sync.current_rev(db)}
