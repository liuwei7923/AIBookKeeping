from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from bookkeeping_app.domain_contracts import (
    CanonicalTransaction,
    SourceTransaction,
    TransactionDirection,
    TransactionIdentityQuality,
    TrustedCategorization,
    TrustedCategorizationSource,
)
from bookkeeping_app.memory import (
    FileMemoryStore,
    FingerprintConflictPolicy,
    InMemoryMemoryStore,
    MemoryListQuery,
    MemoryQuery,
    MemoryStore,
    MemoryWriteStatus,
    RecordTrustedCommand,
    SqlMemoryStore,
)

USER_A = UUID("550e8400-e29b-41d4-a716-446655440000")
USER_B = UUID("550e8400-e29b-41d4-a716-446655440001")


@pytest.fixture(params=["in_memory", "file"])
def memory_store(request: pytest.FixtureRequest, tmp_path: Path) -> MemoryStore:
    if request.param == "in_memory":
        return InMemoryMemoryStore()
    return FileMemoryStore(tmp_path / "categorization_memory.json")


def trusted_transaction(
    transaction_number: int,
    *,
    user_id: UUID = USER_A,
    fingerprint: str | None = None,
    merchant: str = "whole foods",
    direction: TransactionDirection = TransactionDirection.DEBIT,
    category: str = "Groceries",
) -> CanonicalTransaction:
    transaction_id = UUID(int=transaction_number)
    return CanonicalTransaction(
        source=SourceTransaction(
            user_id=user_id,
            transaction_id=transaction_id,
            date="2026-03-01",
            merchant="Whole Foods",
            statement="WHOLEFDS 123",
            amount=Decimal("-42.19"),
        ),
        normalized_merchant=merchant,
        normalized_statement="wholefds 123",
        direction=direction,
        identity_quality=TransactionIdentityQuality.COMPLETE,
        fingerprint=fingerprint or f"sha256:{transaction_number:064x}",
        trusted_categorization=TrustedCategorization(
            category=category,
            source=TrustedCategorizationSource.MANUAL_CLASSIFICATION,
        ),
    )


def test_adapters_satisfy_memory_store_interface(tmp_path: Path) -> None:
    assert isinstance(InMemoryMemoryStore(), MemoryStore)
    assert isinstance(FileMemoryStore(tmp_path / "memory.json"), MemoryStore)
    assert isinstance(SqlMemoryStore("sqlite:///memory.db"), MemoryStore)


def test_record_and_list_trusted_transaction(memory_store: MemoryStore) -> None:
    transaction = trusted_transaction(1)

    result = memory_store.record_trusted(
        [RecordTrustedCommand(transaction=transaction)]
    )
    page = memory_store.list_for_user(MemoryListQuery(user_id=USER_A))

    assert result.count(MemoryWriteStatus.CREATED) == 1
    assert page.transactions == (transaction,)
    assert page.next_cursor is None


def test_record_rejects_transaction_without_trusted_category(
    memory_store: MemoryStore,
) -> None:
    transaction = trusted_transaction(1).model_copy(
        update={"trusted_categorization": None}
    )

    result = memory_store.record_trusted(
        [RecordTrustedCommand(transaction=transaction)]
    )

    assert result.items[0].status is MemoryWriteStatus.REJECTED
    assert (
        memory_store.list_for_user(MemoryListQuery(user_id=USER_A)).transactions == ()
    )


def test_same_fingerprint_and_category_is_duplicate(
    memory_store: MemoryStore,
) -> None:
    first = trusted_transaction(1, fingerprint="sha256:same")
    duplicate = trusted_transaction(2, fingerprint="sha256:same")
    memory_store.record_trusted([RecordTrustedCommand(transaction=first)])

    result = memory_store.record_trusted([RecordTrustedCommand(transaction=duplicate)])

    assert result.items[0].status is MemoryWriteStatus.DUPLICATE
    assert result.items[0].conflicting_transaction_ids == (first.source.transaction_id,)


