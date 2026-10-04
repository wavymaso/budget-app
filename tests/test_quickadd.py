import pytest
from fastapi.testclient import TestClient

from app import config, main


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "api.db")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("QUICKADD_TOKEN", "s3cret")
    # Pretend requests come from this computer unless a test says otherwise.
    with TestClient(main.app, client=("127.0.0.1", 50000)) as c:
        yield c


AUTH = {"Authorization": "Bearer s3cret"}


def test_quick_add_categorizes_and_returns_message(client):
    r = client.post("/api/expenses/quick", headers=AUTH,
                    json={"amount": "4,50", "merchant": "Starbucks Gran Via", "date": "03/10/2026"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert (body["amount_cents"], body["date"], body["source"]) == (450, "2026-10-03", "api")
    assert body["category_name"] == "Eating Out"
    assert body["message"] == "Saved 4,50 € at Starbucks Gran Via · Eating Out"


def test_quick_add_with_explicit_category(client):
    r = client.post("/api/expenses/quick", headers=AUTH,
                    json={"amount": 12, "merchant": "Libros", "category": "university"})
    assert r.json()["category_name"] == "University"
    assert client.get("/api/suggest", params={"merchant": "Libros"}).json()["source"] == "learned"


def test_quick_add_rejects_bad_token(client):
    assert client.post("/api/expenses/quick", json={"amount": 1, "merchant": "x"}).status_code == 401
    bad = {"Authorization": "Bearer nope"}
    assert client.post("/api/expenses/quick", headers=bad, json={"amount": 1, "merchant": "x"}).status_code == 401


def test_quick_add_disabled_without_token(client, monkeypatch):
    monkeypatch.delenv("QUICKADD_TOKEN")
    r = client.post("/api/expenses/quick", headers=AUTH, json={"amount": 1, "merchant": "x"})
    assert r.status_code == 503


def test_quick_add_validates(client):
    r = client.post("/api/expenses/quick", headers=AUTH, json={"amount": "abc", "merchant": "x"})
    assert r.status_code == 422
    r = client.post("/api/expenses/quick", headers=AUTH, json={"amount": 3, "merchant": "x", "date": "tomorrow"})
    assert r.status_code == 422


def test_other_devices_only_reach_quick_add(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "lan.db")
    monkeypatch.setenv("QUICKADD_TOKEN", "s3cret")
    with TestClient(main.app, client=("192.168.1.50", 50000)) as phone:
        assert phone.get("/").status_code == 403
        assert phone.get("/api/expenses").status_code == 403
        r = phone.post("/api/expenses/quick", headers=AUTH, json={"amount": "2", "merchant": "Metro"})
        assert r.status_code == 201
