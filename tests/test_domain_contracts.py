from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from bookkeeping_app.domain_contracts import (
    CanonicalTransaction,
    CategorizationDecision,
    DecisionType,
    SourceTransaction,
    TransactionDirection,
    TransactionIdentityQuality,
    TrustedCategorization,
    TrustedCategorizationSource,
    User,
)

USER_ID = UUID("550e8400-e29b-41d4-a716-446655440000")
TRANSACTION_ID = UUID("660e8400-e29b-41d4-a716-446655440000")


def test_user_gets_a_generated_uuid() -> None:
    user = User()

    assert isinstance(user.user_id, UUID)
    assert user.display_name is None


def test_user_accepts_an_existing_uuid_and_display_name() -> None:
    user = User(user_id=USER_ID, display_name="  Wei Liu  ")

    assert user.user_id == USER_ID
    assert user.display_name == "Wei Liu"


def test_user_rejects_blank_display_name() -> None:
    with pytest.raises(ValidationError):
        User(display_name=" ")


def test_source_transaction_preserves_unprocessed_source_values() -> None:
    transaction = SourceTransaction(
        user_id=USER_ID,
        transaction_id=TRANSACTION_ID,
        date="2026-03-24",
        merchant=" ELECTRIFY AMERICA ",
        statement="ELECTRIFY AMERICA 65RESTON VA",
        amount=Decimal("0.1000000000000000001"),
        original_category="Gas",
    )

    assert transaction.user_id == USER_ID
    assert transaction.transaction_id == TRANSACTION_ID
    assert transaction.merchant == " ELECTRIFY AMERICA "
    assert transaction.statement == "ELECTRIFY AMERICA 65RESTON VA"
    assert transaction.amount == Decimal("0.1000000000000000001")
    assert transaction.original_category == "Gas"


def test_source_transaction_generates_identifier_when_omitted() -> None:
    transaction = SourceTransaction(user_id=USER_ID)

    assert isinstance(transaction.transaction_id, UUID)


def test_source_transaction_rejects_invalid_identifier() -> None:
    with pytest.raises(ValidationError):
        SourceTransaction(user_id=USER_ID, transaction_id=" ")


def test_source_transaction_requires_user_id() -> None:
    with pytest.raises(ValidationError):
        SourceTransaction(transaction_id=TRANSACTION_ID)


@pytest.mark.parametrize("user_id", ["", "user-1", "not-a-uuid"])
def test_source_transaction_rejects_invalid_user_id(user_id: str) -> None:
    with pytest.raises(ValidationError):
        SourceTransaction(user_id=user_id, transaction_id=TRANSACTION_ID)


def test_source_transaction_parses_uuid_string() -> None:
    transaction = SourceTransaction(
        user_id=str(USER_ID), transaction_id=str(TRANSACTION_ID)
    )

    assert transaction.user_id == USER_ID
    assert transaction.transaction_id == TRANSACTION_ID


def test_trusted_categorization_records_category_source_and_note() -> None:
    categorization = TrustedCategorization(
        category="Electric Vehicle Charging",
        source=TrustedCategorizationSource.MANUAL_CLASSIFICATION,
        note="Confirmed from charging receipt.",
    )

    assert categorization.category == "Electric Vehicle Charging"
    assert categorization.source is TrustedCategorizationSource.MANUAL_CLASSIFICATION
    assert categorization.note == "Confirmed from charging receipt."


def test_trusted_categorization_rejects_blank_category() -> None:
    with pytest.raises(ValidationError):
        TrustedCategorization(
            category=" ",
            source=TrustedCategorizationSource.MANUAL_CLASSIFICATION,
        )


def test_ai_suggestion_records_category_reason_and_supporting_memory() -> None:
    decision = CategorizationDecision(
        decision_id="decision-1",
        decision_type=DecisionType.AI_SUGGESTION,
        suggested_category="Electric Vehicle Charging",
        reason="The merchant and statement describe an EV charging session.",
        supporting_memory_ids=["memory-1"],
    )

    assert decision.suggested_category == "Electric Vehicle Charging"
    assert decision.proposed_category is None
    assert decision.supporting_memory_ids == ["memory-1"]


