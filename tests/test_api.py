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
