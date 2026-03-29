from pathlib import Path

from fastapi.testclient import TestClient

from bookkeeping_app.api import app
from bookkeeping_app.metrics import metrics


client = TestClient(app)


def test_health_endpoint() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_extract_transactions_csv_returns_normalized_transactions() -> None:
    csv_bytes = b"date,amount,merchant,category\n2026-03-01,-12.50,Starbucks,Coffee\n"

    response = client.post(
        "/extract-transactions-csv",
        files={"file": ("transactions.csv", csv_bytes, "text/csv")},
    )

    assert response.status_code == 200
    assert response.json() == [
        {
            "date": "2026-03-01",
            "amount": -12.5,
            "merchant": "Starbucks",
            "category": "Coffee",
        }
    ]


def test_recategorize_transactions_csv_uses_review_service(monkeypatch) -> None:
    def fake_review(transactions):
        assert transactions == [
            {
                "date": "2026-03-01",
                "amount": -12.5,
                "merchant": "Starbucks",
                "category": "Coffee",
            }
        ]
        return [
            {
                "date": "2026-03-01",
                "amount": -12.5,
                "merchant": "Starbucks",
                "original_category": "Coffee",
                "suggested_category": "Coffee",
                "reason": "Consistent with prior categorization.",
            }
        ]

    monkeypatch.setattr("bookkeeping_app.api.review_transaction_categories", fake_review)

    response = client.post(
        "/recategorize-transactions-csv",
        files={
            "file": (
                "transactions.csv",
                b"date,amount,merchant,category\n2026-03-01,-12.50,Starbucks,Coffee\n",
                "text/csv",
            )
        },
    )

    assert response.status_code == 200
    assert response.json()[0]["suggested_category"] == "Coffee"


def test_openai_usage_endpoint() -> None:
    metrics.openai_request_count = 3
    response = client.get("/openai-usage")
    assert response.status_code == 200
    assert response.json()["openai_request_count"] == 3


def test_import_categorization_memory_api(tmp_path: Path, monkeypatch) -> None:
    memory_path = tmp_path / "categorization_memory.json"
    monkeypatch.setattr("bookkeeping_app.api.MEMORY_PATH", memory_path)

    csv_bytes = (
        b"merchant,amount,category,notes\n"
        b"Electrify America,-7.00,Electric Vehicle Charging,EV charging merchant\n"
    )

    response = client.post(
        "/categorization-memory/import",
        files={"file": ("memory.csv", csv_bytes, "text/csv")},
    )

    assert response.status_code == 200
    assert response.json() == {"imported": 1, "skipped": 0}


def test_get_categorization_memory_api(tmp_path: Path, monkeypatch) -> None:
    memory_path = tmp_path / "categorization_memory.json"
    monkeypatch.setattr("bookkeeping_app.api.MEMORY_PATH", memory_path)

    client.post(
        "/categorization-memory/import",
        files={
            "file": (
                "memory.csv",
                (
                    b"merchant,amount,category,notes\n"
                    b"Whole Foods,-42.19,Groceries,Trusted historical label\n"
                ),
                "text/csv",
            )
        },
    )

    response = client.get("/categorization-memory")

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["merchant"] == "Whole Foods"
    assert response.json()[0]["corrected_category"] == "Groceries"
    assert response.json()[0]["original_category"] is None
