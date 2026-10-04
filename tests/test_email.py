from email.message import EmailMessage

import pytest
from fastapi.testclient import TestClient

from app import config, email_sync, gmail, main

ME = "jane.doe@gmail.com"


def make_email(body, *, sender=ME, subject="BUDGET", msg_id="<1@mail.gmail.com>", html=None, auth=None):
    m = EmailMessage()
    m["From"] = f"Jane <{sender}>"
    m["To"] = "jane.doe+budget@gmail.com"
    m["Subject"] = subject
    m["Date"] = "Sat, 04 Oct 2026 13:22:07 +0200"
    if msg_id:
        m["Message-ID"] = msg_id
    if auth:
        m["Authentication-Results"] = auth
    if html is not None:
        m.set_content(html, subtype="html")
    else:
        m.set_content(body)
    return m.as_bytes()


LINE = "2026-10-04T13:22:05+02:00;MERCADONA;12,45 €;EUR"


# --- reading the line -------------------------------------------------------------

@pytest.mark.parametrize("line, cents", [
    (LINE, 1245),
    ("2026-10-04T13:22:05+02:00;MERCADONA;€12.45;EUR", 1245),
    ("2026-10-04T13:22:05+02:00;Zara;1.234,56 €;EUR", 123456),
    ("2026-10-04T13:22:05+02:00;Metro;1,70 €;EUR", 170),
    ("2026-10-04T13:22:05Z;Metro;1,70 €", 170),            # currency missing -> EUR
    ("2026-10-04;Metro;1,70 €;EUR", 170),                   # date only
])
def test_reads_amounts(line, cents):
    tx = gmail.find_transaction(line)
    assert tx.amount_cents == cents and tx.problem is None


def test_uses_the_phone_local_date():
    # 00:30 in Spain (UTC+2) is still the 5th there, even though it's the 4th in UTC.
    tx = gmail.find_transaction("2026-10-05T00:30:00+02:00;Bar;3 €;EUR")
    assert tx.date.isoformat() == "2026-10-05"


def test_ignores_signature_and_other_text():
    body = f"Hola\n\n{LINE}\n\nSent from my iPhone\n12;34;56"
    tx = gmail.find_transaction(body)
    assert (tx.merchant, tx.amount_cents) == ("MERCADONA", 1245)


@pytest.mark.parametrize("line, problem", [
    ("2026-10-04T13:22:05+02:00;;12,45 €;EUR", "blank merchant"),
    ("2026-10-04T13:22:05+02:00;MERCADONA;0,00 €;EUR", "amount is 0,00 €"),
    ("2026-10-04T13:22:05+02:00;MERCADONA;;EUR", "blank amount"),
    ("2026-10-04T13:22:05+02:00;Starbucks;5,00 $;USD", "amount is in USD, not EUR"),
])
def test_problems_go_to_review(line, problem):
    assert gmail.find_transaction(line).problem == problem


def test_no_line_found():
    assert gmail.find_transaction("Sent from my iPhone") is None


def test_html_only_email():
    raw = make_email(None, html=f"<div>{LINE}</div><div><br></div><div>Sent from my iPhone</div>")
    assert gmail.find_transaction(gmail.message_text(gmail.parse_message(raw))).merchant == "MERCADONA"


# --- who sent it -------------------------------------------------------------------

@pytest.mark.parametrize("sender, ok", [
    (ME, True),
    ("Jane.Doe@gmail.com", True),
    ("janedoe+budget@googlemail.com", True),     # same Gmail inbox
    ("someone.else@gmail.com", False),
    ("jane.doe@gmail.com.evil.com", False),
])
def test_sender_must_be_me(sender, ok):
    msg = gmail.parse_message(make_email(LINE, sender=sender))
    assert (gmail.sender_problem(msg, ME) is None) == ok


def test_forged_sender_is_refused():
    msg = gmail.parse_message(make_email(LINE, auth="mx.google.com; dmarc=fail (p=NONE) header.from=gmail.com"))
    assert "forged" in gmail.sender_problem(msg, ME)


# --- processing and syncing ---------------------------------------------------------

@pytest.fixture
def gmail_setup(conn, fake_keychain):
    email_sync.save_config(conn, address=ME, label="Budget", enabled=True)
    fake_keychain[ME] = "abcdabcdabcdabcd"
    return conn


def fetcher_for(*emails, uidvalidity=1):
    """A fake Gmail label holding these emails as UIDs 1..n."""
    def fetch(cfg, password, after):
        return uidvalidity, [(i + 1, raw) for i, raw in enumerate(emails) if i + 1 > after]
    return fetch


