"""Integration of CSV ingestion and confirmed merchant persistence.

The user-facing review workflow is not implemented; this test exercises only
the existing ingestion and storage boundaries, not an HTTP review API.
"""

from uuid import UUID

from bookkeeping_app.ingestion import build_canonical_transactions
from bookkeeping_app.merchant_store import FileMerchantStore
from bookkeeping_app.parsers import parse_csv_transactions

USER_A = UUID("550e8400-e29b-41d4-a716-446655440000")
USER_B = UUID("550e8400-e29b-41d4-a716-446655440001")
CSV = (
    "Transaction Date,Post Date,Description,Category,Type,Amount,Memo\n"
    "03/02/2026,03/03/2026,POS COFFEE SHOP 123,Food,Sale,-12.50,\n"
    "03/02/2026,03/03/2026,POS BOOK STORE 456,Shopping,Sale,-18.00,\n"
)


def test_import_confirm_correct_and_reuse_merchants_across_users(tmp_path):
    path = tmp_path / "merchant_confirmations.json"
    transactions = build_canonical_transactions(
        parse_csv_transactions(CSV), user_id=USER_A
    ).canonical_transactions
    coffee, books = (item.source.source_description for item in transactions)
    assert coffee is not None and books is not None
    assert all(item.normalized_merchant is None for item in transactions)

    store = FileMerchantStore(path)
    assert store.lookup(USER_A, coffee).status == "not_found"

    # These calls model explicit user actions; no review API exists yet.
    store.confirm(USER_A, coffee, "Coffee Shop")
    store.confirm(USER_A, coffee, "Northstar Cafe", correction=True)
    store.confirm(USER_A, books, "Book Store")

    reopened = FileMerchantStore(path)
    assert reopened.lookup(USER_A, coffee).merchant == "Northstar Cafe"
    assert reopened.lookup(USER_A, books).merchant == "Book Store"
    history = reopened.history(USER_A)
    assert [(item.confirmed_merchant, item.active) for item in history] == [
        ("Coffee Shop", False),
        ("Northstar Cafe", True),
        ("Book Store", True),
    ]

    new_batch = build_canonical_transactions(
        parse_csv_transactions(CSV), user_id=USER_A
    ).canonical_transactions
    assert (
        reopened.lookup(USER_A, new_batch[0].source.source_description).merchant
        == "Northstar Cafe"
    )
    assert reopened.lookup(USER_B, coffee).status == "not_found"
    assert reopened.history(USER_B) == ()
