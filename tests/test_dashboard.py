from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import config, main


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "dash.db")
    with TestClient(main.app, client=("127.0.0.1", 50000)) as c:
        yield c


def test_daily_totals_and_counts_for_the_heatmap(client):
    for amount, merchant, day in [("12", "Lidl", "2026-09-05"), ("3,50", "Café", "2026-09-05"), ("-2", "Refund", "2026-09-06")]:
        client.post("/api/expenses", json={"amount": amount, "merchant": merchant, "date": day})
    d = client.get("/api/dashboard", params={"period": "month", "date": "2026-09-01"}).json()
    by_day = {x["date"]: x for x in d["daily"]}
    assert len(d["daily"]) == 30                                  # every day of September, zeros included
    assert (by_day["2026-09-05"]["cents"], by_day["2026-09-05"]["count"]) == (1550, 2)
    assert (by_day["2026-09-06"]["cents"], by_day["2026-09-06"]["count"]) == (-200, 1)
    assert (by_day["2026-09-07"]["cents"], by_day["2026-09-07"]["count"]) == (0, 0)
