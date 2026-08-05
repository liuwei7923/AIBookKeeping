from decimal import Decimal
from uuid import UUID

from fastapi.testclient import TestClient

from bookkeeping_app.api import app
from bookkeeping_app.domain_contracts import (
    CanonicalTransaction,
    SourceTransaction,
    TransactionDirection,
    TransactionIdentityQuality,
    TrustedCategorization,
    TrustedCategorizationSource,
)
from bookkeeping_app.memory import InMemoryMemoryStore
from bookkeeping_app.metrics import metrics

TEST_USER_ID = UUID("8a802680-06be-4815-986b-58b88392acfc")
client = TestClient(app, headers={"X-User-Id": str(TEST_USER_ID)})


def test_openapi_exposes_only_the_supported_routes() -> None:
    paths = app.openapi()["paths"]

    assert {
        (method.upper(), path) for path, methods in paths.items() for method in methods
    } == {
        ("GET", "/health"),
        ("GET", "/admin/openai-usage"),
        ("GET", "/categorization-memory"),
        ("POST", "/transactions"),
    }


def test_health_endpoint() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_transactions_uses_review_service(monkeypatch) -> None:
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

    monkeypatch.setattr(
        "bookkeeping_app.routes.transactions.review_transaction_categories",
        fake_review,
    )

    response = client.post(
        "/transactions",
        files={
            "file": (
                "transactions.csv",
                b"date,amount,merchant,category\n2026-03-01,-12.50,Starbucks,Coffee\n",
                "text/csv",
            )
        },
    )

    assert response.status_code == 200
    assert response.headers["X-User-Id"] == str(TEST_USER_ID)
    assert response.json()[0]["suggested_category"] == "Coffee"


def test_explicit_request_user_overrides_the_client_default(monkeypatch) -> None:
    jia_user_id = "0c050ed3-d41b-468c-9c29-e9e6da905c04"
    monkeypatch.setattr(
        "bookkeeping_app.routes.transactions.review_transaction_categories",
        lambda transactions: transactions,
    )

    response = client.post(
        "/transactions",
        headers={"X-User-Id": jia_user_id},
        files={"file": ("transactions.csv", b"merchant\nCoffee\n", "text/csv")},
    )

    assert response.status_code == 200
    assert response.headers["X-User-Id"] == jia_user_id


def test_development_default_runs_user_api_without_header(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEV_USER_ID", str(TEST_USER_ID))
    monkeypatch.setattr(
        "bookkeeping_app.routes.transactions.review_transaction_categories",
        lambda transactions: transactions,
    )
    client_without_user_header = TestClient(app)

    response = client_without_user_header.post(
        "/transactions",
        files={"file": ("transactions.csv", b"merchant\nCoffee\n", "text/csv")},
    )

    assert response.status_code == 200
    assert response.headers["X-User-Id"] == str(TEST_USER_ID)


def test_categorization_memory_is_isolated_by_request_user(
    monkeypatch,
) -> None:
    jia_user_id = UUID("0c050ed3-d41b-468c-9c29-e9e6da905c04")
    monkeypatch.setattr(
        "bookkeeping_app.routes.categorization_memory.MEMORY_STORE",
        InMemoryMemoryStore(
            [
                memory_transaction(
                    user_id=TEST_USER_ID,
                    transaction_number=1,
                    merchant="Wei Market",
                    category="Groceries",
                ),
                memory_transaction(
                    user_id=jia_user_id,
                    transaction_number=2,
                    merchant="Jia Cafe",
                    category="Coffee",
                ),
            ]
        ),
    )

    wei_response = client.get("/categorization-memory")
    jia_response = client.get(
        "/categorization-memory", headers={"X-User-Id": str(jia_user_id)}
    )

    assert [item["merchant"] for item in wei_response.json()] == ["Wei Market"]
    assert [item["merchant"] for item in jia_response.json()] == ["Jia Cafe"]


def test_admin_openai_usage_endpoint() -> None:
    metrics.openai_request_count = 3
    response = client.get("/admin/openai-usage")
    assert response.status_code == 200
    assert response.json()["openai_request_count"] == 3


def test_get_categorization_memory_uses_public_field_names(monkeypatch) -> None:
    transaction = memory_transaction(
        user_id=TEST_USER_ID,
        transaction_number=1,
        merchant="Whole Foods",
        category="Groceries",
    )
    monkeypatch.setattr(
        "bookkeeping_app.routes.categorization_memory.MEMORY_STORE",
        InMemoryMemoryStore([transaction]),
    )

    response = client.get("/categorization-memory")

    assert response.status_code == 200
    assert response.json() == [
        {
            "date": "2026-03-01",
            "merchant": "Whole Foods",
            "statement": "WHOLEFDS 123",
            "amount": -42.19,
            "direction": "debit",
            "original_category": None,
            "category": "Groceries",
            "notes": "Reviewed by user.",
        }
    ]


def test_legacy_routes_are_removed() -> None:
    assert client.get("/openai-usage").status_code == 404
    assert client.post("/categorization-memory/import").status_code == 404
    assert client.post("/categorization-memory").status_code == 405
    assert client.post("/extract-transactions").status_code == 404
    assert client.post("/extract-transactions-csv").status_code == 404
    assert client.post("/recategorize-transactions-csv").status_code == 404


def memory_transaction(
    *,
    user_id: UUID,
    transaction_number: int,
    merchant: str,
    category: str,
) -> CanonicalTransaction:
    normalized_merchant = merchant.lower()
    return CanonicalTransaction(
        source=SourceTransaction(
            user_id=user_id,
            transaction_id=UUID(int=transaction_number),
            date="2026-03-01",
            merchant=merchant,
            statement="WHOLEFDS 123",
            amount=Decimal("-42.19"),
        ),
        normalized_merchant=normalized_merchant,
        normalized_statement="wholefds 123",
        direction=TransactionDirection.DEBIT,
        identity_quality=TransactionIdentityQuality.COMPLETE,
        fingerprint=f"sha256:{transaction_number:064x}",
        trusted_categorization=TrustedCategorization(
            category=category,
            source=TrustedCategorizationSource.MANUAL_CLASSIFICATION,
            note="Reviewed by user.",
        ),
    )
