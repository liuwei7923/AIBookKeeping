"""Converts parsed transaction rows into canonical transactions."""

from decimal import Decimal
from hashlib import sha256
from typing import Any

from pydantic import BaseModel, ConfigDict

from bookkeeping_app.domain_contracts import (
    CanonicalTransaction,
    SourceTransaction,
    TransactionDirection,
    TransactionIdentityQuality,
    UserId,
)
from bookkeeping_app.normalization import normalize_merchant


class IngestionResult(BaseModel):
    """The outcome of converting parsed rows into canonical transactions."""

    model_config = ConfigDict(extra="forbid")

    canonical_transactions: list[CanonicalTransaction]
    incomplete_sources: list[SourceTransaction]


def _identity_quality(
    *,
    date: str | None,
    amount: Decimal | None,
) -> TransactionIdentityQuality:
    if date is None or amount is None:
        return TransactionIdentityQuality.PARTIAL
    return TransactionIdentityQuality.COMPLETE


def _build_fingerprint(
    *,
    date: str | None,
    normalized_merchant: str | None,
    normalized_statement: str | None,
    amount: Decimal | None,
) -> str:
    fingerprint_input = f"{date}|{normalized_merchant}|{normalized_statement}|{amount}"
    return f"sha256:{sha256(fingerprint_input.encode()).hexdigest()}"


def build_canonical_transactions(
    rows: list[dict[str, Any]],
    *,
    user_id: UserId,
) -> IngestionResult:
    canonical_transactions: list[CanonicalTransaction] = []
    incomplete_sources: list[SourceTransaction] = []

    for row in rows:
        amount = row.get("amount")
        decimal_amount = Decimal(str(amount)) if amount is not None else None
        merchant = row.get("merchant")
        description = row.get("description") or row.get("statement") or merchant
        source = SourceTransaction(
            user_id=user_id,
            date=row.get("date"),
            post_date=row.get("post_date") or row.get("posted_date"),
            merchant=merchant,
            description=description,
            statement=description,
            amount=decimal_amount,
            original_category=row.get("category") or row.get("original_category"),
            transaction_type=row.get("type") or row.get("transaction_type"),
            memo=row.get("memo"),
        )
        normalized_merchant = normalize_merchant(source.merchant)
        normalized_statement = normalize_merchant(
            source.statement or source.description
        )

        if not normalized_merchant and not normalized_statement:
            incomplete_sources.append(source)
            continue

        canonical_transactions.append(
            CanonicalTransaction(
                source=source,
                normalized_merchant=normalized_merchant,
                normalized_statement=normalized_statement or normalized_merchant,
                direction=(
                    TransactionDirection.CREDIT
                    if amount is not None and amount >= 0
                    else TransactionDirection.DEBIT
                ),
                identity_quality=_identity_quality(
                    date=source.date,
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

    return IngestionResult(
        canonical_transactions=canonical_transactions,
        incomplete_sources=incomplete_sources,
    )
