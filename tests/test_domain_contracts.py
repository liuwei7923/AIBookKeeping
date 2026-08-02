import pytest
from pydantic import ValidationError

from bookkeeping_app.domain_contracts import (
    BatchStatus,
    CanonicalTransaction,
    CategorizationDecision,
    DecisionConfidence,
    DecisionType,
    RecategorizationBatch,
    RecategorizationResult,
    TransactionDirection,
    TransactionIdentityQuality,
)


def test_canonical_transaction_preserves_source_and_normalized_identity() -> None:
    transaction = CanonicalTransaction(
        transaction_id="txn-1",
        date="2026-03-24",
        merchant=" ELECTRIFY AMERICA ",
        statement="ELECTRIFY AMERICA 65RESTON VA",
        amount=-7.0,
        original_category="Gas",
        normalized_merchant="electrify america",
        normalized_statement="electrify america 65reston va",
        direction=TransactionDirection.DEBIT,
        identity_quality=TransactionIdentityQuality.COMPLETE,
        fingerprint="sha256:abc123",
    )

    assert transaction.transaction_id == "txn-1"
    assert transaction.merchant == " ELECTRIFY AMERICA "
    assert transaction.normalized_merchant == "electrify america"
    assert transaction.direction is TransactionDirection.DEBIT
    assert transaction.identity_quality is TransactionIdentityQuality.COMPLETE


def test_domain_contracts_reject_blank_identifiers() -> None:
    with pytest.raises(ValidationError):
        CanonicalTransaction(
            transaction_id=" ",
            direction=TransactionDirection.UNKNOWN,
            identity_quality=TransactionIdentityQuality.INSUFFICIENT,
        )

    with pytest.raises(ValidationError):
        CategorizationDecision(
            transaction_id=" ",
            decision_type=DecisionType.UNRESOLVED,
            needs_review=True,
            reason="Transaction identity is insufficient.",
        )

    with pytest.raises(ValidationError):
        RecategorizationBatch(
            batch_id=" ",
            status=BatchStatus.COMPLETED,
            results=[],
            openai_request_count=0,
        )


def test_exact_statement_match_contains_only_an_accepted_category() -> None:
    decision = CategorizationDecision(
        transaction_id="txn-1",
        decision_type=DecisionType.EXACT_STATEMENT_MEMORY_MATCH,
        accepted_category="Electric Vehicle Charging",
        needs_review=False,
        confidence=DecisionConfidence.HIGH,
        reason="Matched a trusted transaction statement.",
        supporting_memory_ids=["memory-1"],
    )

    assert decision.accepted_category == "Electric Vehicle Charging"
    assert decision.suggested_category is None
    assert decision.proposed_category is None
    assert decision.needs_review is False


@pytest.mark.parametrize(
    ("decision_type", "category_field"),
    [
        (DecisionType.AI_SUGGESTION_WITH_RELEVANT_MEMORY, "suggested_category"),
        (DecisionType.AI_SUGGESTION_WITHOUT_RELEVANT_MEMORY, "suggested_category"),
        (DecisionType.AI_PROPOSED_NEW_CATEGORY, "proposed_category"),
    ],
)
def test_every_ai_decision_uses_its_distinct_category_field_and_needs_review(
    decision_type: DecisionType,
    category_field: str,
) -> None:
    fields = {
        "transaction_id": "txn-1",
        "decision_type": decision_type,
        category_field: "Electric Vehicle Charging",
        "needs_review": True,
        "confidence": DecisionConfidence.MEDIUM,
        "reason": "AI reviewed the available evidence.",
        "supporting_memory_ids": (
            ["memory-1"]
            if decision_type is DecisionType.AI_SUGGESTION_WITH_RELEVANT_MEMORY
            else []
        ),
    }

    decision = CategorizationDecision(**fields)

    assert getattr(decision, category_field) == "Electric Vehicle Charging"
    assert decision.accepted_category is None

    with pytest.raises(ValidationError):
        CategorizationDecision(**(fields | {"needs_review": False}))


def test_ai_memory_context_type_agrees_with_supporting_memory() -> None:
    common_fields = {
        "transaction_id": "txn-1",
        "suggested_category": "Electric Vehicle Charging",
        "needs_review": True,
        "reason": "AI reviewed the available evidence.",
    }

    with pytest.raises(ValidationError):
        CategorizationDecision(
            decision_type=DecisionType.AI_SUGGESTION_WITH_RELEVANT_MEMORY,
            supporting_memory_ids=[],
            **common_fields,
        )

    with pytest.raises(ValidationError):
        CategorizationDecision(
            decision_type=DecisionType.AI_SUGGESTION_WITHOUT_RELEVANT_MEMORY,
            supporting_memory_ids=["memory-1"],
            **common_fields,
        )