def test_conflicting_category_is_rejected_by_default(
    memory_store: MemoryStore,
) -> None:
    first = trusted_transaction(1, fingerprint="sha256:same")
    conflict = trusted_transaction(
        2,
        fingerprint="sha256:same",
        category="Shopping",
    )
    memory_store.record_trusted([RecordTrustedCommand(transaction=first)])

    result = memory_store.record_trusted([RecordTrustedCommand(transaction=conflict)])

    assert result.items[0].status is MemoryWriteStatus.CONFLICT
    assert memory_store.list_for_user(MemoryListQuery(user_id=USER_A)).transactions == (
        first,
    )


def test_explicit_conflict_policy_replaces_trusted_transaction(
    memory_store: MemoryStore,
) -> None:
    first = trusted_transaction(1, fingerprint="sha256:same")
    replacement = trusted_transaction(
        2,
        fingerprint="sha256:same",
        category="Shopping",
    )
    memory_store.record_trusted([RecordTrustedCommand(transaction=first)])

    result = memory_store.record_trusted(
        [
            RecordTrustedCommand(
                transaction=replacement,
                conflict_policy=FingerprintConflictPolicy.REPLACE_TRUSTED_CATEGORY,
                override_reason="User corrected imported history.",
            )
        ]
    )

    assert result.items[0].status is MemoryWriteStatus.REPLACED
    assert result.items[0].replaced_transaction_id == first.source.transaction_id
    assert memory_store.list_for_user(MemoryListQuery(user_id=USER_A)).transactions == (
        replacement,
    )


def test_replacement_policy_requires_reason() -> None:
    with pytest.raises(ValidationError, match="requires override_reason"):
        RecordTrustedCommand(
            transaction=trusted_transaction(1),
            conflict_policy=FingerprintConflictPolicy.REPLACE_TRUSTED_CATEGORY,
        )


def test_find_relevant_isolates_user_merchant_and_direction(
    memory_store: MemoryStore,
) -> None:
    matching = trusted_transaction(1)
    other_user = trusted_transaction(2, user_id=USER_B)
    other_merchant = trusted_transaction(3, merchant="target")
    other_direction = trusted_transaction(
        4,
        direction=TransactionDirection.CREDIT,
    )
    memory_store.record_trusted(
        [
            RecordTrustedCommand(transaction=transaction)
            for transaction in (
                matching,
                other_user,
                other_merchant,
                other_direction,
            )
        ]
    )

    result = memory_store.find_relevant(
        MemoryQuery(
            user_id=USER_A,
            normalized_merchant="whole foods",
            direction=TransactionDirection.DEBIT,
        )
    )

    assert result == (matching,)


def test_list_for_user_uses_stable_cursor_pagination(
    memory_store: MemoryStore,
) -> None:
    transactions = [trusted_transaction(number) for number in (3, 1, 2)]
    memory_store.record_trusted(
        [RecordTrustedCommand(transaction=item) for item in transactions]
    )

    first_page = memory_store.list_for_user(MemoryListQuery(user_id=USER_A, limit=2))
    second_page = memory_store.list_for_user(
        MemoryListQuery(user_id=USER_A, limit=2, cursor=first_page.next_cursor)
    )

    assert [item.source.transaction_id.int for item in first_page.transactions] == [
        1,
        2,
    ]
    assert first_page.next_cursor == str(UUID(int=2))
    assert [item.source.transaction_id.int for item in second_page.transactions] == [3]
    assert second_page.next_cursor is None


def test_file_store_round_trips_decimal_and_enums(tmp_path: Path) -> None:
    path = tmp_path / "memory.json"
    transaction = trusted_transaction(1)
    FileMemoryStore(path).record_trusted(
        [RecordTrustedCommand(transaction=transaction)]
    )

    restored = FileMemoryStore(path).list_for_user(MemoryListQuery(user_id=USER_A))

    assert restored.transactions == (transaction,)
    assert isinstance(restored.transactions[0].source.amount, Decimal)
    assert restored.transactions[0].direction is TransactionDirection.DEBIT


def test_sql_memory_store_is_explicitly_deferred() -> None:
    store = SqlMemoryStore("sqlite:///memory.db")

    with pytest.raises(NotImplementedError, match="not implemented"):
        store.list_for_user(MemoryListQuery(user_id=USER_A))
