"""Look-and-feel choices, stored in the database so the app window keeps them
between launches (it doesn't keep browser storage)."""
import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..db import get_db, get_setting, set_setting

router = APIRouter(prefix="/api/preferences", tags=["preferences"])

DEFAULTS = {"theme": "auto"}


class PreferencesIn(BaseModel):
    theme: Literal["auto", "light", "dark", "sand", "ocean", "lavender"] | None = None


def _current(db: sqlite3.Connection) -> dict:
    return {**DEFAULTS, **get_setting(db, "preferences", {})}


@router.get("")
def get_preferences(db: sqlite3.Connection = Depends(get_db)):
    return _current(db)


@router.put("")
def update_preferences(body: PreferencesIn, db: sqlite3.Connection = Depends(get_db)):
    prefs = _current(db)
    prefs.update(body.model_dump(exclude_none=True))
    set_setting(db, "preferences", prefs)
    db.commit()
    return prefs
