"""Generate deterministic transaction fixtures for manual judgment UI work.

Run from the repository root::

    python -m scripts.dummy_data --user-id 550e8400-e29b-41d4-a716-446655440000 --count 24 --seed 42 --output data/dummy_transactions.json

The output is one ``DummyTransactionDataset`` JSON object containing
``source_transactions`` and successfully constructed ``canonical_transactions``
arrays. Each canonical transaction embeds its corresponding source transaction;
identity-insufficient sources have no canonical counterpart.

The same count and seed always produce the same merchant, amount, date, and
direction values. Scenario placement is independent of the seed: every eight
records cycle through unreviewed, AI suggestion, proposed category, unresolved,
accepted AI, corrected AI, manual-only, and incomplete-input states.

Call ``generate_dummy_transactions(user_id=..., count=..., seed=...)`` directly
when models are more useful than a file. Generation is local, performs no
filesystem writes, and does not call OpenAI; only the command-line adapter
writes JSON.
"""

import argparse
from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from random import Random
from uuid import uuid5

from pydantic import BaseModel, ConfigDict, model_validator

from bookkeeping_app.domain_contracts import (
    AICategorization,
    CanonicalTransaction,
    CategorizationType,
    SourceTransaction,
    TransactionDirection,
    TransactionIdentityQuality,
    TrustedCategorization,
    TrustedCategorizationSource,
    UserId,
)

MERCHANTS = (
    (
        " ELECTRIFY AMERICA ",
        "electrify america",
        "ELECTRIFY AMERICA RESTON VA",
        "Auto",
        "Electric Vehicle Charging",
    ),
    (
        "Whole Foods Market",
        "whole foods market",
        "WHOLEFDS MKT 10234",
        "Shopping",
        "Groceries",
    ),
    (
        "STARBUCKS  Store 042",
        "starbucks store 042",
        "STARBUCKS 042 SEATTLE",
        "Dining",
        "Coffee Shops",
    ),
    (
        "United Airlines",
        "united airlines",
        "UNITED 016238491",
        "Travel",
        "Air Travel",
    ),
    (
        "Adobe Systems",
        "adobe systems",
        "ADOBE CREATIVE CLOUD",
        "Software",
        "Software Subscriptions",
    ),
)


class DummyTransactionDataset(BaseModel):
    """Source transactions and their successful canonical results."""

    model_config = ConfigDict(extra="forbid")

    user_id: UserId
    source_transactions: list[SourceTransaction]
    canonical_transactions: list[CanonicalTransaction]

    @model_validator(mode="after")
    def transactions_belong_to_dataset_user(self) -> "DummyTransactionDataset":
        source_transactions = [
            *self.source_transactions,
            *(canonical.source for canonical in self.canonical_transactions),
        ]
        if any(source.user_id != self.user_id for source in source_transactions):
            raise ValueError("all transactions must match dataset user_id")
        return self


