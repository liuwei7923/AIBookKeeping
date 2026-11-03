from decimal import Decimal
from uuid import UUID

import pytest

from bookkeeping_app.domain_contracts import (
    MerchantIdentificationStatus,
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
            "amount": -42.19,
            "category": "Groceries",
        }
    ]

    result = build_canonical_transactions(rows, user_id=USER_ID)

    assert result.incomplete_sources == []
    assert len(result.canonical_transactions) == 1
    canonical = result.canonical_transactions[0]
    assert canonical.source.user_id == USER_ID
    assert canonical.source.merchant == "Whole Foods"
    assert canonical.source.original_category == "Groceries"
    assert canonical.source.amount == Decimal("-42.19")
    assert canonical.normalized_merchant == "whole foods"
    assert canonical.direction == TransactionDirection.DEBIT
    assert canonical.identity_quality == TransactionIdentityQuality.COMPLETE


def test_build_canonical_transactions_marks_positive_amount_as_credit() -> None:
    row = {
        "date": "2026-03-02",
        "merchant": "Employer Payroll",
        "amount": 1500.00,
        "category": None,
    }

    canonical = build_canonical_transactions(
        [row], user_id=USER_ID
    ).canonical_transactions[0]

    assert canonical.direction == TransactionDirection.CREDIT


def test_build_canonical_transactions_preserves_order() -> None:
    rows = [
        {"merchant": "Whole Foods", "amount": -10, "date": None, "category": None},
        {"merchant": "Starbucks", "amount": -5, "date": None, "category": None},
        {"merchant": "Costco", "amount": -100, "date": None, "category": None},
    ]

    result = build_canonical_transactions(rows, user_id=USER_ID)

    assert [t.normalized_merchant for t in result.canonical_transactions] == [
        "whole foods",
        "starbucks",
        "costco",
    ]


def test_build_canonical_transactions_assigns_unique_ids_within_a_batch() -> None:
    rows = [
        {
            "merchant": "Whole Foods",
            "amount": -10,
            "date": "2026-03-02",
            "category": None,
        },
        {
            "merchant": "Whole Foods",
            "amount": -10,
            "date": "2026-03-02",
            "category": None,
        },
        {
            "merchant": "Whole Foods",
            "amount": -10,
            "date": "2026-03-02",
            "category": None,
        },
    ]

    result = build_canonical_transactions(rows, user_id=USER_ID)

    transaction_ids = [t.source.transaction_id for t in result.canonical_transactions]
    assert len(set(transaction_ids)) == len(transaction_ids)


def test_build_canonical_transactions_fingerprint_is_deterministic() -> None:
    row = {
        "date": "2026-03-02",
        "merchant": "Whole Foods",
        "amount": -42.19,
        "category": "Groceries",
    }

    first = build_canonical_transactions([row], user_id=USER_ID).canonical_transactions[
        0
    ]
    second = build_canonical_transactions(
        [row], user_id=USER_ID
    ).canonical_transactions[0]

    assert first.fingerprint == second.fingerprint


def test_build_canonical_transactions_fingerprint_distinguishes_different_transactions() -> (
    None
):
    base_row = {
        "date": "2026-03-02",
        "merchant": "Whole Foods",
        "amount": -42.19,
        "category": "Groceries",
    }
    different_amount_row = {**base_row, "amount": -99.99}

    base = build_canonical_transactions(
        [base_row], user_id=USER_ID
    ).canonical_transactions[0]
    different = build_canonical_transactions(
        [different_amount_row], user_id=USER_ID
    ).canonical_transactions[0]

    assert base.fingerprint != different.fingerprint


def test_build_canonical_transactions_marks_missing_merchant_as_incomplete() -> None:
    row = {
        "date": "2026-03-02",
        "merchant": None,
        "amount": -10.0,
        "category": None,
    }

    result = build_canonical_transactions([row], user_id=USER_ID)

    assert result.canonical_transactions == []
    assert len(result.incomplete_sources) == 1
    assert result.incomplete_sources[0].merchant is None


def test_build_canonical_transactions_marks_missing_date_or_amount_as_partial() -> None:
    row = {
        "date": None,
        "merchant": "Whole Foods",
        "amount": -10.0,
        "category": None,
    }

    canonical = build_canonical_transactions(
        [row], user_id=USER_ID
    ).canonical_transactions[0]

    assert canonical.identity_quality == TransactionIdentityQuality.PARTIAL
    assert canonical.fingerprint


