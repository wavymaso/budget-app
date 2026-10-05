import pytest
from fastapi.testclient import TestClient

from app import auth, config, main, server
from app.db import connect

PHONE = ("192.168.1.50", 50000)
MAC = ("127.0.0.1", 50000)


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "phone.db")
    auth._failures.clear()
    return tmp_path / "phone.db"


@pytest.fixture
def mac(db_path):
    with TestClient(main.app, client=MAC) as c:
        yield c


@pytest.fixture
def phone(db_path):
    with TestClient(main.app, client=PHONE, follow_redirects=False) as c:
        yield c


def set_password(mac, pw="hunter22"):
    r = mac.put("/api/phone", json={"enabled": False, "port": 8000, "password": pw})
    assert r.status_code == 200, r.text


def test_mac_needs_no_login(mac):
    assert mac.get("/api/expenses").status_code == 200
    assert mac.get("/api/auth/me").json() == {"local": True}


def test_phone_is_sent_to_login(phone):
    r = phone.get("/")
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert phone.get("/login").status_code == 200
    assert phone.get("/static/app.js").status_code == 200        # code only, no data
    assert phone.get("/api/expenses").status_code == 401
    assert phone.get("/api/dashboard").status_code == 401
    assert phone.get("/api/auth/me").json() == {"local": False}


def test_login_flow(mac, phone):
    set_password(mac)
    assert phone.post("/api/auth/login", json={"password": "wrong"}).status_code == 401
    r = phone.post("/api/auth/login", json={"password": "hunter22"})
    assert r.status_code == 200
    cookie = r.headers["set-cookie"]
    assert "HttpOnly" in cookie and "samesite=lax" in cookie.lower()
    assert phone.get("/api/expenses").status_code == 200
    assert phone.get("/").status_code == 200
    phone.post("/api/auth/logout")
    assert phone.get("/api/expenses").status_code == 401


def test_login_impossible_without_a_password(phone):
    r = phone.post("/api/auth/login", json={"password": ""})
    assert r.status_code == 403 and "Set one on your Mac" in r.json()["detail"]


def test_guessing_is_slowed_down(mac, phone):
    set_password(mac)
    for _ in range(auth.MAX_FAILURES):
        assert phone.post("/api/auth/login", json={"password": "nope"}).status_code == 401
    r = phone.post("/api/auth/login", json={"password": "hunter22"})   # even the right one waits
    assert r.status_code == 429


def test_phone_cannot_change_mac_only_settings(mac, phone):
    set_password(mac)
    phone.post("/api/auth/login", json={"password": "hunter22"})
    for method, path in [("get", "/api/phone"), ("put", "/api/phone"), ("post", "/api/phone/sign-out-all"),
                         ("get", "/api/email/settings"), ("put", "/api/email/settings"), ("post", "/api/email/test")]:
        kwargs = {} if method == "get" else {"json": {}}
        assert getattr(phone, method)(path, **kwargs).status_code == 403, path
    assert phone.get("/api/email/review").status_code == 200        # reviewing imports is fine


def test_new_password_signs_phones_out(mac, phone):
    set_password(mac)
    phone.post("/api/auth/login", json={"password": "hunter22"})
    assert len(mac.get("/api/phone").json()["sessions"]) == 1
    set_password(mac, "another-one")
    assert phone.get("/api/expenses").status_code == 401
    assert mac.get("/api/phone").json()["sessions"] == []


def test_sign_out_all(mac, phone):
    set_password(mac)
    phone.post("/api/auth/login", json={"password": "hunter22"})
    mac.post("/api/phone/sign-out-all")
    assert phone.get("/api/expenses").status_code == 401


def test_password_is_hashed_and_rules(mac, db_path):
    assert mac.put("/api/phone", json={"enabled": False, "port": 8000, "password": "123"}).status_code == 422
    r = mac.put("/api/phone", json={"enabled": True, "port": 8000})
    assert r.status_code == 422 and "password" in r.json()["detail"]
    set_password(mac, "hunter22")
    assert b"hunter22" not in db_path.read_bytes()
    conn = connect()
    assert auth.check_password(conn, "hunter22") and not auth.check_password(conn, "hunter23")
    conn.close()


def test_session_tokens_are_stored_hashed(mac, phone, db_path):
    set_password(mac)
    token = phone.post("/api/auth/login", json={"password": "hunter22"}).cookies[auth.COOKIE]
    conn = connect()
    stored = [r[0] for r in conn.execute("SELECT token_hash FROM sessions")]
    conn.close()
    assert stored and token not in stored


def test_turning_phone_access_on_and_off(mac, monkeypatch):
    calls = []

    class FakePhoneAccess:
        running, error, port = False, None, None
        def apply(self, enabled, port):
            calls.append((enabled, port))
            self.running, self.port = enabled, port
        def urls(self):
            return [f"http://mac.local:{self.port}"] if self.running else []

    monkeypatch.setattr(server, "phone_access", FakePhoneAccess())
    set_password(mac)
    on = mac.put("/api/phone", json={"enabled": True, "port": 8123}).json()
    assert on["running"] and on["urls"] == ["http://mac.local:8123"] and on["enabled"]
    off = mac.put("/api/phone", json={"enabled": False, "port": 8123}).json()
    assert not off["running"]
    assert calls == [(False, 8000), (True, 8123), (False, 8123)]


def test_real_phone_server_starts_and_stops(db_path):
    pa = server.PhoneAccess()
    pa.apply(True, 0)           # port 0 = any free port
    try:
        assert pa.running and pa.port and pa.error is None
    finally:
        pa.stop()
    assert not pa.running
