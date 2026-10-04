"""List and manage categories."""
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field, field_validator

from ..db import get_db

router = APIRouter(prefix="/api/categories", tags=["categories"])

HEX_COLOR = r"^#[0-9a-fA-F]{6}$"


def _clean_name(v: str | None) -> str | None:
    if v is None:
        return None
    v = " ".join(v.split())
    if not v:
        raise ValueError("name is required")
    if v.lower() == "uncategorized":
        raise ValueError("'Uncategorized' is reserved")
    return v


class CategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    color: str = Field("#64748b", pattern=HEX_COLOR)

    _name = field_validator("name")(_clean_name)


class CategoryPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=40)
    color: str | None = Field(None, pattern=HEX_COLOR)

    _name = field_validator("name")(_clean_name)


class ReorderIn(BaseModel):
    ids: list[int]


def _fetch(db: sqlite3.Connection, category_id: int) -> dict:
    row = db.execute(
        """SELECT c.id, c.name, c.color, c.sort_order,
                  (SELECT COUNT(*) FROM expenses e WHERE e.category_id = c.id) AS expense_count
           FROM categories c WHERE c.id = ?""",
        (category_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Category not found")
    return dict(row)


@router.get("")
def list_categories(db: sqlite3.Connection = Depends(get_db)):
    rows = db.execute(
        """SELECT c.id, c.name, c.color, c.sort_order,
                  (SELECT COUNT(*) FROM expenses e WHERE e.category_id = c.id) AS expense_count
           FROM categories c ORDER BY c.sort_order, c.name"""
    ).fetchall()
    return [dict(r) for r in rows]


@router.post("", status_code=201)
def create_category(body: CategoryIn, db: sqlite3.Connection = Depends(get_db)):
    next_order = db.execute("SELECT COALESCE(MAX(sort_order), -1) + 1 FROM categories").fetchone()[0]
    try:
        cur = db.execute(
            "INSERT INTO categories (name, color, sort_order) VALUES (?, ?, ?)",
            (body.name, body.color.lower(), next_order),
        )
    except sqlite3.IntegrityError:
        raise HTTPException(409, f"A category called '{body.name}' already exists")
    db.commit()
    return _fetch(db, cur.lastrowid)


@router.patch("/{category_id}")
def update_category(category_id: int, body: CategoryPatch, db: sqlite3.Connection = Depends(get_db)):
    _fetch(db, category_id)
    try:
        if body.name is not None:
            db.execute("UPDATE categories SET name = ? WHERE id = ?", (body.name, category_id))
        if body.color is not None:
            db.execute("UPDATE categories SET color = ? WHERE id = ?", (body.color.lower(), category_id))
    except sqlite3.IntegrityError:
        raise HTTPException(409, f"A category called '{body.name}' already exists")
    db.commit()
    return _fetch(db, category_id)


@router.post("/reorder")
def reorder_categories(body: ReorderIn, db: sqlite3.Connection = Depends(get_db)):
    for i, cid in enumerate(body.ids):
        db.execute("UPDATE categories SET sort_order = ? WHERE id = ?", (i, cid))
    db.commit()
    return list_categories(db)


@router.delete("/{category_id}", status_code=204)
def delete_category(
    category_id: int,
    move_to: str = Query("none", description="Category id to move expenses and rules to, or 'none'"),
    db: sqlite3.Connection = Depends(get_db),
):
    _fetch(db, category_id)
    target = None
    if move_to != "none":
        if not move_to.isdigit() or int(move_to) == category_id:
            raise HTTPException(422, "move_to must be another category id or 'none'")
        target = _fetch(db, int(move_to))["id"]
    db.execute("UPDATE expenses SET category_id = ?, category_source = CASE WHEN ? IS NULL THEN 'none' ELSE 'manual' END "
               "WHERE category_id = ?", (target, target, category_id))
    if target is not None:
        # Keep what the app learned: those merchants now map to the new category.
        db.execute("UPDATE merchant_rules SET category_id = ? WHERE category_id = ?", (target, category_id))
        db.execute("UPDATE OR IGNORE keyword_rules SET category_id = ? WHERE category_id = ?", (target, category_id))
        db.execute("UPDATE OR IGNORE ai_cache SET category_id = ? WHERE category_id = ?", (target, category_id))
    db.execute("DELETE FROM categories WHERE id = ?", (category_id,))
    db.commit()
    return Response(status_code=204)
