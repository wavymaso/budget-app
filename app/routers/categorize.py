"""Live category suggestions and the merchants the app has learned."""
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel

from .. import categorizer, config
from ..db import get_db

router = APIRouter(prefix="/api", tags=["categorization"])


@router.get("/suggest")
def suggest(
    merchant: str = Query(..., max_length=200),
    ai: bool = Query(False, description="Ask Claude if nothing else matches"),
    db: sqlite3.Connection = Depends(get_db),
):
    s = categorizer.suggest(db, merchant, use_ai=ai)
    cat = db.execute("SELECT name, color FROM categories WHERE id = ?", (s.category_id,)).fetchone() \
        if s.category_id else None
    return {
        "category_id": s.category_id,
        "category_name": cat["name"] if cat else None,
        "category_color": cat["color"] if cat else None,
        "source": s.source,
        "normalized": s.normalized,
        "matched": s.matched,
        "ai_enabled": config.anthropic_api_key() is not None,
    }


@router.get("/rules")
def list_rules(db: sqlite3.Connection = Depends(get_db)):
    rows = db.execute(
        """SELECT r.merchant_norm, r.category_id, r.hit_count, r.updated_at,
                  c.name AS category_name, c.color AS category_color
           FROM merchant_rules r JOIN categories c ON c.id = r.category_id
           ORDER BY r.updated_at DESC"""
    ).fetchall()
    return [dict(r) for r in rows]


class RuleIn(BaseModel):
    category_id: int


@router.put("/rules/{merchant_norm}")
def update_rule(merchant_norm: str, body: RuleIn, db: sqlite3.Connection = Depends(get_db)):
    if not db.execute("SELECT 1 FROM categories WHERE id = ?", (body.category_id,)).fetchone():
        raise HTTPException(422, "That category doesn't exist")
    cur = db.execute(
        "UPDATE merchant_rules SET category_id = ?, updated_at = datetime('now') WHERE merchant_norm = ?",
        (body.category_id, merchant_norm),
    )
    if cur.rowcount == 0:
        raise HTTPException(404, "No learned rule for that merchant")
    db.commit()
    return {"ok": True}


@router.delete("/rules/{merchant_norm}", status_code=204)
def delete_rule(merchant_norm: str, db: sqlite3.Connection = Depends(get_db)):
    db.execute("DELETE FROM merchant_rules WHERE merchant_norm = ?", (merchant_norm,))
    db.commit()
    return Response(status_code=204)
