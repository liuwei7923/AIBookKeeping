"""Converts parsed transaction rows into canonical transactions."""

from decimal import Decimal
from hashlib import sha256
from typing import Any

from bookkeeping_app.domain_contracts import (
    CanonicalTransaction,
    SourceTransaction,
    TransactionDirection,
    TransactionIdentityQuality,
    UserId,
)
from bookkeeping_app.normalization import normalize_merchant, normalize_statement


def _identity_quality(
    *,
    normalized_merchant: str | None,
    normalized_statement: str | None,
    amount: Decimal | None,
) -> TransactionIdentityQuality:
    if not normalized_merchant:
        return TransactionIdentityQuality.INSUFFICIENT

    if not normalized_statement or amount is None:
        return TransactionIdentityQuality.PARTIAL

    return TransactionIdentityQuality.COMPLETE


def _build_fingerprint(
    *,
    date: str | None,
    normalized_merchant: str | None,
    normalized_statement: str | None,
    amount: Decimal | None,
) -> str | None:
    if not normalized_merchant or not normalized_statement or amount is None:
        return None

    fingerprint_input = f"{date}|{normalized_merchant}|{normalized_statement}|{amount}"
    return f"sha256:{sha256(fingerprint_input.encode()).hexdigest()}"


def build_canonical_transactions(
    rows: list[dict[str, Any]],
    *,
    user_id: UserId,
) -> list[CanonicalTransaction]:
    canonical_transactions: list[CanonicalTransaction] = []

    for index, row in enumerate(rows):
        amount = row.get("amount")
        decimal_amount = Decimal(str(amount)) if amount is not None else None
        source = SourceTransaction(
            user_id=user_id,
            transaction_id=f"txn-{index + 1}",
            date=row.get("date"),
            merchant=row.get("merchant"),
            statement=row.get("statement"),
            amount=decimal_amount,
            original_category=row.get("category"),
        )
        normalized_merchant = normalize_merchant(source.merchant)
        normalized_statement = normalize_statement(source.statement)

        canonical_transactions.append(
            CanonicalTransaction(
                source=source,
                normalized_merchant=normalized_merchant,
                normalized_statement=normalized_statement,
                direction=(
                    TransactionDirection.CREDIT
                    if amount is not None and amount >= 0
                    else TransactionDirection.DEBIT
                ),
                identity_quality=_identity_quality(
                    normalized_merchant=normalized_merchant,
                    normalized_statement=normalized_statement,
                    amount=decimal_amount,
                ),
                fingerprint=_build_fingerprint(
                    date=source.date,
                    normalized_merchant=normalized_merchant,
                    normalized_statement=normalized_statement,
                    amount=decimal_amount,
                ),
            )
        )

    return canonical_transactions
