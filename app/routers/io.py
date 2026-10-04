"""CSV import, CSV export and database backups."""
import csv
import io
import sqlite3
from collections import Counter
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .. import categorizer, config, importer
from ..db import connect, get_db, get_setting, set_setting
from ..models import CATEGORY_SOURCES
from .expenses import insert_expense

router = APIRouter(prefix="/api", tags=["import/export"])

MAX_CSV_CHARS = 5_000_000
AI_LOOKUPS_PER_IMPORT = 40


class ParseIn(BaseModel):
    text: str = Field(max_length=MAX_CSV_CHARS)


class Mapping(BaseModel):
    date: int
    description: int
    amount: int
    date_format: str = "DD/MM/YYYY"
    sign: str = Field("negative", pattern="^(negative|positive)$")


class PreviewIn(BaseModel):
    text: str = Field(max_length=MAX_CSV_CHARS)
    mapping: Mapping
    use_ai: bool = True


class ImportRow(BaseModel):
    date: str
    merchant: str = Field(min_length=1, max_length=200)
    amount_cents: int
    category_id: int | None = None
    category_source: str = "none"
    import_hash: str | None = None


class CommitIn(BaseModel):
    rows: list[ImportRow]


@router.post("/import/parse")
def parse(body: ParseIn, db: sqlite3.Connection = Depends(get_db)):
    headers, rows, delimiter = importer.read_csv(body.text)
    if not headers or not rows:
        raise HTTPException(422, "Couldn't find any rows in that file")
    saved = get_setting(db, "csv_mapping")
    # Reuse the mapping you confirmed last time if this file has the same columns.
    if saved and saved.get("headers") == headers:
        mapping, remembered = saved["mapping"], True
    else:
        mapping, remembered = importer.guess_mapping(headers), False
        if mapping.get("date") is not None:
            mapping["date_format"] = importer.guess_date_format([r[mapping["date"]] for r in rows])
        if mapping.get("amount") is not None:
            amounts = []
            for r in rows[:100]:
                try:
                    amounts.append(importer.to_cents(r[mapping["amount"]]))
                except ValueError:
                    pass
            mapping["sign"] = importer.guess_sign(amounts) if amounts else "negative"
    return {
        "headers": headers,
        "delimiter": delimiter,
        "row_count": len(rows),
        "sample": rows[:6],
        "mapping": mapping,
        "remembered": remembered,
        "date_formats": list(importer.DATE_FORMATS),
    }


@router.post("/import/preview")
def preview(body: PreviewIn, db: sqlite3.Connection = Depends(get_db)):
    headers, rows, _ = importer.read_csv(body.text)
    m = body.mapping
    if max(m.date, m.description, m.amount) >= len(headers):
        raise HTTPException(422, "Column mapping doesn't match this file")
    set_setting(db, "csv_mapping", {"headers": headers, "mapping": m.model_dump()})
    db.commit()

    seen = Counter()
    ai_budget = AI_LOOKUPS_PER_IMPORT if body.use_ai else 0
    out = []
    for i, r in enumerate(rows):
        raw_date, merchant, raw_amount = r[m.date].strip(), " ".join(r[m.description].split()), r[m.amount]
        item = {"row": i + 1, "raw": {"date": raw_date, "description": merchant, "amount": raw_amount.strip()}}
        d = importer.parse_date(raw_date, m.date_format)
        try:
            cents = importer.to_signed_cents(raw_amount, m.sign)
        except ValueError:
            cents = None
        if d is None or cents is None or not merchant or cents == 0:
            item["error"] = ("unreadable date" if d is None else "unreadable amount" if cents is None
                             else "empty description" if not merchant else "zero amount")
            out.append(item)
            continue
        key = (d.isoformat(), cents, merchant.lower())
        seen[key] += 1
        h = importer.row_hash(d.isoformat(), cents, merchant, seen[key])

        s = categorizer.suggest(db, merchant, use_ai=False)
        if s.category_id is None and ai_budget > 0 and config.anthropic_api_key():
            ai_budget -= 1
            s = categorizer.suggest(db, merchant, use_ai=True)
        item.update({
            "date": d.isoformat(), "merchant": merchant, "amount_cents": cents,
            "category_id": s.category_id, "category_source": s.source, "import_hash": h,
            "duplicate": importer.find_duplicate(db, d.isoformat(), cents, merchant, h),
        })
        out.append(item)
    return {"rows": out}


@router.post("/import/commit")
def commit(body: CommitIn, db: sqlite3.Connection = Depends(get_db)):
    valid_ids = {r[0] for r in db.execute("SELECT id FROM categories")}
    added = 0
    for r in body.rows:
        try:
            day = datetime.strptime(r.date, "%Y-%m-%d").date().isoformat()
        except ValueError:
            raise HTTPException(422, f"Bad date {r.date!r}")
        category_id = r.category_id if r.category_id in valid_ids else None
        source = r.category_source if r.category_source in CATEGORY_SOURCES else "none"
        if source == "manual" and category_id is not None:
            categorizer.learn(db, r.merchant, category_id)   # you corrected it in the preview
        insert_expense(db, amount_cents=r.amount_cents, merchant=r.merchant.strip(), date=day, note=None,
                       category_id=category_id, category_source=source if category_id else "none",
                       source="csv", import_hash=r.import_hash)
        added += 1
    db.commit()
    return {"added": added}


@router.get("/export.csv")
def export_csv(db: sqlite3.Connection = Depends(get_db)):
    rows = db.execute(
        """SELECT e.id, e.date, e.merchant_raw, e.amount_cents, c.name AS category, e.note, e.source
           FROM expenses e LEFT JOIN categories c ON c.id = e.category_id ORDER BY e.date, e.id"""
    ).fetchall()
    buf = io.StringIO()
    buf.write("﻿")  # BOM so Excel opens accents correctly
    # Semicolons + comma decimals: opens cleanly in Spanish-locale Excel and Numbers.
    w = csv.writer(buf, delimiter=";")
    w.writerow(["ID", "Date", "Merchant", "Amount (EUR)", "Category", "Note", "Source"])
    for r in rows:
        y, m, d = r["date"].split("-")
        w.writerow([r["id"], f"{d}/{m}/{y}", r["merchant_raw"], f"{r['amount_cents'] / 100:.2f}".replace(".", ","),
                    r["category"] or "Uncategorized", r["note"] or "", r["source"]])
    filename = f"budget-export-{datetime.now():%Y-%m-%d}.csv"
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.post("/backup")
def backup():
    config.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    target = config.BACKUP_DIR / f"budget-{datetime.now():%Y-%m-%d_%H-%M-%S}.db"
    src = connect()
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)   # consistent copy even while the app is running
    finally:
        dst.close()
        src.close()
    return {"file": str(target.relative_to(config.BASE_DIR)), "size_bytes": target.stat().st_size}


@router.get("/backups")
def list_backups():
    if not config.BACKUP_DIR.exists():
        return []
    files = sorted(config.BACKUP_DIR.glob("budget-*.db"), reverse=True)
    return [{"file": str(f.relative_to(config.BASE_DIR)), "size_bytes": f.stat().st_size,
             "created": datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec="seconds")} for f in files]
