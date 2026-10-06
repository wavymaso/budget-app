import pytest
from fastapi.testclient import TestClient

from app import config, main


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "prefs.db")
    with TestClient(main.app, client=("127.0.0.1", 50000)) as c:
        yield c


def test_theme_defaults_to_automatic(client):
    assert client.get("/api/preferences").json() == {"theme": "auto"}


def test_theme_is_saved(client):
    assert client.put("/api/preferences", json={"theme": "sand"}).json()["theme"] == "sand"
    assert client.get("/api/preferences").json()["theme"] == "sand"
    # Sending nothing keeps the current choice.
    assert client.put("/api/preferences", json={}).json()["theme"] == "sand"


def test_unknown_theme_is_refused(client):
    assert client.put("/api/preferences", json={"theme": "neon"}).status_code == 422
    assert client.get("/api/preferences").json()["theme"] == "auto"
