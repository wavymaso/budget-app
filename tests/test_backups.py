from datetime import date, timedelta

from app import backups, config, db


def test_one_automatic_backup_a_day_and_only_the_newest_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "budget.db")
    db.init_db()
    manual = backups.make_backup()
    start = date(2026, 9, 1)
    for i in range(20):
        backups.auto_backup(start + timedelta(days=i))
    assert backups.auto_backup(start + timedelta(days=19)) is None   # already made today
    autos = sorted(p.name for p in backups.backup_dir().glob("budget-auto-*.db"))
    assert len(autos) == backups.AUTO_KEEP
    assert autos[-1] == "budget-auto-2026-09-20.db"
    assert manual.exists()                                            # yours are never deleted
    listed = backups.list_backups()
    assert sum(b["automatic"] for b in listed) == backups.AUTO_KEEP
    assert backups.backup_dir() == tmp_path / "backups"               # next to the database


def test_no_backup_without_a_database(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "missing.db")
    assert backups.auto_backup() is None
