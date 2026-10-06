"""Add, list, edit and delete expenses."""
import secrets
import sqlite3
from datetime import date as Date
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from pydantic import BaseModel, Field, ValidationError, field_validator

from .. import categorizer, config, recurring
from ..db import get_db
from ..models import ExpenseIn, to_cents
from ..normalize import normalize_merchant

router = APIRouter(prefix="/api/expenses", tags=["expenses"])

SELECT_EXPENSE = """
SELECT e.*, c.name AS category_name, c.color AS category_color
FROM expenses e LEFT JOIN categories c ON c.id = e.category_id
"""

SORT_COLUMNS = {
    "date": "e.date {o}, e.id {o}",
    "amount": "e.amount_cents {o}, e.date DESC",
    "merchant": "e.merchant_raw COLLATE NOCASE {o}, e.date DESC",
    "category": "COALESCE(c.name, '') COLLATE NOCASE {o}, e.date DESC",
}


def expense_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "amount_cents": row["amount_cents"],
        "merchant": row["merchant_raw"],
        "merchant_norm": row["merchant_norm"],
        "category_id": row["category_id"],
        "category_name": row["category_name"],
        "category_color": row["category_color"],
        "date": row["date"],
        "note": row["note"],
        "source": row["source"],
        "category_source": row["category_source"],
        "recurring_id": row["recurring_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def fetch_expense(db: sqlite3.Connection, expense_id: int) -> dict:
    row = db.execute(SELECT_EXPENSE + " WHERE e.id = ?", (expense_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Expense not found")
    return expense_to_dict(row)


def check_category(db: sqlite3.Connection, category_id: int | None) -> None:
    if category_id is not None and not db.execute(
        "SELECT 1 FROM categories WHERE id = ?", (category_id,)
    ).fetchone():
        raise HTTPException(422, "That category doesn't exist")


def insert_expense(
    db: sqlite3.Connection,
    *,
    amount_cents: int,
    merchant: str,
    date: str,
    note: str | None,
    category_id: int | None,
    category_source: str,
    source: str,
    import_hash: str | None = None,
) -> int:
    cur = db.execute(
        """INSERT INTO expenses (amount_cents, merchant_raw, merchant_norm, category_id,
                                 date, note, source, category_source, import_hash)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (amount_cents, merchant, normalize_merchant(merchant), category_id,
         date, note, source, category_source, import_hash),
    )
    return cur.lastrowid


@router.get("")
def list_expenses(
    q: str | None = None,
    category_id: str | None = Query(None, description="A category id, or 'none' for Uncategorized"),
    date_from: Date | None = None,
    date_to: Date | None = None,
    sort: str = Query("date", pattern="^(date|amount|merchant|category)$"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: sqlite3.Connection = Depends(get_db),
):
    recurring.add_due(db)
    where, params = [], []
    if q and q.strip():
        like = f"%{q.strip()}%"
        where.append("(e.merchant_raw LIKE ? OR e.note LIKE ? OR c.name LIKE ?)")
        params += [like, like, like]
    if category_id == "none":
        where.append("e.category_id IS NULL")
    elif category_id:
        if not category_id.isdigit():
            raise HTTPException(422, "category_id must be a number or 'none'")
        where.append("e.category_id = ?")
        params.append(int(category_id))
    if date_from:
        where.append("e.date >= ?")
        params.append(date_from.isoformat())
    if date_to:
        where.append("e.date <= ?")
        params.append(date_to.isoformat())

    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    order_sql = SORT_COLUMNS[sort].format(o=order.upper())
    rows = db.execute(
        f"{SELECT_EXPENSE}{where_sql} ORDER BY {order_sql} LIMIT ? OFFSET ?",
        params + [limit, offset],
    ).fetchall()
    totals = db.execute(
        f"SELECT COUNT(*) AS n, COALESCE(SUM(e.amount_cents), 0) AS total "
        f"FROM expenses e LEFT JOIN categories c ON c.id = e.category_id{where_sql}",
        params,
    ).fetchone()
    return {
        "items": [expense_to_dict(r) for r in rows],
        "count": totals["n"],
        "total_cents": totals["total"],
    }


@router.get("/{expense_id}")
def get_expense(expense_id: int, db: sqlite3.Connection = Depends(get_db)):
    return fetch_expense(db, expense_id)


def resolve_category(
    db: sqlite3.Connection, body: ExpenseIn, *, use_ai: bool
) -> tuple[int | None, str]:
    """Use the category the client sent (and learn it), or auto-categorize."""
    if body.category_id is not None:
        check_category(db, body.category_id)
        categorizer.learn(db, body.merchant, body.category_id)
        return body.category_id, body.category_source or "manual"
    s = categorizer.suggest(db, body.merchant, use_ai=use_ai)
    return s.category_id, s.source


@router.post("", status_code=201)
def create_expense(body: ExpenseIn, db: sqlite3.Connection = Depends(get_db)):
    category_id, category_source = resolve_category(db, body, use_ai=False)
    expense_id = insert_expense(
        db,
        amount_cents=to_cents(body.amount),
        merchant=body.merchant,
        date=(body.date or Date.today()).isoformat(),
        note=body.note,
        category_id=category_id,
        category_source=category_source,
        source="manual",
    )
    if body.repeat_monthly:
        recurring.create(db, expense_id=expense_id, merchant=body.merchant, amount_cents=to_cents(body.amount),
                         category_id=category_id, note=body.note, first=body.date or Date.today())
        recurring.add_due(db)   # a first date far in the past catches up to today
    db.commit()
    return fetch_expense(db, expense_id)


class QuickAddIn(BaseModel):
    amount: str | float = Field(description="Euros, e.g. 4.50 or \"4,50\"")
    merchant: str = Field(min_length=1, max_length=200)
    date: str | None = Field(None, description="YYYY-MM-DD or DD/MM/YYYY; defaults to today")
    note: str | None = Field(None, max_length=1000)
    category: str | None = Field(None, description="Optional category name")

    @field_validator("date")
    @classmethod
    def _date(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        v = v.strip()[:10]
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"):
            try:
                return datetime.strptime(v, fmt).date().isoformat()
            except ValueError:
                pass
        raise ValueError("date must be YYYY-MM-DD or DD/MM/YYYY")


def require_token(authorization: str | None = Header(None)) -> None:
    expected = config.quickadd_token()
    if expected is None:
        raise HTTPException(503, "Quick-add is disabled. Set QUICKADD_TOKEN in .env and restart.")
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not secrets.compare_digest(token.strip(), expected):
        raise HTTPException(401, "Missing or wrong token", headers={"WWW-Authenticate": "Bearer"})


@router.post("/quick", status_code=201, dependencies=[Depends(require_token)])
def quick_add(body: QuickAddIn, db: sqlite3.Connection = Depends(get_db)):
    """For iPhone Shortcuts: log an expense with a token instead of the web page."""
    category_id = None
    if body.category:
        row = db.execute("SELECT id FROM categories WHERE name = ? COLLATE NOCASE", (body.category.strip(),)).fetchone()
        if row is None:
            raise HTTPException(422, f"No category called '{body.category}'")
        category_id = row["id"]
    try:
        expense = ExpenseIn(amount=body.amount, merchant=body.merchant, date=body.date, note=body.note,
                            category_id=category_id, category_source="manual" if category_id else None)
    except ValidationError as exc:
        raise HTTPException(422, "; ".join(e["msg"].removeprefix("Value error, ") for e in exc.errors()))
    category_id, category_source = resolve_category(db, expense, use_ai=True)
    expense_id = insert_expense(
        db, amount_cents=to_cents(expense.amount), merchant=expense.merchant,
        date=(expense.date or Date.today()).isoformat(), note=expense.note,
        category_id=category_id, category_source=category_source, source="api",
    )
    db.commit()
    saved = fetch_expense(db, expense_id)
    euros = f"{abs(saved['amount_cents']) / 100:.2f}".replace(".", ",")
    saved["message"] = f"Saved {euros} € at {saved['merchant']} · {saved['category_name'] or 'Uncategorized'}"
    return saved


@router.put("/{expense_id}")
def update_expense(expense_id: int, body: ExpenseIn, db: sqlite3.Connection = Depends(get_db)):
    fetch_expense(db, expense_id)
    check_category(db, body.category_id)
    categorizer.learn(db, body.merchant, body.category_id)
    db.execute(
        """UPDATE expenses SET amount_cents = ?, merchant_raw = ?, merchant_norm = ?,
               category_id = ?, category_source = ?, date = ?, note = ?,
               updated_at = datetime('now')
           WHERE id = ?""",
        (to_cents(body.amount), body.merchant, normalize_merchant(body.merchant),
         body.category_id, (body.category_source or "manual") if body.category_id else "none",
         (body.date or Date.today()).isoformat(), body.note, expense_id),
    )
    db.commit()
    return fetch_expense(db, expense_id)


@router.delete("/{expense_id}", status_code=204)
def delete_expense(expense_id: int, db: sqlite3.Connection = Depends(get_db)):
    fetch_expense(db, expense_id)
    db.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
    db.commit()
    return Response(status_code=204)
