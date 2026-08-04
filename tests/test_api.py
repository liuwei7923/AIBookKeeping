from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient

from bookkeeping_app.api import app
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
        ("POST", "/categorization-memory"),
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
    tmp_path: Path, monkeypatch
) -> None:
    memory_path = tmp_path / "categorization_memory.json"
    jia_user_id = "0c050ed3-d41b-468c-9c29-e9e6da905c04"
    monkeypatch.setattr(
        "bookkeeping_app.routes.categorization_memory.MEMORY_PATH",
        memory_path,
    )

    client.post(
        "/categorization-memory",
        files={"file": ("wei.csv", b"merchant,category\nWei Market,Groceries\n")},
    )
    client.post(
        "/categorization-memory",
        headers={"X-User-Id": jia_user_id},
        files={"file": ("jia.csv", b"merchant,category\nJia Cafe,Coffee\n")},
    )

    wei_response = client.get("/categorization-memory")
    jia_response = client.get(
        "/categorization-memory", headers={"X-User-Id": jia_user_id}
    )

    assert [item["merchant"] for item in wei_response.json()] == ["Wei Market"]
    assert [item["merchant"] for item in jia_response.json()] == ["Jia Cafe"]


def test_admin_openai_usage_endpoint() -> None:
    metrics.openai_request_count = 3
    response = client.get("/admin/openai-usage")
    assert response.status_code == 200
    assert response.json()["openai_request_count"] == 3


def test_import_categorization_memory_api(tmp_path: Path, monkeypatch) -> None:
    memory_path = tmp_path / "categorization_memory.json"
    monkeypatch.setattr(
        "bookkeeping_app.routes.categorization_memory.MEMORY_PATH",
        memory_path,
    )

    csv_bytes = (
        b"merchant,amount,category,statement,notes\n"
        b"Electrify America,-7.00,Electric Vehicle Charging,ELECTRIFY AMERICA 65RESTON VA,EV charging merchant\n"
    )

    response = client.post(
        "/categorization-memory",
        files={"file": ("memory.csv", csv_bytes, "text/csv")},
    )

    assert response.status_code == 200
    assert response.json() == {"imported": 1, "skipped": 0}
    stored = memory_path.read_text(encoding="utf-8")
    assert "ELECTRIFY AMERICA 65RESTON VA" in stored


def test_get_categorization_memory_api(tmp_path: Path, monkeypatch) -> None:
    memory_path = tmp_path / "categorization_memory.json"
    monkeypatch.setattr(
        "bookkeeping_app.routes.categorization_memory.MEMORY_PATH",
        memory_path,
    )

    client.post(
        "/categorization-memory",
        files={
            "file": (
                "memory.csv",
                (
                    b"merchant,amount,category,statement,notes\n"
                    b"Whole Foods,-42.19,Groceries,WHOLEFDS SAN JOSE,Trusted historical label\n"
                ),
                "text/csv",
            )
        },
    )

    response = client.get("/categorization-memory")

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["merchant"] == "Whole Foods"
    assert response.json()[0]["statement"] == "WHOLEFDS SAN JOSE"
    assert response.json()[0]["category"] == "Groceries"
    assert response.json()[0]["original_category"] is None
    assert "normalized_merchant" not in response.json()[0]
    assert "id" not in response.json()[0]


def test_get_categorization_memory_uses_public_field_names(
    tmp_path: Path, monkeypatch
) -> None:
    memory_path = tmp_path / "categorization_memory.json"
    monkeypatch.setattr(
        "bookkeeping_app.routes.categorization_memory.MEMORY_PATH",
        memory_path,
    )

    client.post(
        "/categorization-memory",
        files={
            "file": (
                "memory.csv",
                (
                    b"merchant,amount,corrected_category,original statement\n"
                    b"Electrify America,-7.00,Electric Vehicle Charging,ELECTRIFY AMERICA 65RESTON VA\n"
                ),
                "text/csv",
            )
        },
    )

    response = client.get("/categorization-memory")

    assert response.status_code == 200
    assert response.json() == [
        {
            "date": None,
            "merchant": "Electrify America",
            "statement": "ELECTRIFY AMERICA 65RESTON VA",
            "amount": -7.0,
            "direction": "debit",
            "original_category": None,
            "category": "Electric Vehicle Charging",
            "notes": None,
        }
    ]


def test_legacy_routes_are_removed() -> None:
    assert client.get("/openai-usage").status_code == 404
    assert client.post("/categorization-memory/import").status_code == 404
    assert client.post("/extract-transactions").status_code == 404
    assert client.post("/extract-transactions-csv").status_code == 404
    assert client.post("/recategorize-transactions-csv").status_code == 404
