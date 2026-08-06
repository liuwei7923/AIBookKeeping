from decimal import Decimal
from uuid import UUID

from bookkeeping_app.domain_contracts import (
    TransactionDirection,
    TransactionIdentityQuality,
)
from bookkeeping_app.ingestion import build_canonical_transactions

USER_ID = UUID("550e8400-e29b-41d4-a716-446655440000")


def test_build_canonical_transactions_maps_a_complete_row() -> None:
    rows = [
        {
            "date": "2026-03-02",
            "merchant": "Whole Foods",
            "statement": "WHOLEFDS SAN JOSE",
            "amount": -42.19,
            "category": "Groceries",
        }
    ]

    transactions = build_canonical_transactions(rows, user_id=USER_ID)

    assert len(transactions) == 1
    canonical = transactions[0]
    assert canonical.source.user_id == USER_ID
    assert canonical.source.transaction_id
    assert canonical.source.merchant == "Whole Foods"
    assert canonical.source.statement == "WHOLEFDS SAN JOSE"
    assert canonical.source.original_category == "Groceries"
    assert canonical.source.amount == Decimal("-42.19")
    assert canonical.normalized_merchant == "whole foods"
    assert canonical.normalized_statement == "wholefds san jose"
    assert canonical.direction == TransactionDirection.DEBIT
    assert canonical.identity_quality == TransactionIdentityQuality.COMPLETE


def test_build_canonical_transactions_preserves_order_and_assigns_unique_ids() -> None:
    rows = [
        {"merchant": "Whole Foods", "statement": "WHOLEFDS", "amount": -10, "date": None, "category": None},
        {"merchant": "Starbucks", "statement": "STARBUCKS", "amount": -5, "date": None, "category": None},
        {"merchant": "Costco", "statement": "COSTCO", "amount": -100, "date": None, "category": None},
    ]

    transactions = build_canonical_transactions(rows, user_id=USER_ID)

    assert [t.normalized_merchant for t in transactions] == [
        "whole foods",
        "starbucks",
        "costco",
    ]
    ids = [t.source.transaction_id for t in transactions]
    assert len(ids) == len(set(ids))


def test_build_canonical_transactions_fingerprint_is_deterministic() -> None:
    row = {
        "date": "2026-03-02",
        "merchant": "Whole Foods",
        "statement": "WHOLEFDS SAN JOSE",
        "amount": -42.19,
        "category": "Groceries",
    }

    first = build_canonical_transactions([row], user_id=USER_ID)[0]
    second = build_canonical_transactions([row], user_id=USER_ID)[0]

    assert first.fingerprint is not None
    assert first.fingerprint == second.fingerprint


def test_build_canonical_transactions_fingerprint_distinguishes_different_transactions() -> None:
    base_row = {
        "date": "2026-03-02",
        "merchant": "Whole Foods",
        "statement": "WHOLEFDS SAN JOSE",
        "amount": -42.19,
        "category": "Groceries",
    }
    different_amount_row = {**base_row, "amount": -99.99}

    base = build_canonical_transactions([base_row], user_id=USER_ID)[0]
    different = build_canonical_transactions([different_amount_row], user_id=USER_ID)[0]

    assert base.fingerprint != different.fingerprint


def test_build_canonical_transactions_marks_missing_merchant_insufficient() -> None:
    row = {
        "date": "2026-03-02",
        "merchant": None,
        "statement": "UNKNOWN CHARGE",
        "amount": -10.0,
        "category": None,
    }

    canonical = build_canonical_transactions([row], user_id=USER_ID)[0]

    assert canonical.identity_quality == TransactionIdentityQuality.INSUFFICIENT
    assert canonical.fingerprint is None


def test_build_canonical_transactions_marks_missing_statement_partial() -> None:
    row = {
        "date": "2026-03-02",
        "merchant": "Whole Foods",
        "statement": None,
        "amount": -10.0,
        "category": None,
    }

    canonical = build_canonical_transactions([row], user_id=USER_ID)[0]

    assert canonical.identity_quality == TransactionIdentityQuality.PARTIAL
    assert canonical.fingerprint is None
