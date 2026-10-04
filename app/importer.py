"""Reading bank-statement CSVs: delimiter/encoding detection, dates, amounts, duplicates."""
import csv
import hashlib
import io
import sqlite3
from datetime import date, datetime, timedelta

from rapidfuzz import fuzz

from .models import to_cents
from .normalize import normalize_merchant

DATE_FORMATS = {
    "DD/MM/YYYY": ["%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%d-%m-%y", "%d.%m.%Y", "%d.%m.%y"],
    "YYYY-MM-DD": ["%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"],
    "MM/DD/YYYY": ["%m/%d/%Y", "%m/%d/%y"],
}

HEADER_HINTS = {
    "date": ["fecha operacion", "fecha", "date", "f. valor", "fecha valor", "transaction date", "booking date"],
    "description": ["concepto", "descripcion", "description", "comercio", "merchant", "detalle", "payee", "movimiento", "name"],
    "amount": ["importe", "amount", "cantidad", "cargo", "value", "eur"],
}


def decode(raw: bytes | str) -> str:
    if isinstance(raw, str):
        return raw.lstrip("﻿")
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def read_csv(text: str) -> tuple[list[str], list[list[str]], str]:
    text = text.lstrip("﻿")
    sample = text[:5000]
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters=";,\t|").delimiter
    except csv.Error:
        delimiter = ";" if sample.count(";") > sample.count(",") else ","
    rows = [r for r in csv.reader(io.StringIO(text), delimiter=delimiter) if any(c.strip() for c in r)]
    if not rows:
        return [], [], delimiter
    # Some banks put a few title lines above the real header; use the first
    # row that has as many columns as most of the file.
    widths = [len(r) for r in rows]
    common = max(set(widths), key=widths.count)
    start = next(i for i, r in enumerate(rows) if len(r) == common)
    headers = [h.strip() or f"Column {i + 1}" for i, h in enumerate(rows[start])]
    body = [r + [""] * (len(headers) - len(r)) for r in rows[start + 1:]]
    return headers, body, delimiter


def guess_mapping(headers: list[str]) -> dict[str, int | None]:
    lowered = [normalize_merchant(h) or h.lower() for h in headers]
    mapping = {}
    for field, hints in HEADER_HINTS.items():
        mapping[field] = next(
            (i for hint in hints for i, h in enumerate(lowered) if hint == h or h.startswith(hint)), None
        )
    return mapping


def parse_date(value: str, fmt: str) -> date | None:
    value = value.strip()
    for pattern in DATE_FORMATS.get(fmt, []):
        try:
            return datetime.strptime(value, pattern).date()
        except ValueError:
            continue
    return None


def guess_date_format(values: list[str]) -> str:
    values = [v for v in values if v.strip()][:50]
    for fmt in DATE_FORMATS:          # day-first is tried before month-first
        if values and all(parse_date(v, fmt) for v in values):
            return fmt
    return "DD/MM/YYYY"


def guess_sign(amounts: list[int]) -> str:
    """Card statements usually show spending as negative numbers."""
    negatives = sum(1 for a in amounts if a < 0)
    return "negative" if negatives >= len(amounts) / 2 else "positive"


def row_hash(day: str, amount_cents: int, description: str, occurrence: int) -> str:
    key = f"{day}|{amount_cents}|{description.strip().lower()}|{occurrence}"
    return hashlib.sha1(key.encode()).hexdigest()


def find_duplicate(conn: sqlite3.Connection, day: str, amount_cents: int, merchant: str,
                   import_hash: str) -> dict | None:
    """An exact earlier import, or an expense with the same amount, a similar merchant, within a day."""
    row = conn.execute("SELECT id, merchant_raw, date FROM expenses WHERE import_hash = ?", (import_hash,)).fetchone()
    if row:
        return {"id": row["id"], "reason": "already imported", "merchant": row["merchant_raw"], "date": row["date"]}
    d = date.fromisoformat(day)
    norm = normalize_merchant(merchant)
    candidates = conn.execute(
        "SELECT id, merchant_raw, merchant_norm, date FROM expenses "
        "WHERE amount_cents = ? AND date BETWEEN ? AND ?",
        (amount_cents, (d - timedelta(days=1)).isoformat(), (d + timedelta(days=1)).isoformat()),
    ).fetchall()
    for c in candidates:
        if (c["merchant_norm"] == norm or norm in c["merchant_norm"] or c["merchant_norm"] in norm
                or fuzz.token_set_ratio(norm, c["merchant_norm"]) >= 80):
            return {"id": c["id"], "reason": "same amount and merchant", "merchant": c["merchant_raw"], "date": c["date"]}
    return None


def to_signed_cents(value: str, sign: str) -> int:
    """Expense amounts are stored positive; money coming back is negative (a refund)."""
    cents = to_cents(value)
    return -cents if sign == "negative" else cents
