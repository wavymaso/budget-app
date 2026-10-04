import sqlite3

import pytest

from app import config, db


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    legacy = tmp_path / "project" / "data"
    new = tmp_path / "support"
    monkeypatch.setattr(config, "LEGACY_DATA_DIR", legacy)
    monkeypatch.setattr(config, "DATA_DIR", new)
    monkeypatch.setattr(config, "DB_PATH", new / "budget.db")
    monkeypatch.setattr(config, "BACKUP_DIR", new / "backups")
    return legacy, new


def make_old_db(legacy):
    legacy.mkdir(parents=True)
    (legacy / "backups").mkdir()
    (legacy / "backups" / "budget-2026-10-01_10-00-00.db").write_bytes(b"old backup")
    conn = sqlite3.connect(legacy / "budget.db")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("CREATE TABLE t (x)")
    conn.execute("INSERT INTO t VALUES (42)")
    conn.commit()
    return conn  # left open, so the row may still be sitting in the -wal file


def test_moves_old_database_and_backups(dirs):
    legacy, new = dirs
    still_open = make_old_db(legacy)
    msg = db.migrate_legacy_data()
    still_open.close()
    assert msg and "budget.db" in msg
    assert sqlite3.connect(new / "budget.db").execute("SELECT x FROM t").fetchone() == (42,)
    assert (new / "backups" / "budget-2026-10-01_10-00-00.db").read_bytes() == b"old backup"
    assert (legacy / "budget.db").exists()  # original left in place


def test_never_overwrites_existing_data(dirs):
    legacy, new = dirs
    make_old_db(legacy).close()
    new.mkdir()
    sqlite3.connect(new / "budget.db").execute("CREATE TABLE mine (y)").connection.commit()
    assert db.migrate_legacy_data() is None
    tables = {r[0] for r in sqlite3.connect(new / "budget.db").execute("SELECT name FROM sqlite_master")}
    assert tables == {"mine"}


def test_nothing_to_migrate(dirs):
    assert db.migrate_legacy_data() is None
    assert not config.DB_PATH.exists()