def expenses(conn):
    return conn.execute("SELECT merchant_raw, amount_cents, date, source, category_id FROM expenses").fetchall()


def test_imports_and_categorizes(gmail_setup, cat):
    r = email_sync.sync(gmail_setup, fetcher=fetcher_for(make_email(LINE)), use_ai=False)
    assert (r["imported"], r["review"], r["error"]) == (1, 0, None)
    (row,) = expenses(gmail_setup)
    assert tuple(row) == ("MERCADONA", 1245, "2026-10-04", "email", cat("Groceries"))


def test_never_imports_the_same_email_twice(gmail_setup):
    raw = make_email(LINE)
    email_sync.sync(gmail_setup, fetcher=fetcher_for(raw), use_ai=False)
    # Gmail renumbers the label (new UIDVALIDITY) and the email shows up again.
    r = email_sync.sync(gmail_setup, fetcher=fetcher_for(raw, uidvalidity=2), use_ai=False)
    assert r["imported"] == 0 and len(expenses(gmail_setup)) == 1


def test_only_new_uids_are_fetched(gmail_setup):
    seen = []
    def fetch(cfg, password, after):
        seen.append(after)
        return 1, []
    email_sync.sync(gmail_setup, fetcher=fetcher_for(make_email(LINE)), use_ai=False)
    email_sync.sync(gmail_setup, fetcher=fetch, use_ai=False)
    assert seen == [1]


def test_two_identical_coffees_are_both_imported(gmail_setup):
    line = "2026-10-04T09:00:00+02:00;Starbucks;3,50 €;EUR"
    r = email_sync.sync(gmail_setup, fetcher=fetcher_for(make_email(line, msg_id="<a@x>"),
                                                         make_email(line, msg_id="<b@x>")), use_ai=False)
    assert r["imported"] == 2


def test_duplicate_of_bank_import_goes_to_review(gmail_setup):
    gmail_setup.execute(
        "INSERT INTO expenses (amount_cents, merchant_raw, merchant_norm, date, source) "
        "VALUES (1245, 'COMPRA EN MERCADONA MADRID 4521', 'mercadona', '2026-10-04', 'csv')")
    r = email_sync.sync(gmail_setup, fetcher=fetcher_for(make_email(LINE)), use_ai=False)
    assert r["review"] == 1 and len(expenses(gmail_setup)) == 1
    reason = gmail_setup.execute("SELECT reason FROM email_messages").fetchone()[0]
    assert "already in a bank import" in reason


def test_bank_csv_flags_email_imports_as_duplicates(gmail_setup):
    from app import importer
    email_sync.sync(gmail_setup, fetcher=fetcher_for(make_email(LINE)), use_ai=False)
    dup = importer.find_duplicate(gmail_setup, "2026-10-04", 1245, "COMPRA EN MERCADONA MADRID 4521", "h")
    assert dup and dup["reason"] == "already logged from your iPhone"


def test_problem_emails_wait_for_review(gmail_setup):
    emails = [
        make_email("2026-10-04T10:00:00+02:00;;4,00 €;EUR", msg_id="<blank@x>"),
        make_email("2026-10-04T10:00:00+02:00;Metro;0,00 €;EUR", msg_id="<zero@x>"),
        make_email("Sent from my iPhone", msg_id="<empty@x>"),
    ]
    r = email_sync.sync(gmail_setup, fetcher=fetcher_for(*emails), use_ai=False)
    assert (r["imported"], r["review"]) == (0, 3)
    assert expenses(gmail_setup) == []


def test_other_senders_and_subjects(gmail_setup):
    emails = [make_email(LINE, sender="stranger@gmail.com", msg_id="<s@x>"),
              make_email(LINE, subject="Re: BUDGET", msg_id="<re@x>"),
              make_email(LINE, subject="budget ", msg_id="<lower@x>")]
    r = email_sync.sync(gmail_setup, fetcher=fetcher_for(*emails), use_ai=False)
    assert (r["refused"], r["skipped"], r["imported"]) == (1, 1, 1)


def test_sync_reports_errors(conn, fake_keychain):
    assert email_sync.sync(conn)["error"] == "Gmail isn't set up yet."
    email_sync.save_config(conn, address=ME)
    assert email_sync.sync(conn)["error"] == "No app password saved for this address."
    fake_keychain[ME] = "x"
    def broken(cfg, password, after):
        raise gmail.GmailError("Gmail rejected the address or app password.")
    r = email_sync.sync(conn, fetcher=broken)
    assert r["error"].startswith("Gmail rejected")
    assert conn.execute("SELECT value FROM settings WHERE key = 'email_last_sync'").fetchone()


# --- IMAP: read-only -----------------------------------------------------------------

