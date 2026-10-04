"""Reading Apple Pay transactions that an iPhone Shortcut emails to your Gmail.

Each email has the subject BUDGET and a body line like

    2026-10-04T13:22:05+02:00;MERCADONA;12,45 €;EUR

Gmail is opened read-only over IMAP: nothing is ever marked, moved or deleted.
The app password is kept in the macOS Keychain, never in a file or the database.
"""
import email
import email.policy
import email.utils
import html
import imaplib
import re
import socket
import ssl
from dataclasses import dataclass
from datetime import date as Date
from datetime import datetime
from email.message import EmailMessage

from .models import to_cents

IMAP_HOST = "imap.gmail.com"
KEYCHAIN_SERVICE = "Budget – Gmail app password"
SUBJECT = "BUDGET"

# --- Keychain ---------------------------------------------------------------


def _keyring():
    import keyring
    import keyring.backends.macOS
    # Pick the Keychain explicitly: backend auto-discovery doesn't work inside the .app.
    keyring.set_keyring(keyring.backends.macOS.Keyring())
    return keyring


def get_password(address: str) -> str | None:
    if not address:
        return None
    try:
        return _keyring().get_password(KEYCHAIN_SERVICE, address.lower())
    except Exception:
        return None


def set_password(address: str, password: str) -> None:
    _keyring().set_password(KEYCHAIN_SERVICE, address.lower(), password)


def delete_password(address: str) -> None:
    try:
        _keyring().delete_password(KEYCHAIN_SERVICE, address.lower())
    except Exception:
        pass


def clean_app_password(password: str) -> str:
    """Google shows app passwords as 'abcd efgh ijkl mnop'; the spaces aren't part of it."""
    return re.sub(r"\s+", "", password or "")


# --- Parsing ------------------------------------------------------------------

LINE_RE = re.compile(
    r"""^\s*
    (?P<when>\d{4}-\d{2}-\d{2}(?:[T\s]\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?)?(?:Z|[+-]\d{2}:?\d{2})?)
    \s*;\s*(?P<merchant>[^;]*?)
    \s*;\s*(?P<amount>[^;]*?)
    \s*(?:;\s*(?P<currency>[A-Za-z]{3})?\s*)?$""",
    re.VERBOSE,
)


@dataclass
class Transaction:
    line: str
    date: Date | None
    merchant: str
    amount_cents: int | None
    currency: str
    problem: str | None = None      # why it needs review, if it does


def find_transaction(text: str) -> Transaction | None:
    """The first line in the email that looks like date;merchant;amount;currency."""
    for raw in (text or "").splitlines():
        m = LINE_RE.match(raw.replace(" ", " "))
        if m:
            return _build(raw.strip(), m)
    return None


def _build(line: str, m: re.Match) -> Transaction:
    when = m["when"]
    try:
        # The phone's local date (the offset in the timestamp is already local time).
        day = datetime.fromisoformat(when.replace(" ", "T").replace("Z", "+00:00")).date()
    except ValueError:
        day = None
    merchant = " ".join(m["merchant"].split())
    currency = (m["currency"] or "EUR").upper()
    # Keep digits, separators and sign: "12,45 €", "€12.45", "12,45 EUR" -> "12,45".
    amount_text = re.sub(r"[^\d,.\-+]", "", m["amount"])
    try:
        cents = to_cents(amount_text) if amount_text else None
    except ValueError:
        cents = None

    problem = None
    if day is None:
        problem = "unreadable date"
    elif currency != "EUR":
        problem = f"amount is in {currency}, not EUR"
    elif not merchant:
        problem = "blank merchant"
    elif cents is None:
        problem = "unreadable amount" if m["amount"].strip() else "blank amount"
    elif cents == 0:
        problem = "amount is 0,00 €"
    return Transaction(line, day, merchant, cents, currency, problem)


def message_text(msg: EmailMessage) -> str:
    """Plain-text body, or the HTML body with tags stripped if there's no plain part."""
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    try:
        text = part.get_content()
    except (LookupError, UnicodeDecodeError):
        text = part.get_payload(decode=True).decode("utf-8", errors="replace")
    if part.get_content_type() == "text/html":
        text = re.sub(r"(?i)<br\s*/?>|</p>|</div>", "\n", text)
        text = html.unescape(re.sub(r"<[^>]+>", "", text))
    return text


def parse_message(raw: bytes) -> EmailMessage:
    return email.message_from_bytes(raw, policy=email.policy.default)


def canonical_gmail(address: str) -> str:
    """j.doe+budget@googlemail.com and jdoe@gmail.com are the same Gmail inbox."""
    address = (address or "").strip().lower()
    local, _, domain = address.partition("@")
    if domain in ("gmail.com", "googlemail.com"):
        local = local.split("+", 1)[0].replace(".", "")
        domain = "gmail.com"
    return f"{local}@{domain}"


def sender_problem(msg: EmailMessage, my_address: str) -> str | None:
    """None if the email really comes from you, otherwise why it was refused."""
    sender = email.utils.parseaddr(str(msg.get("From", "")))[1]
    if canonical_gmail(sender) != canonical_gmail(my_address):
        return f"sent from {sender or 'an unknown address'}, not from you"
    # Mail that arrived from outside carries Google's verdict; refuse forged "From" lines.
    for result in msg.get_all("Authentication-Results", []):
        verdict = str(result).lower()
        if "dmarc=fail" in verdict or "spf=fail" in verdict or "dkim=fail" in verdict:
            return "failed Gmail's sender check (possibly forged)"
    return None