def test_ai_new_category_proposal_uses_only_proposed_category() -> None:
    fields = {
        "decision_id": "decision-2",
        "decision_type": DecisionType.AI_PROPOSED_NEW_CATEGORY,
        "proposed_category": "Electric Vehicle Charging",
        "reason": "No existing category describes an EV charging session.",
    }

    decision = CategorizationDecision(**fields)

    assert decision.proposed_category == "Electric Vehicle Charging"
    assert decision.suggested_category is None

    with pytest.raises(ValidationError):
        CategorizationDecision(**(fields | {"suggested_category": "Transportation"}))


@pytest.mark.parametrize(
    ("decision_type", "category_field"),
    [
        (DecisionType.AI_SUGGESTION, "suggested_category"),
        (DecisionType.AI_PROPOSED_NEW_CATEGORY, "proposed_category"),
    ],
)
def test_ai_category_values_must_not_be_blank(
    decision_type: DecisionType,
    category_field: str,
) -> None:
    with pytest.raises(ValidationError):
        CategorizationDecision(
            decision_id="decision-blank-category",
            decision_type=decision_type,
            reason="AI returned an unusable category.",
            **{category_field: " "},
        )


def test_unresolved_ai_decision_contains_no_category() -> None:
    fields = {
        "decision_id": "decision-3",
        "decision_type": DecisionType.UNRESOLVED,
        "reason": "The available evidence is conflicting.",
        "supporting_memory_ids": ["memory-2", "memory-3"],
    }

    decision = CategorizationDecision(**fields)

    assert decision.suggested_category is None
    assert decision.proposed_category is None

    with pytest.raises(ValidationError):
        CategorizationDecision(**(fields | {"suggested_category": "Transportation"}))


def test_ai_decision_rejects_blank_supporting_memory_id() -> None:
    with pytest.raises(ValidationError):
        CategorizationDecision(
            decision_id="decision-4",
            decision_type=DecisionType.UNRESOLVED,
            reason="The available evidence is conflicting.",
            supporting_memory_ids=["memory-1", " "],
        )


def test_canonical_transaction_keeps_source_identity_and_both_categorizations() -> None:
    source = SourceTransaction(
        user_id=USER_ID,
        transaction_id=TRANSACTION_ID,
        merchant=" ELECTRIFY AMERICA ",
        statement="ELECTRIFY AMERICA 65RESTON VA",
        amount=-7.0,
        original_category="Gas",
    )
    ai_decision = CategorizationDecision(
        decision_id="decision-1",
        decision_type=DecisionType.AI_SUGGESTION,
        suggested_category="Electric Vehicle Charging",
        reason="The transaction describes an EV charging session.",
    )
    trusted_categorization = TrustedCategorization(
        category="Vehicle Charging",
        source=TrustedCategorizationSource.CORRECTED_AI_SUGGESTION,
        note="User corrected the category name.",
    )

    transaction = CanonicalTransaction(
        source=source,
        normalized_merchant="electrify america",
        normalized_statement="electrify america 65reston va",
        direction=TransactionDirection.DEBIT,
        identity_quality=TransactionIdentityQuality.COMPLETE,
        fingerprint="sha256:abc123",
        ai_categorization=ai_decision,
        trusted_categorization=trusted_categorization,
    )

    assert transaction.source.user_id == USER_ID
    assert transaction.source.merchant == " ELECTRIFY AMERICA "
    assert transaction.normalized_merchant == "electrify america"
    assert transaction.fingerprint == "sha256:abc123"
    assert transaction.ai_categorization == ai_decision
    assert transaction.trusted_categorization == trusted_categorization


def test_canonical_transaction_requires_fingerprint() -> None:
    source = SourceTransaction(user_id=USER_ID, transaction_id=TRANSACTION_ID)

    with pytest.raises(ValidationError):
        CanonicalTransaction(
            source=source,
            direction=TransactionDirection.DEBIT,
            identity_quality=TransactionIdentityQuality.PARTIAL,
        )