class FakeIMAP:
    commands = []

    def __init__(self, host, port, timeout=None):
        FakeIMAP.commands = [("connect", host, port)]

    def login(self, user, password):
        FakeIMAP.commands.append(("login", user))
        if password != "good":
            import imaplib
            raise imaplib.IMAP4.error(b"[AUTHENTICATIONFAILED] Invalid credentials (Failure)")
        return "OK", [b""]

    def select(self, mailbox, readonly=False):
        FakeIMAP.commands.append(("select", mailbox, readonly))
        return ("OK", [b"3"]) if mailbox == '"Budget"' else ("NO", [b"[NONEXISTENT] Unknown Mailbox"])

    def response(self, code):
        return code, [b"7"]

    def uid(self, command, *args):
        FakeIMAP.commands.append(("uid", command, *args))
        if command == "SEARCH":
            return "OK", [b"5 6"]
        return "OK", [(b"5 (UID 5 BODY[] {10}", make_email(LINE)), b")"]

    def logout(self):
        FakeIMAP.commands.append(("logout",))


@pytest.fixture
def fake_imap(monkeypatch):
    monkeypatch.setattr(gmail.imaplib, "IMAP4_SSL", FakeIMAP)


def test_gmail_is_opened_read_only(fake_imap):
    with gmail.GmailClient(ME, "good", "Budget") as c:
        assert c.search_budget_uids(5) == [6]
        c.fetch([6])
    names = [cmd[1] if cmd[0] == "uid" else cmd[0] for cmd in FakeIMAP.commands]
    assert ("select", '"Budget"', True) in FakeIMAP.commands
    assert any("BODY.PEEK[]" in str(cmd) for cmd in FakeIMAP.commands)
    assert not {"STORE", "EXPUNGE", "COPY", "MOVE", "store", "expunge"} & set(names)


def test_connection_messages(fake_imap):
    ok = gmail.test_connection(ME, "good", "Budget")
    assert ok["ok"] and "Signed in" in ok["message"] and "2 emails" in ok["message"]
    bad = gmail.test_connection(ME, "wrong", "Budget")
    assert not bad["ok"] and "app password" in bad["message"]
    no_label = gmail.test_connection(ME, "good", "Presupuesto")
    assert not no_label["ok"] and "no Gmail label called “Presupuesto”" in no_label["message"]
    assert gmail.test_connection("", "good", "Budget")["message"] == "Enter your Gmail address first."
    assert "Couldn't reach" in gmail.explain(OSError.__new__(TimeoutError))


# --- API: settings and review list ---------------------------------------------------

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "api.db")
    with TestClient(main.app, client=("127.0.0.1", 1)) as c:
        yield c


def test_password_goes_to_keychain_not_database(client, fake_keychain):
    r = client.put("/api/email/settings", json={"address": ME, "label": "Budget", "password": "abcd efgh ijkl mnop"})
    assert r.json()["has_password"] is True and "password" not in r.json()
    assert fake_keychain[ME] == "abcdefghijklmnop"
    dump = "\n".join(config.DB_PATH.parent.joinpath("api.db").read_bytes().decode("latin-1").split("\x00"))
    assert "abcdefghijklmnop" not in dump
    client.put("/api/email/settings", json={"address": ME, "label": "Budget", "forget_password": True})
    assert ME not in fake_keychain


def test_review_accept_and_dismiss(client, fake_keychain):
    from app.db import connect
    conn = connect()
    email_sync.save_config(conn, address=ME, enabled=True)
    fake_keychain[ME] = "x"
    email_sync.sync(conn, fetcher=fetcher_for(
        make_email("2026-10-04T10:00:00+02:00;;4,00 €;EUR", msg_id="<blank@x>"),
        make_email("Sent from my iPhone", msg_id="<empty@x>")), use_ai=False)
    conn.close()
    items = client.get("/api/email/review").json()
    assert {i["reason"] for i in items} == {"blank merchant", "no transaction line found"}
    assert client.get("/api/email/status").json()["review_count"] == 2
    blank = next(i for i in items if i["reason"] == "blank merchant")
    r = client.post(f"/api/email/review/{blank['id']}/accept",
                    json={"merchant": "Lidl", "amount": "4,00", "date": "2026-10-04"})
    assert r.status_code == 201 and r.json()["category_name"] == "Groceries" and r.json()["source"] == "email"
    other = next(i for i in items if i["id"] != blank["id"])
    assert client.post(f"/api/email/review/{other['id']}/dismiss").status_code == 200
    assert client.get("/api/email/review").json() == []
    assert client.post(f"/api/email/review/{other['id']}/dismiss").status_code == 404
