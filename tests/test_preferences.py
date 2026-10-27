import pytest
from fastapi.testclient import TestClient

from app import config, main


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "prefs.db")
    with TestClient(main.app, client=("127.0.0.1", 50000)) as c:
        yield c


def test_theme_defaults_to_automatic(client):
    assert client.get("/api/preferences").json()["theme"] == "auto"


def test_theme_is_saved(client):
    assert client.put("/api/preferences", json={"theme": "teja"}).json()["theme"] == "teja"
    assert client.get("/api/preferences").json()["theme"] == "teja"
    # Sending nothing keeps the current choice.
    assert client.put("/api/preferences", json={}).json()["theme"] == "teja"


def test_unknown_theme_is_refused(client):
    assert client.put("/api/preferences", json={"theme": "neon"}).status_code == 422
    assert client.get("/api/preferences").json()["theme"] == "auto"


def test_month_summary_and_shortcut_warning_can_be_hidden(client):
    prefs = client.put("/api/preferences", json={"summary_dismissed": "2026-09", "shortcut_snoozed_until": "2026-10-14"}).json()
    assert (prefs["summary_dismissed"], prefs["shortcut_snoozed_until"], prefs["theme"]) == ("2026-09", "2026-10-14", "auto")
    assert client.put("/api/preferences", json={"summary_dismissed": "September"}).status_code == 422


def test_campo_themes_are_accepted(client):
    for theme in ("verde", "azul", "mar", "ciruela", "teja", "tinta", "noche"):
        assert client.put("/api/preferences", json={"theme": theme}).json()["theme"] == theme


def test_old_themes_open_as_their_nearest_new_one(client):
    # Saved by an older app (Mac or phone): stored and read back as the new name.
    for old, new in (("light", "verde"), ("dark", "noche"), ("sand", "teja"), ("ocean", "mar"),
                     ("lavender", "ciruela"), ("rose", "ciruela"), ("noir", "noche")):
        assert client.put("/api/preferences", json={"theme": old}).json()["theme"] == new
    from app.db import connect, set_setting
    conn = connect()
    try:
        set_setting(conn, "preferences", {"theme": "sand"})     # stored before this version
        conn.commit()
    finally:
        conn.close()
    assert client.get("/api/preferences").json()["theme"] == "teja"


def test_preferences_say_which_computer_this_is(client, monkeypatch):
    assert client.get("/api/preferences").json()["computer"] == config.COMPUTER
    monkeypatch.setattr(config, "COMPUTER", "PC")
    prefs = client.put("/api/preferences", json={"theme": "noir"}).json()
    assert prefs["computer"] == "PC"
    # It's reported, never stored as a preference.
    from app.db import connect, get_setting
    conn = connect()
    try:
        assert "computer" not in get_setting(conn, "preferences")
    finally:
        conn.close()


def test_data_folder_on_windows(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "WINDOWS", True)
    monkeypatch.setattr(config, "MAC", False)
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    assert config._default_data_dir() == tmp_path / "Roaming" / "Budget"
    assert config._default_log_dir() == tmp_path / "Local" / "Budget" / "Logs"
