"""Keeping the iPhone app and the Mac in step.

The iPhone app keeps its own full copy of your data and works without the Mac.
When it can reach the Mac, it sends what changed on the phone and asks for what
changed here since last time.

How changes are tracked (database triggers, so every way Budget saves data is
covered: the window, CSV imports, Gmail, monthly bills):

- every synced row has a permanent `uid` (the same on both devices), a `rev`
  (a counter that goes up with every change on the Mac) and `modified_at`
  (when it was last edited, on whichever device);
- deleting a row leaves a note in `sync_deleted`, so the phone deletes it too.

The phone asks for "everything after rev N". When both sides changed the same
row, the newer edit wins. Bill occurrences get the same uid on both devices
("rec:<bill>:<date>"), so a bill added by both is only added once. The same goes
for expenses from Apple Pay emails, which both devices read on their own (uid made
from the email's Message-ID, see email_sync.expense_uid).
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from . import categorizer
from .db import get_setting
from .normalize import normalize_merchant

NOW = "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"

# Tables with their own permanent uid.
UID_TABLES = ["categories", "expenses", "budgets", "recurring", "savings_moves"]
# Tables whose rows are identified by a natural key instead.
KEYED_TABLES = {"merchant_rules": "merchant_norm", "keyword_rules": "keyword",
                "savings_months": "month", "settings": "key"}
# Settings the phone may see and change. Everything else (phone password, Gmail) stays here.
SYNCED_SETTINGS = {"preferences", "savings"}
# What the phone may send. The rest is worked out by the Mac and only sent down.
PUSHABLE = {"categories", "expenses", "budgets", "recurring", "savings_moves", "merchant_rules", "settings"}


def _key_col(table: str) -> str:
    return "uid" if table in UID_TABLES else KEYED_TABLES[table]


def install(conn: sqlite3.Connection) -> None:
    """Add the sync columns and triggers (safe to run on every start)."""
    conn.execute("CREATE TABLE IF NOT EXISTS sync_state (k TEXT PRIMARY KEY, v INTEGER NOT NULL)")
    conn.execute("INSERT OR IGNORE INTO sync_state (k, v) VALUES ('rev', 0)")
    conn.execute("""CREATE TABLE IF NOT EXISTS sync_deleted (
        tbl TEXT NOT NULL, key TEXT NOT NULL, rev INTEGER NOT NULL, deleted_at TEXT NOT NULL,
        PRIMARY KEY (tbl, key))""")
    for table in UID_TABLES + list(KEYED_TABLES):
        cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        uid = table in UID_TABLES
        if uid and "uid" not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN uid TEXT")
            conn.execute(f"UPDATE {table} SET uid = lower(hex(randomblob(16))) WHERE uid IS NULL")
        if "rev" not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN rev INTEGER NOT NULL DEFAULT 0")
        if "modified_at" not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN modified_at TEXT")
            conn.execute(f"UPDATE {table} SET modified_at = {NOW} WHERE modified_at IS NULL")
        if uid:
            conn.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS ux_{table}_uid ON {table}(uid)")
        conn.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_rev ON {table}(rev)")
        key = _key_col(table)
        bump = "UPDATE sync_state SET v = v + 1 WHERE k = 'rev';"
        rev = "(SELECT v FROM sync_state WHERE k = 'rev')"
        conn.executescript(f"""
            CREATE TRIGGER IF NOT EXISTS sync_ins_{table} AFTER INSERT ON {table} BEGIN
                {bump}
                UPDATE {table} SET rev = {rev},
                    {"uid = COALESCE(NEW.uid, lower(hex(randomblob(16)))), " if uid else ""}
                    modified_at = COALESCE(NEW.modified_at, {NOW})
                WHERE rowid = NEW.rowid;
                DELETE FROM sync_deleted WHERE tbl = '{table}' AND key = NEW.{key};
            END;
            CREATE TRIGGER IF NOT EXISTS sync_upd_{table} AFTER UPDATE ON {table} WHEN NEW.rev IS OLD.rev BEGIN
                {bump}
                UPDATE {table} SET rev = {rev},
                    modified_at = CASE WHEN NEW.modified_at IS OLD.modified_at THEN {NOW} ELSE NEW.modified_at END
                WHERE rowid = NEW.rowid;
            END;
            CREATE TRIGGER IF NOT EXISTS sync_del_{table} AFTER DELETE ON {table} BEGIN
                {bump}
                INSERT OR REPLACE INTO sync_deleted (tbl, key, rev, deleted_at)
                    VALUES ('{table}', OLD.{key}, {rev}, {NOW});
            END;
        """)


def current_rev(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT v FROM sync_state WHERE k = 'rev'").fetchone()[0]


# --- rows on the wire -------------------------------------------------------------
# Rows travel with uids instead of the Mac's numeric ids: category_uid, recurring_uid.

def _uid_of(conn, table: str, row_id) -> str | None:
    if row_id is None:
        return None
    r = conn.execute(f"SELECT uid FROM {table} WHERE id = ?", (row_id,)).fetchone()
    return r["uid"] if r else None


def _id_of(conn, table: str, uid) -> int | None:
    if not uid:
        return None
    r = conn.execute(f"SELECT id FROM {table} WHERE uid = ?", (uid,)).fetchone()
    return r["id"] if r else None


def _out(conn, table: str, r: sqlite3.Row) -> dict:
    base = {"modified_at": r["modified_at"]}
    if table == "categories":
        return {**base, "uid": r["uid"], "name": r["name"], "color": r["color"], "sort_order": r["sort_order"]}
    if table == "expenses":
        return {**base, "uid": r["uid"], "amount_cents": r["amount_cents"], "merchant": r["merchant_raw"],
                "merchant_norm": r["merchant_norm"], "date": r["date"], "note": r["note"], "source": r["source"],
                "category_uid": _uid_of(conn, "categories", r["category_id"]), "category_source": r["category_source"],
                "recurring_uid": _uid_of(conn, "recurring", r["recurring_id"]), "created_at": r["created_at"]}
    if table == "budgets":
        return {**base, "uid": r["uid"], "category_uid": _uid_of(conn, "categories", r["category_id"]),
                "period": r["period"], "limit_cents": r["limit_cents"]}
    if table == "recurring":
        return {**base, "uid": r["uid"], "merchant": r["merchant"], "amount_cents": r["amount_cents"],
                "category_uid": _uid_of(conn, "categories", r["category_id"]), "note": r["note"],
                "day": r["day"], "next_date": r["next_date"]}
    if table == "savings_moves":
        return {**base, "uid": r["uid"], "date": r["date"], "amount_cents": r["amount_cents"], "note": r["note"]}
    if table == "merchant_rules":
        return {**base, "merchant_norm": r["merchant_norm"], "category_uid": _uid_of(conn, "categories", r["category_id"]),
                "hit_count": r["hit_count"]}
    if table == "keyword_rules":
        return {**base, "keyword": r["keyword"], "category_uid": _uid_of(conn, "categories", r["category_id"])}
    if table == "savings_months":
        return {**base, "month": r["month"], "limit_cents": r["limit_cents"], "spent_cents": r["spent_cents"],
                "saved_cents": r["saved_cents"]}
    if table == "settings":
        return {**base, "key": r["key"], "value": json.loads(r["value"])}
    raise ValueError(table)


def changes_since(conn: sqlite3.Connection, since: int) -> dict:
    """Everything that changed on the Mac after `since` (0 = everything)."""
    out: dict[str, Any] = {"rev": current_rev(conn), "tables": {}, "deleted": [], "gmail": _gmail_hint(conn)}
    for table in UID_TABLES + list(KEYED_TABLES):
        sql = f"SELECT * FROM {table} WHERE rev > ?"   # rows from before sync existed have rev 0
        if table == "settings":
            sql += f" AND key IN ({','.join('?' * len(SYNCED_SETTINGS))})"
        rows = conn.execute(sql + " ORDER BY rev", (since if since else -1,
                                                    *(sorted(SYNCED_SETTINGS) if table == "settings" else ()))).fetchall()
        out["tables"][table] = [_out(conn, table, r) for r in rows]
    if since:
        out["deleted"] = [{"table": r["tbl"], "key": r["key"], "deleted_at": r["deleted_at"]}
                          for r in conn.execute("SELECT * FROM sync_deleted WHERE rev > ? ORDER BY rev", (since,))
                          if r["tbl"] != "settings" or r["key"] in SYNCED_SETTINGS]
    return out


def _gmail_hint(conn: sqlite3.Connection) -> dict | None:
    """Which Gmail address and label the Mac reads, so the phone only needs the app password."""
    cfg = get_setting(conn, "email") or {}
    if not cfg.get("address"):
        return None
    return {"address": cfg["address"], "label": cfg.get("label") or "Budget"}


# --- applying what the phone sends --------------------------------------------------

def _newer(incoming: str | None, existing: str | None) -> bool:
    return bool(incoming) and (existing is None or incoming > existing)


def apply(conn: sqlite3.Connection, changes: dict[str, list[dict]], deleted: list[dict]) -> dict:
    """Apply the phone's changes; the newer edit wins. Returns uids the phone should
    replace with the Mac's (a category or budget that already existed here), and
    expenses it should drop (from an email whose expense was deleted here)."""
    remap: dict[str, str] = {}
    dropped: list[str] = []
    cat_id = lambda uid: _id_of(conn, "categories", remap.get(uid, uid))   # noqa: E731

    for c in changes.get("categories", []):
        row = conn.execute("SELECT * FROM categories WHERE uid = ?", (c["uid"],)).fetchone()
        if row is None:
            same = conn.execute("SELECT * FROM categories WHERE name = ? COLLATE NOCASE", (c["name"],)).fetchone()
            if same:   # made on both devices: keep the Mac's
                remap[c["uid"]] = same["uid"]
                continue
            conn.execute("INSERT INTO categories (uid, name, color, sort_order, modified_at) VALUES (?, ?, ?, ?, ?)",
                         (c["uid"], c["name"], c.get("color") or "#64748b", c.get("sort_order", 0), c["modified_at"]))
        elif _newer(c["modified_at"], row["modified_at"]):
            clash = conn.execute("SELECT 1 FROM categories WHERE name = ? COLLATE NOCASE AND uid != ?", (c["name"], c["uid"])).fetchone()
            conn.execute("UPDATE categories SET name = ?, color = ?, sort_order = ?, modified_at = ? WHERE uid = ?",
                         (row["name"] if clash else c["name"], c.get("color") or row["color"], c.get("sort_order", row["sort_order"]),
                          c["modified_at"], c["uid"]))

    for b in changes.get("recurring", []):
        row = conn.execute("SELECT * FROM recurring WHERE uid = ?", (b["uid"],)).fetchone()
        vals = (b["merchant"], b["amount_cents"], cat_id(b.get("category_uid")), b.get("note"), b["day"], b["next_date"], b["modified_at"])
        if row is None:
            conn.execute("INSERT INTO recurring (merchant, amount_cents, category_id, note, day, next_date, modified_at, uid) "
                         "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (*vals, b["uid"]))
        elif _newer(b["modified_at"], row["modified_at"]):
            # next_date only moves forward: a bill added on either device stays added.
            nd = max(b["next_date"], row["next_date"])
            conn.execute("UPDATE recurring SET merchant = ?, amount_cents = ?, category_id = ?, note = ?, day = ?, next_date = ?, "
                         "modified_at = ? WHERE uid = ?", (*vals[:5], nd, b["modified_at"], b["uid"]))

    for e in changes.get("expenses", []):
        row = conn.execute("SELECT * FROM expenses WHERE uid = ?", (e["uid"],)).fetchone()
        cid = cat_id(e.get("category_uid"))
        source = e.get("category_source") or ("manual" if cid else "none")
        vals = (e["amount_cents"], e["merchant"], normalize_merchant(e["merchant"]), cid, e["date"], e.get("note"),
                source, _id_of(conn, "recurring", e.get("recurring_uid")), e["modified_at"])
        if row is None and e.get("source") == "email" and conn.execute(
                "SELECT 1 FROM sync_deleted WHERE tbl = 'expenses' AND key = ?", (e["uid"],)).fetchone():
            dropped.append(e["uid"])   # the Mac imported this email too, and you deleted it
            continue
        if row is None:
            cur = conn.execute(
                "INSERT INTO expenses (amount_cents, merchant_raw, merchant_norm, category_id, date, note, category_source, "
                "recurring_id, modified_at, uid, source) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (*vals, e["uid"], e.get("source") or "phone"))
            if cid is None:   # the Mac's categorizer has more to go on: let it try
                s = categorizer.suggest(conn, e["merchant"], use_ai=False)
                if s.category_id is not None:
                    conn.execute("UPDATE expenses SET category_id = ?, category_source = ? WHERE id = ?",
                                 (s.category_id, s.source, cur.lastrowid))
            if e.get("source") == "email":
                _settle_review(conn, e["uid"], cur.lastrowid)
        elif _newer(e["modified_at"], row["modified_at"]):
            conn.execute("UPDATE expenses SET amount_cents = ?, merchant_raw = ?, merchant_norm = ?, category_id = ?, date = ?, "
                         "note = ?, category_source = ?, recurring_id = ?, modified_at = ?, updated_at = datetime('now') WHERE uid = ?",
                         (*vals, e["uid"]))

    for b in changes.get("budgets", []):
        cid = cat_id(b.get("category_uid"))
        row = conn.execute("SELECT * FROM budgets WHERE uid = ?", (b["uid"],)).fetchone()
        if row is None:
            same = conn.execute("SELECT * FROM budgets WHERE COALESCE(category_id, 0) = COALESCE(?, 0) AND period = ?",
                                (cid, b["period"])).fetchone()
            if same:
                remap[b["uid"]] = same["uid"]
                row = same
            else:
                conn.execute("INSERT INTO budgets (category_id, period, limit_cents, modified_at, uid) VALUES (?, ?, ?, ?, ?)",
                             (cid, b["period"], b["limit_cents"], b["modified_at"], b["uid"]))
                continue
        if _newer(b["modified_at"], row["modified_at"]):
            conn.execute("UPDATE budgets SET limit_cents = ?, modified_at = ? WHERE uid = ?",
                         (b["limit_cents"], b["modified_at"], row["uid"]))

    for m in changes.get("savings_moves", []):
        row = conn.execute("SELECT * FROM savings_moves WHERE uid = ?", (m["uid"],)).fetchone()
        if row is None:
            conn.execute("INSERT INTO savings_moves (date, amount_cents, note, modified_at, uid) VALUES (?, ?, ?, ?, ?)",
                         (m["date"], m["amount_cents"], m.get("note"), m["modified_at"], m["uid"]))
        elif _newer(m["modified_at"], row["modified_at"]):
            conn.execute("UPDATE savings_moves SET date = ?, amount_cents = ?, note = ?, modified_at = ? WHERE uid = ?",
                         (m["date"], m["amount_cents"], m.get("note"), m["modified_at"], m["uid"]))

    for r in changes.get("merchant_rules", []):
        cid = cat_id(r.get("category_uid"))
        norm = r.get("merchant_norm") or normalize_merchant(r.get("merchant", ""))
        if not norm or cid is None:
            continue
        row = conn.execute("SELECT * FROM merchant_rules WHERE merchant_norm = ?", (norm,)).fetchone()
        if row is None:
            conn.execute("INSERT INTO merchant_rules (merchant_norm, category_id, hit_count, modified_at) VALUES (?, ?, ?, ?)",
                         (norm, cid, r.get("hit_count", 1), r["modified_at"]))
        elif _newer(r["modified_at"], row["modified_at"]):
            conn.execute("UPDATE merchant_rules SET category_id = ?, hit_count = MAX(hit_count, ?), modified_at = ?, "
                         "updated_at = datetime('now') WHERE merchant_norm = ?", (cid, r.get("hit_count", 1), r["modified_at"], norm))

    for s in changes.get("settings", []):
        if s.get("key") not in SYNCED_SETTINGS:
            continue
        row = conn.execute("SELECT * FROM settings WHERE key = ?", (s["key"],)).fetchone()
        if row is None:
            conn.execute("INSERT INTO settings (key, value, modified_at) VALUES (?, ?, ?)",
                         (s["key"], json.dumps(s["value"]), s["modified_at"]))
        elif _newer(s["modified_at"], row["modified_at"]):
            conn.execute("UPDATE settings SET value = ?, modified_at = ? WHERE key = ?",
                         (json.dumps(s["value"]), s["modified_at"], s["key"]))

    for d in deleted:
        table, key = d.get("table"), d.get("key")
        if table not in PUSHABLE or not key or (table == "settings" and key not in SYNCED_SETTINGS):
            continue
        col = _key_col(table)
        row = conn.execute(f"SELECT modified_at FROM {table} WHERE {col} = ?", (key,)).fetchone()
        # Deleted on the phone, but edited here afterwards: the edit wins.
        if row and not (row["modified_at"] and d.get("deleted_at") and row["modified_at"] > d["deleted_at"]):
            conn.execute(f"DELETE FROM {table} WHERE {col} = ?", (key,))

    conn.commit()
    return {"remap": remap, "dropped": dropped}


def _settle_review(conn: sqlite3.Connection, uid: str, expense_id: int) -> None:
    """The phone imported an email the Mac had put in "Needs review": it's handled now."""
    from .email_sync import expense_uid
    for r in conn.execute("SELECT id, message_id FROM email_messages WHERE status = 'review'").fetchall():
        if expense_uid(r["message_id"]) == uid:
            conn.execute("UPDATE email_messages SET status = 'imported', expense_id = ?, "
                         "reason = 'added on your iPhone' WHERE id = ?", (expense_id, r["id"]))
