"""Shared deterministic behavior used by local Memory Store adapters."""

from collections.abc import Iterable, Sequence

from bookkeeping_app.domain_contracts import CanonicalTransaction
from bookkeeping_app.memory.contracts import (
    FingerprintConflictPolicy,
    MemoryListQuery,
    MemoryPage,
    MemoryQuery,
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
) -> tuple[CanonicalTransaction, ...]:
    matches = (
        transaction
        for transaction in transactions
        if transaction.source.user_id == query.user_id
        and transaction.normalized_merchant == query.normalized_merchant
        and transaction.direction is query.direction
        and transaction.trusted_categorization is not None
    )
    return tuple(sorted(matches, key=_transaction_sort_key))


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
