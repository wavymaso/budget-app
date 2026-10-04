from app import desktop


class FakeWindow:
    def __init__(self, answer):
        self.answer = answer

    def create_file_dialog(self, *args, **kwargs):
        self.kwargs = kwargs
        return self.answer


def test_export_writes_csv_where_you_chose(conn, cat, tmp_path):
    conn.execute(
        "INSERT INTO expenses (amount_cents, merchant_raw, merchant_norm, category_id, date) "
        "VALUES (1250, 'Mercadona', 'mercadona', ?, '2026-10-03')", (cat("Groceries"),))
    conn.commit()
    api = desktop.DesktopApi()
    target = tmp_path / "mine.csv"
    api._window = FakeWindow((str(target),))
    assert api.export_csv() == str(target)
    text = target.read_text(encoding="utf-8")
    assert "03/10/2026;Mercadona;12,50;Groceries" in text
    assert api._window.kwargs["save_filename"].startswith("budget-export-")


def test_export_cancelled(conn):
    api = desktop.DesktopApi()
    api._window = FakeWindow(None)
    assert api.export_csv() is None
