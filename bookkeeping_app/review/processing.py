"""Bridge current CSV review output into canonical review items."""

from decimal import Decimal
from hashlib import sha256
from typing import Any
from uuid import uuid4

from bookkeeping_app.domain_contracts import (
    AICategorization,
    CanonicalTransaction,
    CategorizationType,
    EvidenceCondition,
    ReviewRequirement,
    SourceTransaction,
    TransactionDirection,
    TransactionIdentityQuality,
    TransactionItem,
    UserId,
)
from bookkeeping_app.review.session import EphemeralReviewSession


def enqueue_review_results(
    *,
    user_id: UserId,
    source_rows: list[dict[str, Any]],
    reviewed_rows: list[dict[str, Any]],
    review_session: EphemeralReviewSession,
) -> list[dict[str, Any]]:
    """Persist review-required AI results and add their IDs to the API response."""
    response_rows: list[dict[str, Any]] = []
    transaction_items: list[TransactionItem] = []
    for index, reviewed in enumerate(reviewed_rows):
        source = source_rows[index] if index < len(source_rows) else reviewed
        item = _review_item(user_id, source, reviewed, index)
        transaction_items.append(item)
        response_rows.append(reviewed | {"transaction_id": str(item.transaction_id)})
    review_session.add(transaction_items)
    return response_rows


def enqueue_canonical_review_items(
    transactions: list[CanonicalTransaction], review_session: EphemeralReviewSession
) -> tuple[TransactionItem, ...]:
    """Queue only canonical decisions that require human review."""
    items = []
    for transaction in transactions:
        decision = transaction.ai_categorization
        if decision is None:
            continue
        items.append(
            TransactionItem(
                transaction=transaction,
                review_requirement=ReviewRequirement.NEEDS_REVIEW,
                evidence_condition=(
                    EvidenceCondition.SUPPORTING
                    if decision.supporting_memory_ids
                    else EvidenceCondition.INSUFFICIENT
                ),
            )
        )
    review_session.add(items)
    return tuple(items)


def _review_item(
    user_id: UserId,
    source_row: dict[str, Any],
    reviewed_row: dict[str, Any],
    index: int,
) -> TransactionItem:
    suggested = reviewed_row.get("suggested_category")
    proposed = reviewed_row.get("proposed_category")
    categorization_type = (
        CategorizationType.PROPOSED
        if proposed
        else CategorizationType.SUGGESTED
        if suggested
        else CategorizationType.NOT_AVAILABLE
    )
    reason = reviewed_row.get("reason") or "No categorization reason was provided."
    decision = AICategorization(
        decision_id=f"review-{uuid4()}",
        categorization_type=categorization_type,
        category=proposed or suggested,
        reason=reason,
    )
    amount_value = source_row.get("amount")
    amount = Decimal(str(amount_value)) if amount_value is not None else None
    merchant = source_row.get("merchant")
    normalized_merchant = merchant.strip().lower() if merchant else None
    statement = source_row.get("statement") or merchant
    normalized_statement = statement.strip().lower() if statement else None
    fingerprint_payload = "|".join(
        str(value or "")
        for value in (source_row.get("date"), statement, amount_value, index)
    )
    transaction = CanonicalTransaction(
        source=SourceTransaction(
            user_id=user_id,
            date=source_row.get("date"),
            merchant=merchant,
            statement=statement,
            amount=amount,
            original_category=source_row.get("category"),
        ),
        normalized_merchant=normalized_merchant,
        normalized_statement=normalized_statement,
        direction=(
            TransactionDirection.DEBIT
            if amount is not None and amount < 0
            else TransactionDirection.CREDIT
        ),
        identity_quality=(
            TransactionIdentityQuality.COMPLETE
            if source_row.get("date") is not None
            and merchant is not None
            and amount is not None
            else TransactionIdentityQuality.PARTIAL
        ),
        fingerprint=f"sha256:{sha256(fingerprint_payload.encode()).hexdigest()}",
        ai_categorization=decision,
    )
    return TransactionItem(
        transaction=transaction,
        review_requirement=ReviewRequirement.NEEDS_REVIEW,
        evidence_condition=_evidence_condition(reviewed_row, decision),
    )


def _evidence_condition(
    reviewed_row: dict[str, Any], decision: AICategorization
) -> EvidenceCondition:
    explicit = reviewed_row.get("evidence_condition")
    if explicit in {condition.value for condition in EvidenceCondition}:
        return EvidenceCondition(explicit)
    if decision.supporting_memory_ids:
        return EvidenceCondition.SUPPORTING
    return EvidenceCondition.INSUFFICIENT