def _build_categorizations(
    index: int,
    suggested_category: str,
) -> tuple[AICategorization | None, TrustedCategorization | None]:
    scenario = index % 8
    decision_id = f"decision-{index + 1:04d}"
    memory_ids = [f"memory-{index + 1:04d}"]

    if scenario == 1:
        return (
            AICategorization(
                decision_id=decision_id,
                categorization_type=CategorizationType.SUGGESTED,
                category=suggested_category,
                reason="AI matched the merchant to a known category.",
                supporting_memory_ids=memory_ids,
            ),
            None,
        )
    if scenario == 2:
        return (
            AICategorization(
                decision_id=decision_id,
                categorization_type=CategorizationType.PROPOSED,
                category="Specialized Merchant Expense",
                reason="AI found no suitable category in the known examples.",
            ),
            None,
        )
    if scenario == 3:
        return (
            AICategorization(
                decision_id=decision_id,
                categorization_type=CategorizationType.NOT_AVAILABLE,
                reason="The available categorization evidence conflicts.",
                supporting_memory_ids=memory_ids,
            ),
            None,
        )
    if scenario == 4:
        return (
            AICategorization(
                decision_id=decision_id,
                categorization_type=CategorizationType.SUGGESTED,
                category=suggested_category,
                reason="AI matched the merchant to a known category.",
                supporting_memory_ids=memory_ids,
            ),
            TrustedCategorization(
                category=suggested_category,
                source=TrustedCategorizationSource.CONFIRMED_AI_SUGGESTION,
                note="User accepted the AI suggestion.",
            ),
        )
    if scenario == 5:
        return (
            AICategorization(
                decision_id=decision_id,
                categorization_type=CategorizationType.SUGGESTED,
                category=suggested_category,
                reason="AI matched the merchant to a known category.",
                supporting_memory_ids=memory_ids,
            ),
            TrustedCategorization(
                category="Business Expense",
                source=TrustedCategorizationSource.CORRECTED_AI_SUGGESTION,
                note="User corrected the AI suggestion.",
            ),
        )
    if scenario == 6:
        return None, TrustedCategorization(
            category=suggested_category,
            source=TrustedCategorizationSource.MANUAL_CLASSIFICATION,
            note="User categorized this transaction without AI assistance.",
        )
    return None, None


def generate_dummy_transactions(
    *,
    user_id: UserId,
    count: int = 50,
    seed: int = 42,
) -> DummyTransactionDataset:
    """Generate a deterministic, validated transaction dataset."""

    if count <= 0:
        raise ValueError("count must be positive")

    rng = Random(seed)
    source_transactions: list[SourceTransaction] = []
    canonical_transactions: list[CanonicalTransaction] = []

    for index in range(count):
        (
            merchant,
            normalized_merchant,
            statement,
            original_category,
            suggested_category,
        ) = rng.choice(MERCHANTS)
        scenario = index % 8
        is_incomplete = scenario == 7
        amount = Decimal(rng.randint(199, 25_000)) / Decimal("100")
        if rng.choice((True, False)):
            amount = -amount
        transaction_id = uuid5(user_id, f"dummy:{seed}:{index}")
        transaction_date = date(2026, 1, 1) + timedelta(days=rng.randint(0, 180))
        source = SourceTransaction(
            user_id=user_id,
            transaction_id=transaction_id,
            date=transaction_date.isoformat(),
            merchant=None if is_incomplete else merchant,
            statement=None if is_incomplete else statement,
            amount=amount,
            original_category=None if is_incomplete else original_category,
        )
        source_transactions.append(source)
        if is_incomplete:
            continue

        ai_categorization, trusted_categorization = _build_categorizations(
            index, suggested_category
        )
        fingerprint_input = f"{user_id}|{source.date}|{normalized_merchant}|{statement.lower()}|{amount}"
        fingerprint = f"sha256:{sha256(fingerprint_input.encode()).hexdigest()}"
        canonical = CanonicalTransaction(
            source=source,
            normalized_merchant=normalized_merchant,
            normalized_statement=statement.lower(),
            direction=(
                TransactionDirection.CREDIT
                if amount >= 0
                else TransactionDirection.DEBIT
            ),
            identity_quality=TransactionIdentityQuality.COMPLETE,
            fingerprint=fingerprint,
            ai_categorization=ai_categorization,
            trusted_categorization=trusted_categorization,
        )
        canonical_transactions.append(canonical)

    return DummyTransactionDataset(
        user_id=user_id,
        source_transactions=source_transactions,
        canonical_transactions=canonical_transactions,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Write a generated dataset to a JSON file."""

    parser = argparse.ArgumentParser(
        description="Generate deterministic source and canonical transactions."
    )
    parser.add_argument("--count", type=int, default=50)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--user-id", type=UserId, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    dataset = generate_dummy_transactions(
        user_id=args.user_id,
        count=args.count,
        seed=args.seed,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(dataset.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
