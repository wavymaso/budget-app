"""Look-and-feel choices, stored in the database so the app window keeps them
between launches (it doesn't keep browser storage)."""
import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from .. import config
from ..db import get_db, get_setting, set_setting

router = APIRouter(prefix="/api/preferences", tags=["preferences"])

DEFAULTS = {"theme": "auto", "summary_dismissed": None, "shortcut_snoozed_until": None}

THEMES = ("auto", "verde", "azul", "mar", "ciruela", "teja", "tinta", "noche")
# Themes from before the Campo look (Oct 2026), saved by older apps: each opens as its nearest new one.
OLD_THEMES = {"light": "verde", "dark": "noche", "sand": "teja", "ocean": "mar", "lavender": "ciruela",
              "rose": "ciruela", "noir": "noche"}


class PreferencesIn(BaseModel):
    theme: Literal["auto", "verde", "azul", "mar", "ciruela", "teja", "tinta", "noche",
                   "light", "dark", "sand", "ocean", "lavender", "rose", "noir"] | None = None
    summary_dismissed: str | None = Field(None, pattern=r"^\d{4}-\d{2}$")         # month whose summary was closed
    shortcut_snoozed_until: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")  # hide the Shortcut warning until


def _current(db: sqlite3.Connection) -> dict:
    prefs = {**DEFAULTS, **get_setting(db, "preferences", {})}
    prefs["theme"] = OLD_THEMES.get(prefs["theme"], prefs["theme"])
    return prefs


def _out(prefs: dict) -> dict:
    # "computer" isn't a preference: it lets the page say "Mac" or "PC".
    return {**prefs, "computer": config.COMPUTER}


@router.get("")
def get_preferences(db: sqlite3.Connection = Depends(get_db)):
    return _out(_current(db))


@router.put("")
def update_preferences(body: PreferencesIn, db: sqlite3.Connection = Depends(get_db)):
    prefs = _current(db)
    prefs.update(body.model_dump(exclude_none=True))
    prefs["theme"] = OLD_THEMES.get(prefs["theme"], prefs["theme"])
    set_setting(db, "preferences", prefs)
    db.commit()
    return _out(prefs)
