import pytest

from app import config, db


@pytest.fixture
def conn(tmp_path, monkeypatch):
    """A fresh, seeded database in a temp folder (never touches data/budget.db)."""
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    db.init_db()
    c = db.connect()
    yield c
    c.close()


@pytest.fixture
def cat(conn):
    """Look up a category id by name: cat("Groceries")."""
    ids = {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM categories")}
    return ids.__getitem__


@pytest.fixture(autouse=True)
def fake_keychain(monkeypatch):
    """Tests never read or write your real macOS Keychain."""
    from app import gmail
    store = {}
    monkeypatch.setattr(gmail, "get_password", lambda a: store.get((a or "").lower()))
    monkeypatch.setattr(gmail, "set_password", lambda a, p: store.__setitem__(a.lower(), p))
    monkeypatch.setattr(gmail, "delete_password", lambda a: store.pop((a or "").lower(), None))
    return store