def test_build_canonical_transactions_bridges_statement_from_merchant() -> None:
    row = {
        "date": "2026-03-02",
        "merchant": "Whole Foods",
        "amount": -42.19,
        "category": "Groceries",
    }

    canonical = build_canonical_transactions(
        [row], user_id=USER_ID
    ).canonical_transactions[0]

    assert canonical.source.statement == "Whole Foods"
    assert canonical.normalized_statement == "whole foods"


def test_description_only_is_preserved_without_becoming_merchant() -> None:
    from bookkeeping_app.parsers import parse_csv_transactions

    row = parse_csv_transactions(
        "Transaction Date,Post Date,Description,Type,Amount,Memo\n"
        "03/02/2026,03/03/2026,POS MARKET #12,Sale,-1.20,synthetic\n"
    )[0]
    canonical = build_canonical_transactions(
        [row], user_id=USER_ID
    ).canonical_transactions[0]
    assert canonical.source.source_description == "POS MARKET #12"
    assert canonical.source.merchant is None
    assert canonical.normalized_merchant is None
    assert canonical.source.merchant_status is MerchantIdentificationStatus.UNKNOWN
    assert canonical.source.post_date == "03/03/2026"
    assert canonical.source.transaction_type == "Sale"
    assert canonical.source.memo == "synthetic"


def test_explicit_merchant_and_confirmation_have_distinct_semantics() -> None:
    source_provided = build_canonical_transactions(
        [{"merchant": "Acme", "description": "POS ACME 1", "amount": -2}],
        user_id=USER_ID,
    ).canonical_transactions[0]
    assert (
        source_provided.source.merchant_status
        is MerchantIdentificationStatus.SOURCE_PROVIDED
    )
    with pytest.raises(ValueError, match="confirmed_merchant"):
        build_canonical_transactions(
            [{"description": "POS ACME 1", "confirmed_merchant": "Acme", "amount": -2}],
            user_id=USER_ID,
        )


def test_source_statement_is_preserved_separately_from_merchant() -> None:
    canonical = build_canonical_transactions(
        [{"merchant": "Acme", "description": "POS ACME 1", "amount": -2}],
        user_id=USER_ID,
    ).canonical_transactions[0]

    assert canonical.source.statement == "POS ACME 1"
    assert canonical.source.merchant == "Acme"


def test_fingerprint_uses_source_not_reviewed_merchant() -> None:
    source = {"description": "POS ACME 1", "amount": -2, "date": "2026-03-01"}
    transaction = build_canonical_transactions(
        [source], user_id=USER_ID
    ).canonical_transactions[0]
    # Applying a review changes derived state, not the source identity.
    reviewed = transaction.model_copy(update={"normalized_merchant": "acme"})
    assert reviewed.fingerprint == transaction.fingerprint
    assert (
        build_canonical_transactions([source], user_id=USER_ID)
        .canonical_transactions[0]
        .fingerprint
        == reviewed.fingerprint
    )


def test_merchant_only_fingerprint_retains_existing_formula() -> None:
    from hashlib import sha256

    row = {"merchant": "Acme", "amount": -2.0, "date": "2026-03-01"}
    transaction = build_canonical_transactions(
        [row], user_id=USER_ID
    ).canonical_transactions[0]
    legacy_fingerprint = sha256(b"2026-03-01|acme|-2.0").hexdigest()

    assert transaction.fingerprint == f"sha256:{legacy_fingerprint}"


def test_merchant_only_row_does_not_claim_source_description() -> None:
    canonical = build_canonical_transactions(
        [{"merchant": "Acme", "amount": -2}], user_id=USER_ID
    ).canonical_transactions[0]
    assert canonical.source.merchant == "Acme"
    assert canonical.source.source_description is None


def test_description_changes_transaction_fingerprint_when_merchant_missing() -> None:
    first, second = build_canonical_transactions(
        [
            {"description": "POS CAFE ONE", "date": "2026-03-01", "amount": -2},
            {"description": "POS CAFE TWO", "date": "2026-03-01", "amount": -2},
        ],
        user_id=USER_ID,
    ).canonical_transactions
    assert first.normalized_merchant is None
    assert first.fingerprint != second.fingerprint
