import pytest
from pydantic import ValidationError

from bookkeeping_app.domain_contracts import (
    CanonicalTransaction,
    CategorizationDecision,
    DecisionType,
    ManualCategorization,
    SourceTransaction,
    TransactionDirection,
    TransactionIdentityQuality,
)


def test_source_transaction_preserves_unprocessed_source_values() -> None:
    transaction = SourceTransaction(
        transaction_id="txn-1",
        date="2026-03-24",
        merchant=" ELECTRIFY AMERICA ",
        statement="ELECTRIFY AMERICA 65RESTON VA",
        amount=-7.0,
        original_category="Gas",
    )

    assert transaction.transaction_id == "txn-1"
    assert transaction.merchant == " ELECTRIFY AMERICA "
    assert transaction.statement == "ELECTRIFY AMERICA 65RESTON VA"
    assert transaction.original_category == "Gas"


def test_source_transaction_rejects_blank_identifier() -> None:
    with pytest.raises(ValidationError):
        SourceTransaction(transaction_id=" ")


def test_manual_categorization_records_a_trusted_user_category() -> None:
    categorization = ManualCategorization(
        category="Electric Vehicle Charging",
        note="Confirmed from charging receipt.",
    )

    assert categorization.category == "Electric Vehicle Charging"
    assert categorization.note == "Confirmed from charging receipt."


def test_manual_categorization_rejects_blank_category() -> None:
    with pytest.raises(ValidationError):
        ManualCategorization(category=" ")


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
        CategorizationDecision(
            **(fields | {"suggested_category": "Transportation"})
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
        CategorizationDecision(
            **(fields | {"suggested_category": "Transportation"})
        )


def test_canonical_transaction_keeps_source_identity_and_both_categorizations() -> None:
    source = SourceTransaction(
        transaction_id="txn-1",
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
    manual_categorization = ManualCategorization(
        category="Vehicle Charging",
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
        manual_categorization=manual_categorization,
    )

    assert transaction.source.merchant == " ELECTRIFY AMERICA "
    assert transaction.normalized_merchant == "electrify america"
    assert transaction.fingerprint == "sha256:abc123"
    assert transaction.ai_categorization == ai_decision
    assert transaction.manual_categorization == manual_categorization
