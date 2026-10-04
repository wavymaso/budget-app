"""Import Apple Pay emails from Gmail: on launch, then every few minutes.

Every email is recorded in `email_messages` by its Message-ID, so nothing is
imported twice, even if Gmail renumbers the label. Outcomes:

    imported   added as an expense
    review     in "Needs review" (blank merchant, 0 €, no transaction line,
               other currency, or looks like an expense you already have)
    accepted / dismissed   what you decided in "Needs review"
    refused    not sent from your own address (kept only as a record)
"""
import email.utils
import logging
import sqlite3
import threading
from datetime import datetime
from typing import Callable, Iterable

from . import categorizer, gmail, importer
from .db import connect, get_setting, set_setting
from .routers.expenses import insert_expense

log = logging.getLogger("budget.email")

CHECK_EVERY_SECONDS = 5 * 60
DEFAULTS = {"address": "", "label": "Budget", "enabled": False}

_lock = threading.Lock()


def get_config(conn: sqlite3.Connection) -> dict:
    return {**DEFAULTS, **(get_setting(conn, "email") or {})}


def save_config(conn: sqlite3.Connection, **changes) -> dict:
    cfg = {**get_config(conn), **changes}
    set_setting(conn, "email", cfg)
    conn.commit()
    return cfg


# A fetcher returns (uidvalidity, [(uid, raw_email_bytes), ...]) for UIDs above `after_uid`.
Fetcher = Callable[[dict, str, int], tuple[int | None, Iterable[tuple[int, bytes]]]]


def gmail_fetcher(cfg: dict, password: str, after_uid: int):
    with gmail.GmailClient(cfg["address"], password, cfg["label"]) as client:
        uids = client.search_budget_uids(after_uid)
        return client.uidvalidity, client.fetch(uids)


def sync(conn: sqlite3.Connection | None = None, *, fetcher: Fetcher = gmail_fetcher,
         password: str | None = None, use_ai: bool = True) -> dict:
    """Check Gmail once. Returns a summary that is also saved as the 'last sync'."""
    if not _lock.acquire(blocking=False):
        return {"error": "A check is already running.", "imported": 0, "review": 0}
    own = conn is None
    conn = conn or connect()
    result = {"started_at": datetime.now().isoformat(timespec="seconds"),
              "imported": 0, "review": 0, "refused": 0, "skipped": 0, "error": None}
    try:
        result["error"] = _check(conn, result, fetcher, password, use_ai)
    finally:
        result["finished_at"] = datetime.now().isoformat(timespec="seconds")
        result["run"] = (get_setting(conn, "email_last_sync") or {}).get("run", 0) + 1
        set_setting(conn, "email_last_sync", result)
        conn.commit()
        if own:
            conn.close()
        _lock.release()
    if result["error"]:
        log.warning("Gmail check failed: %s", result["error"])
    elif result["imported"] or result["review"]:
        log.info("Gmail: %s imported, %s need review", result["imported"], result["review"])
    return result


def _check(conn, result, fetcher, password, use_ai) -> str | None:
    """Do one check, filling in the counts in `result`. Returns an error message or None."""
    cfg = get_config(conn)
    if not cfg["address"]:
        return "Gmail isn't set up yet."
    password = password or gmail.get_password(cfg["address"])
    if not password:
        return "No app password saved for this address."

    state = get_setting(conn, "email_state") or {}
    same_mailbox = state.get("address") == cfg["address"].lower() and state.get("label") == cfg["label"]
    after = state.get("last_uid", 0) if same_mailbox else 0
    try:
        uidvalidity, messages = fetcher(cfg, password, after)
        if after and uidvalidity != state.get("uidvalidity"):
            # Gmail renumbered the label: look at everything again (Message-IDs prevent repeats).
            after = 0
            uidvalidity, messages = fetcher(cfg, password, 0)
    except gmail.GmailError as exc:
        return str(exc)
    except Exception as exc:  # noqa: BLE001
        return gmail.explain(exc)

    last_uid = after
    for uid, raw in messages:
        last_uid = max(last_uid, uid)
        outcome = process_email(conn, raw, cfg["address"], uid=uid, use_ai=use_ai)
        result[outcome] += 1
        conn.commit()
    set_setting(conn, "email_state", {"address": cfg["address"].lower(), "label": cfg["label"],
                                      "uidvalidity": uidvalidity, "last_uid": last_uid})
    return None


