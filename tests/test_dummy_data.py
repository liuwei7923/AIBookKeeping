import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from bookkeeping_app.domain_contracts import (
    CategorizationType,
    SourceTransaction,
)
from scripts.dummy_data import (
    DummyTransactionDataset,
    generate_dummy_transactions,
)

USER_ID = UUID("550e8400-e29b-41d4-a716-446655440000")


def test_dummy_dataset_is_reproducible_for_count_and_seed() -> None:
    first = generate_dummy_transactions(user_id=USER_ID, count=5, seed=42)
    second = generate_dummy_transactions(user_id=USER_ID, count=5, seed=42)

    assert len(first.source_transactions) == 5
    assert len(first.canonical_transactions) == 5
    assert first.user_id == USER_ID
    assert first.model_dump_json() == second.model_dump_json()


def test_dummy_dataset_changes_with_seed() -> None:
    first = generate_dummy_transactions(user_id=USER_ID, count=5, seed=42)
    second = generate_dummy_transactions(user_id=USER_ID, count=5, seed=43)

    assert first.model_dump_json() != second.model_dump_json()


def test_dummy_dataset_round_trips_through_json() -> None:
    dataset = generate_dummy_transactions(user_id=USER_ID, count=8, seed=42)

    restored = DummyTransactionDataset.model_validate_json(dataset.model_dump_json())

    assert restored == dataset
    sources_by_id = {
        source.transaction_id: source for source in restored.source_transactions
    }
    assert all(
        canonical.source == sources_by_id[canonical.source.transaction_id]
        for canonical in restored.canonical_transactions
    )
    assert all(
        isinstance(source.amount, Decimal) for source in restored.source_transactions
    )
    assert all(source.user_id == USER_ID for source in restored.source_transactions)
    assert all(
        canonical.source.user_id == USER_ID
        for canonical in restored.canonical_transactions
    )
    assert all(
        "user_id" not in canonical.model_dump()
        for canonical in restored.canonical_transactions
    )


@pytest.mark.parametrize("count", [0, -1])
def test_dummy_dataset_rejects_non_positive_count(count: int) -> None:
    with pytest.raises(ValueError, match="count must be positive"):
        generate_dummy_transactions(user_id=USER_ID, count=count, seed=42)


def test_dummy_dataset_rejects_transaction_owned_by_another_user() -> None:
    other_user_id = UUID("550e8400-e29b-41d4-a716-446655440001")

    with pytest.raises(ValidationError, match="must match dataset user_id"):
        DummyTransactionDataset(
            user_id=USER_ID,
            source_transactions=[SourceTransaction(user_id=other_user_id)],
            canonical_transactions=[],
        )


def test_dummy_dataset_covers_manual_judgment_ui_states() -> None:
    dataset = generate_dummy_transactions(
        user_id=USER_ID,
        count=8,
        seed=42,
    )
    transactions = dataset.canonical_transactions

    assert any(
        item.ai_categorization is None and item.trusted_categorization is None
        for item in transactions
    )
    assert any(
        item.ai_categorization is not None
        and item.ai_categorization.categorization_type is CategorizationType.SUGGESTED
        and item.trusted_categorization is None
        for item in transactions
    )
    assert any(
        item.ai_categorization is not None
        and item.ai_categorization.categorization_type is CategorizationType.PROPOSED
        for item in transactions
    )
    assert any(
        item.ai_categorization is not None
        and item.ai_categorization.categorization_type
        is CategorizationType.NOT_AVAILABLE
        for item in transactions
    )
    assert any(
        item.ai_categorization is not None
        and item.trusted_categorization is not None
        and item.ai_categorization.category == item.trusted_categorization.category
        for item in transactions
    )
    assert any(
        item.ai_categorization is not None
        and item.ai_categorization.category is not None
        and item.trusted_categorization is not None
        and item.ai_categorization.category != item.trusted_categorization.category
        for item in transactions
    )
    assert any(
        item.ai_categorization is None and item.trusted_categorization is not None
        for item in transactions
    )
    assert all(item.fingerprint for item in transactions)
    assert any(
        source.merchant is None and source.statement is None
        for source in dataset.source_transactions
    )
    assert len(dataset.source_transactions) == 8
    assert len(dataset.canonical_transactions) == 7


def test_dummy_data_cli_writes_a_valid_dataset(tmp_path: Path) -> None:
    output_path = tmp_path / "nested" / "transactions.json"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.dummy_data",
            "--count",
            "8",
            "--user-id",
            str(USER_ID),
            "--seed",
            "123",
            "--output",
            str(output_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert output_path.exists()
    dataset = DummyTransactionDataset.model_validate_json(output_path.read_text())
    assert len(dataset.source_transactions) == 8
    assert len(dataset.canonical_transactions) == 7
    assert {item.user_id for item in dataset.source_transactions} == {USER_ID}