def test_merchant_consensus_contains_only_an_accepted_category() -> None:
    fields = {
        "transaction_id": "txn-2",
        "decision_type": DecisionType.MERCHANT_CONSENSUS,
        "accepted_category": "Restaurants",
        "needs_review": False,
        "confidence": DecisionConfidence.HIGH,
        "reason": "Trusted merchant history has unanimous category evidence.",
        "supporting_memory_ids": ["memory-2", "memory-3"],
    }

    decision = CategorizationDecision(**fields)

    assert decision.accepted_category == "Restaurants"

    with pytest.raises(ValidationError):
        CategorizationDecision(
            **(
                fields
                | {
                    "accepted_category": None,
                    "suggested_category": "Restaurants",
                }
            )
        )


def test_unresolved_categorization_has_no_category_and_needs_review() -> None:
    fields = {
        "transaction_id": "txn-3",
        "decision_type": DecisionType.UNRESOLVED,
        "needs_review": True,
        "confidence": DecisionConfidence.LOW,
        "reason": "Available evidence is conflicting.",
    }

    decision = CategorizationDecision(**fields)

    assert decision.accepted_category is None
    assert decision.suggested_category is None
    assert decision.proposed_category is None

    with pytest.raises(ValidationError):
        CategorizationDecision(**(fields | {"accepted_category": "Restaurants"}))


def test_recategorization_batch_preserves_order_and_reports_summary_counts() -> None:
    decision_specs = [
        {
            "decision_type": DecisionType.EXACT_STATEMENT_MEMORY_MATCH,
            "accepted_category": "Restaurants",
            "needs_review": False,
        },
        {
            "decision_type": DecisionType.AI_SUGGESTION_WITHOUT_RELEVANT_MEMORY,
            "suggested_category": "Travel",
            "needs_review": True,
        },
        {
            "decision_type": DecisionType.UNRESOLVED,
            "needs_review": True,
        },
    ]
    results = []
    for position, decision_spec in enumerate(decision_specs):
        transaction_id = f"txn-{position}"
        transaction = CanonicalTransaction(
            transaction_id=transaction_id,
            direction=TransactionDirection.DEBIT,
            identity_quality=TransactionIdentityQuality.PARTIAL,
        )
        decision = CategorizationDecision(
            transaction_id=transaction_id,
            confidence=DecisionConfidence.LOW,
            reason="Representative batch decision.",
            **decision_spec,
        )
        results.append(
            RecategorizationResult(
                position=position,
                transaction=transaction,
                decision=decision,
            )
        )

    batch = RecategorizationBatch(
        batch_id="batch-1",
        status=BatchStatus.COMPLETED,
        results=results,
        openai_request_count=1,
    )

    assert [result.transaction.transaction_id for result in batch.results] == [
        "txn-0",
        "txn-1",
        "txn-2",
    ]
    assert batch.total_count == 3
    assert batch.deterministic_count == 1
    assert batch.ai_reviewed_count == 1
    assert batch.unknown_count == 1
    assert batch.needs_review_count == 2
    assert batch.approval_required is False


def test_recategorization_batch_rejects_a_result_out_of_input_order() -> None:
    transaction = CanonicalTransaction(
        transaction_id="txn-0",
        direction=TransactionDirection.UNKNOWN,
        identity_quality=TransactionIdentityQuality.INSUFFICIENT,
    )
    decision = CategorizationDecision(
        transaction_id="txn-0",
        decision_type=DecisionType.UNRESOLVED,
        needs_review=True,
        reason="Transaction identity is insufficient.",
    )
    misplaced_result = RecategorizationResult(
        position=1,
        transaction=transaction,
        decision=decision,
    )

    with pytest.raises(ValidationError):
        RecategorizationBatch(
            batch_id="batch-2",
            status=BatchStatus.APPROVAL_REQUIRED,
            results=[misplaced_result],
            openai_request_count=0,
        )


def test_recategorization_batch_rejects_duplicate_request_scoped_ids() -> None:
    transaction = CanonicalTransaction(
        transaction_id="txn-0",
        direction=TransactionDirection.UNKNOWN,
        identity_quality=TransactionIdentityQuality.INSUFFICIENT,
    )
    decision = CategorizationDecision(
        transaction_id="txn-0",
        decision_type=DecisionType.UNRESOLVED,
        needs_review=True,
        reason="Transaction identity is insufficient.",
    )
    results = [
        RecategorizationResult(position=0, transaction=transaction, decision=decision),
        RecategorizationResult(position=1, transaction=transaction, decision=decision),
    ]

    with pytest.raises(ValidationError):
        RecategorizationBatch(
            batch_id="batch-3",
            status=BatchStatus.COMPLETED,
            results=results,
            openai_request_count=0,
        )