def subject_ok(msg: EmailMessage) -> bool:
    return str(msg.get("Subject", "")).strip().upper() == SUBJECT


def message_id(msg: EmailMessage, raw: bytes) -> str:
    mid = str(msg.get("Message-ID", "")).strip()
    if mid:
        return mid
    import hashlib
    return "sha1:" + hashlib.sha1(raw).hexdigest()


# --- IMAP -------------------------------------------------------------------------


class GmailError(Exception):
    """A problem talking to Gmail, explained in plain words."""


def explain(exc: Exception) -> str:
    text = str(exc)
    low = text.lower()
    if isinstance(exc, GmailError):
        return text
    if "application-specific password required" in low or "authenticationfailed" in low \
            or "invalid credentials" in low or "username and password not accepted" in low:
        return ("Gmail rejected the address or app password. Use a 16-letter app password "
                "(not your normal Google password); app passwords need 2-Step Verification turned on.")
    if "not enabled for imap" in low or "imap access is disabled" in low:
        return "IMAP is turned off for this Gmail account. Turn it on in Gmail → Settings → Forwarding and POP/IMAP."
    if "too many" in low or "web login required" in low:
        return "Gmail is temporarily blocking sign-ins for this account. Wait a few minutes, or sign in at gmail.com once, then try again."
    if isinstance(exc, (socket.gaierror, socket.timeout, TimeoutError, ConnectionError)):
        return "Couldn't reach imap.gmail.com. Check that the Mac is online."
    if isinstance(exc, ssl.SSLError):
        return f"Secure connection to Gmail failed ({exc.__class__.__name__}). Check the Mac's date and time."
    if isinstance(exc, OSError):
        return f"Network error talking to Gmail: {text}"
    return f"Gmail said: {text}"


def _quote_mailbox(label: str) -> str:
    return '"' + label.replace("\\", "\\\\").replace('"', '\\"') + '"'


class GmailClient:
    def __init__(self, address: str, password: str, label: str, timeout: float = 30):
        self.address, self.password, self.label, self.timeout = address, password, label, timeout
        self.imap: imaplib.IMAP4_SSL | None = None
        self.uidvalidity: int | None = None

    def __enter__(self):
        try:
            self.imap = imaplib.IMAP4_SSL(IMAP_HOST, 993, timeout=self.timeout)
            self.imap.login(self.address, self.password)
        except (imaplib.IMAP4.error, OSError) as exc:
            raise GmailError(explain(exc)) from exc
        status, data = self.imap.select(_quote_mailbox(self.label), readonly=True)
        if status != "OK":
            raise GmailError(
                f"Signed in, but there's no Gmail label called “{self.label}”. "
                "Check the label name (it's case-sensitive) and that your filter applies it.")
        status, data = self.imap.response("UIDVALIDITY")
        self.uidvalidity = int(data[0]) if data and data[0] else None
        return self

    def __exit__(self, *exc):
        try:
            if self.imap is not None:
                self.imap.logout()
        except Exception:
            pass

    def _uid(self, *args):
        try:
            status, data = self.imap.uid(*args)
        except (imaplib.IMAP4.error, OSError) as exc:
            raise GmailError(explain(exc)) from exc
        if status != "OK":
            raise GmailError(f"Gmail refused the request ({status}).")
        return data

    def search_budget_uids(self, after_uid: int = 0) -> list[int]:
        """UIDs in the label whose subject contains BUDGET (exact match is checked later)."""
        data = self._uid("SEARCH", None, f"UID {after_uid + 1}:*", "SUBJECT", f'"{SUBJECT}"')
        uids = [int(u) for u in (data[0] or b"").split()]
        return sorted(u for u in uids if u > after_uid)   # "n:*" can return the last UID even if < n

    def fetch(self, uids: list[int]) -> list[tuple[int, bytes]]:
        out = []
        for start in range(0, len(uids), 50):
            chunk = ",".join(str(u) for u in uids[start:start + 50])
            data = self._uid("FETCH", chunk, "(UID BODY.PEEK[])")   # PEEK: don't mark as read
            for item in data:
                if isinstance(item, tuple):
                    m = re.search(rb"UID (\d+)", item[0])
                    if m:
                        out.append((int(m.group(1)), item[1]))
        return sorted(out)


def test_connection(address: str, password: str, label: str) -> dict:
    """Try to sign in and open the label; report what happened in plain words."""
    if not address or "@" not in address:
        return {"ok": False, "message": "Enter your Gmail address first."}
    if not password:
        return {"ok": False, "message": "Enter your Gmail app password first."}
    try:
        with GmailClient(address, password, label, timeout=20) as client:
            count = len(client.search_budget_uids(0))
    except GmailError as exc:
        return {"ok": False, "message": str(exc)}
    except Exception as exc:  # noqa: BLE001 - always answer the button with a reason
        return {"ok": False, "message": explain(exc)}
    return {"ok": True, "message": f"Signed in as {address}. The “{label}” label has "
                                   f"{count} email{'s' if count != 1 else ''} with the subject {SUBJECT}."}
