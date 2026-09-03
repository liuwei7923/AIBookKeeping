"""Shared deterministic behavior used by local Memory Store adapters."""

from collections.abc import Iterable, Sequence
from datetime import date
from decimal import Decimal
from difflib import SequenceMatcher

from bookkeeping_app.domain_contracts import (
    CanonicalTransaction,
    TransactionIdentityQuality,
)
from bookkeeping_app.memory.contracts import (
    CategoryCount,
    FingerprintConflictPolicy,
    MemoryEvidence,
    MemoryListQuery,
    MemoryPage,
    MemoryQuery,
    MemoryQueryResult,
    MemoryWriteItemResult,
    MemoryWriteResult,
    MemoryWriteStatus,
    RecordTrustedCommand,
)


def record_commands(
    transactions: Sequence[CanonicalTransaction],
    commands: Sequence[RecordTrustedCommand],
) -> tuple[list[CanonicalTransaction], MemoryWriteResult]:
    """Apply a batch to a copy and return the replacement state plus outcomes."""

    updated = list(transactions)
    results: list[MemoryWriteItemResult] = []

    for command in commands:
        transaction = command.transaction
        if transaction.identity_quality is TransactionIdentityQuality.PARTIAL:
            results.append(
                MemoryWriteItemResult(
                    transaction_id=transaction.source.transaction_id,
                    status=MemoryWriteStatus.REJECTED,
                    reason="transaction identity is insufficient for categorization memory",
                )
            )
            continue

        trusted = transaction.trusted_categorization
        if trusted is None:
            results.append(
                MemoryWriteItemResult(
                    transaction_id=transaction.source.transaction_id,
                    status=MemoryWriteStatus.REJECTED,
                    reason="transaction has no trusted categorization",
                )
            )
            continue

        matches = [
            existing
            for existing in updated
            if existing.source.user_id == transaction.source.user_id
            and existing.fingerprint == transaction.fingerprint
        ]
        if not matches:
            updated.append(transaction)
            results.append(
                MemoryWriteItemResult(
                    transaction_id=transaction.source.transaction_id,
                    status=MemoryWriteStatus.CREATED,
                )
            )
            continue

        matching_categories = {
            existing.trusted_categorization.category
            for existing in matches
            if existing.trusted_categorization is not None
        }
        conflicting_ids = tuple(existing.source.transaction_id for existing in matches)
        if trusted.category in matching_categories:
            results.append(
                MemoryWriteItemResult(
                    transaction_id=transaction.source.transaction_id,
                    status=MemoryWriteStatus.DUPLICATE,
                    conflicting_transaction_ids=conflicting_ids,
                )
            )
            continue

        if command.conflict_policy is FingerprintConflictPolicy.REJECT:
            results.append(
                MemoryWriteItemResult(
                    transaction_id=transaction.source.transaction_id,
                    status=MemoryWriteStatus.CONFLICT,
                    conflicting_transaction_ids=conflicting_ids,
                    reason="fingerprint already has a different trusted category",
                )
            )
            continue

        matched_ids = {existing.source.transaction_id for existing in matches}
        updated = [
            existing
            for existing in updated
            if existing.source.transaction_id not in matched_ids
        ]
        updated.append(transaction)
        results.append(
            MemoryWriteItemResult(
                transaction_id=transaction.source.transaction_id,
                status=MemoryWriteStatus.REPLACED,
                conflicting_transaction_ids=conflicting_ids,
                replaced_transaction_id=conflicting_ids[0],
                reason=command.override_reason,
            )
        )

    return updated, MemoryWriteResult(items=tuple(results))


def find_relevant_transactions(
    transactions: Iterable[CanonicalTransaction],
    query: MemoryQuery,
) -> MemoryQueryResult:
    matches = [
        transaction
        for transaction in transactions
        if transaction.source.user_id == query.user_id
        and transaction.normalized_merchant == query.normalized_merchant
        and transaction.direction is query.direction
        and transaction.trusted_categorization is not None
    ]

    category_counts = _category_counts(matches)
    ranked = sorted(matches, key=lambda transaction: _rank_key(transaction, query))
    candidates = tuple(_to_evidence(transaction) for transaction in ranked[: query.limit])

    return MemoryQueryResult(candidates=candidates, category_counts=category_counts)


def _category_counts(
    matches: Sequence[CanonicalTransaction],
) -> tuple[CategoryCount, ...]:
    counts: dict[str, int] = {}
    for transaction in matches:
        trusted = transaction.trusted_categorization
        assert trusted is not None
        counts[trusted.category] = counts.get(trusted.category, 0) + 1
    return tuple(
        CategoryCount(category=category, count=count)
        for category, count in sorted(
            counts.items(), key=lambda item: (-item[1], item[0])
        )
    )


def _rank_key(
    transaction: CanonicalTransaction,
    query: MemoryQuery,
) -> tuple[float, int, tuple[int, Decimal], tuple[int, int], str]:
    similarity = _statement_similarity(
        query.normalized_statement, transaction.normalized_statement
    )
    category_agrees = (
        query.original_category is not None
        and transaction.source.original_category == query.original_category
    )
    return (
        -similarity,
        0 if category_agrees else 1,
        _amount_distance_key(query.amount, transaction.source.amount),
        _recency_key(transaction.source.date),
        str(transaction.source.transaction_id),
    )


def _statement_similarity(
    query_statement: str | None,
    candidate_statement: str | None,
) -> float:
    if query_statement is None or candidate_statement is None:
        return 0.0
    return SequenceMatcher(None, query_statement, candidate_statement).ratio()


def _amount_distance_key(
    query_amount: Decimal | None,
    candidate_amount: Decimal | None,
) -> tuple[int, Decimal]:
    if query_amount is None or candidate_amount is None:
        return (1, Decimal(0))
    return (0, abs(query_amount - candidate_amount))


def _recency_key(date_text: str | None) -> tuple[int, int]:
    parsed = _parse_date(date_text)
    if parsed is None:
        return (1, 0)
    return (0, -parsed.toordinal())


def _parse_date(date_text: str | None) -> date | None:
    if date_text is None:
        return None
    try:
        return date.fromisoformat(date_text)
    except ValueError:
        return None


def _to_evidence(transaction: CanonicalTransaction) -> MemoryEvidence:
    trusted = transaction.trusted_categorization
    assert trusted is not None
    return MemoryEvidence(
        evidence_id=transaction.source.transaction_id,
        normalized_statement=transaction.normalized_statement,
        date=transaction.source.date,
        amount=transaction.source.amount,
        original_category=transaction.source.original_category,
        category=trusted.category,
    )


def list_transactions(
    transactions: Iterable[CanonicalTransaction],
    query: MemoryListQuery,
) -> MemoryPage:
    owned = sorted(
        (
            transaction
            for transaction in transactions
            if transaction.source.user_id == query.user_id
            and transaction.trusted_categorization is not None
        ),
        key=_transaction_sort_key,
    )
    if query.cursor is not None:
        owned = [
            transaction
            for transaction in owned
            if str(transaction.source.transaction_id) > query.cursor
        ]

    page_items = owned[: query.limit]
    next_cursor = None
    if len(owned) > query.limit:
        next_cursor = str(page_items[-1].source.transaction_id)
    return MemoryPage(transactions=tuple(page_items), next_cursor=next_cursor)


def _transaction_sort_key(transaction: CanonicalTransaction) -> str:
    return str(transaction.source.transaction_id)