def process_email(conn: sqlite3.Connection, raw: bytes, my_address: str, *, uid: int | None = None,
                  use_ai: bool = True) -> str:
    """Handle one email. Returns imported | review | refused | skipped."""
    msg = gmail.parse_message(raw)
    mid = gmail.message_id(msg, raw)
    if conn.execute("SELECT 1 FROM email_messages WHERE message_id = ?", (mid,)).fetchone():
        return "skipped"                              # already handled on an earlier check
    if not gmail.subject_ok(msg):
        return "skipped"                              # e.g. subject "Re: BUDGET"

    received = None
    if msg.get("Date"):
        try:
            received = email.utils.parsedate_to_datetime(str(msg["Date"])).isoformat()
        except (TypeError, ValueError):
            pass
    record = {"message_id": mid, "uid": uid, "sender": str(msg.get("From", ""))[:200],
              "received_at": received}

    problem = gmail.sender_problem(msg, my_address)
    if problem:
        _record(conn, **record, status="refused", reason=problem)
        log.warning("Refused email %s: %s", mid, problem)
        return "refused"

    tx = gmail.find_transaction(gmail.message_text(msg))
    if tx is None:
        excerpt = " ".join(gmail.message_text(msg).split())[:200]
        _record(conn, **record, status="review", reason="no transaction line found", line=excerpt)
        return "review"

    fields = {"line": tx.line, "date": tx.date.isoformat() if tx.date else None,
              "merchant": tx.merchant or None, "amount_cents": tx.amount_cents, "currency": tx.currency}
    category_id, category_source = None, "none"
    if tx.merchant:
        s = categorizer.suggest(conn, tx.merchant, use_ai=use_ai)
        category_id, category_source = s.category_id, s.source
    fields.update(category_id=category_id, category_source=category_source)

    if tx.problem:
        _record(conn, **record, **fields, status="review", reason=tx.problem)
        return "review"

    # Compare with expenses from bank CSVs or typed by hand (not other emails:
    # two identical coffees on the same day are both real).
    dup = importer.find_duplicate(conn, fields["date"], tx.amount_cents, tx.merchant,
                                  f"email:{mid}", exclude_sources=("email",))
    if dup:
        _record(conn, **record, **fields, status="review", duplicate_of=dup["id"],
                reason=f"looks like an expense you already have ({dup['merchant']}, {dup['reason']})")
        return "review"

    expense_id = insert_expense(
        conn, amount_cents=tx.amount_cents, merchant=tx.merchant, date=fields["date"], note=None,
        category_id=category_id, category_source=category_source, source="email",
        import_hash=f"email:{mid}",
    )
    _record(conn, **record, **fields, status="imported", expense_id=expense_id)
    return "imported"


def _record(conn: sqlite3.Connection, **row) -> None:
    cols = ", ".join(row)
    conn.execute(f"INSERT INTO email_messages ({cols}) VALUES ({', '.join('?' * len(row))})", list(row.values()))


# --- Background checks --------------------------------------------------------


class Poller:
    """Checks Gmail right away, then every CHECK_EVERY_SECONDS until stopped."""

    def __init__(self, interval: float = CHECK_EVERY_SECONDS):
        self.interval = interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="gmail-poller", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                conn = connect()
                try:
                    if get_config(conn)["enabled"]:
                        sync(conn)
                finally:
                    conn.close()
            except Exception:  # never let one bad check stop future ones
                log.exception("Gmail check crashed")
            self._stop.wait(self.interval)

