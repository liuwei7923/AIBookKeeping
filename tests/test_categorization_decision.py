from decimal import Decimal
from uuid import UUID

from bookkeeping_app.categorization_decision import decide_categorization
from bookkeeping_app.domain_contracts import (
    EvidenceConfidence,
    LocalDecisionType,
    TransactionDirection,
)
from bookkeeping_app.memory import (
    CategoryCount,
    MemoryEvidence,
    MemoryQuery,
    MemoryQueryResult,
)

USER_A = UUID("550e8400-e29b-41d4-a716-446655440000")


def evidence(
    evidence_number: int,
    *,
    normalized_statement: str | None = "wholefds 123",
    category: str = "Groceries",
    amount: Decimal | None = Decimal("-42.19"),
    date: str | None = "2026-03-01",
    original_category: str | None = None,
) -> MemoryEvidence:
    return MemoryEvidence(
        evidence_id=UUID(int=evidence_number),
        normalized_statement=normalized_statement,
        date=date,
        amount=amount,
        original_category=original_category,
        category=category,
    )


def base_query(
    *,
    normalized_statement: str | None = "wholefds 123",
    amount: Decimal | None = Decimal("-42.19"),
) -> MemoryQuery:
    return MemoryQuery(
        user_id=USER_A,
        normalized_merchant="whole foods",
        direction=TransactionDirection.DEBIT,
        normalized_statement=normalized_statement,
        amount=amount,
    )


def test_exact_statement_agreement_returns_high_evidence_local_decision() -> None:
    query = base_query()
    result = MemoryQueryResult(
        candidates=(evidence(1),),
        category_counts=(CategoryCount(category="Groceries", count=1),),
    )

    decision = decide_categorization(query, result)

    assert decision.decision_type is LocalDecisionType.ACCEPTED
    assert decision.category == "Groceries"
    assert decision.evidence_confidence is EvidenceConfidence.HIGH
    assert decision.reason
    assert decision.supporting_memory_ids == (UUID(int=1),)


def test_two_unanimous_merchant_examples_satisfy_default_consensus() -> None:
    query = base_query(normalized_statement="wholefds 999")
    result = MemoryQueryResult(
        candidates=(
            evidence(1, normalized_statement="wholefds 111"),
            evidence(2, normalized_statement="wholefds 222"),
        ),
        category_counts=(CategoryCount(category="Groceries", count=2),),
    )

    decision = decide_categorization(query, result)

    assert decision.decision_type is LocalDecisionType.ACCEPTED
    assert decision.category == "Groceries"
    assert decision.evidence_confidence is EvidenceConfidence.CONSENSUS
    assert decision.reason
    assert set(decision.supporting_memory_ids) == {UUID(int=1), UUID(int=2)}


def test_conflicting_categories_remain_unknown() -> None:
    query = base_query(normalized_statement="wholefds 999")
    result = MemoryQueryResult(
        candidates=(
            evidence(1, normalized_statement="wholefds 111", category="Groceries"),
            evidence(2, normalized_statement="wholefds 222", category="Dining"),
        ),
        category_counts=(
            CategoryCount(category="Groceries", count=1),
            CategoryCount(category="Dining", count=1),
        ),
    )

    decision = decide_categorization(query, result)

    assert decision.decision_type is LocalDecisionType.UNKNOWN
    assert decision.category is None
    assert decision.evidence_confidence is EvidenceConfidence.NONE
    assert decision.reason


def test_one_example_does_not_satisfy_merchant_consensus() -> None:
    query = base_query(normalized_statement="wholefds 999")
    result = MemoryQueryResult(
        candidates=(evidence(1, normalized_statement="wholefds 111"),),
        category_counts=(CategoryCount(category="Groceries", count=1),),
    )

    decision = decide_categorization(query, result)

    assert decision.decision_type is LocalDecisionType.UNKNOWN
    assert decision.category is None
    assert decision.evidence_confidence is EvidenceConfidence.NONE
    assert decision.reason


def test_duplicate_fingerprints_cannot_satisfy_consensus() -> None:
    query = base_query(normalized_statement="wholefds 999")
    result = MemoryQueryResult(
        candidates=(
            evidence(1, normalized_statement="wholefds 111"),
            evidence(2, normalized_statement="wholefds 111"),
        ),
        category_counts=(CategoryCount(category="Groceries", count=1),),
    )

    decision = decide_categorization(query, result)

    assert decision.decision_type is LocalDecisionType.UNKNOWN
    assert decision.category is None
    assert decision.evidence_confidence is EvidenceConfidence.NONE


def test_missing_evidence_is_unknown() -> None:
    query = base_query()
    result = MemoryQueryResult(candidates=(), category_counts=())

    decision = decide_categorization(query, result)

    assert decision.decision_type is LocalDecisionType.UNKNOWN
    assert decision.category is None
    assert decision.evidence_confidence is EvidenceConfidence.NONE
    assert decision.reason
    assert decision.supporting_memory_ids == ()


def test_configurable_threshold_lets_a_single_example_reach_consensus() -> None:
    query = base_query(normalized_statement="wholefds 999")
    result = MemoryQueryResult(
        candidates=(evidence(1, normalized_statement="wholefds 111"),),
        category_counts=(CategoryCount(category="Groceries", count=1),),
    )

    decision = decide_categorization(query, result, merchant_consensus_threshold=1)

    assert decision.decision_type is LocalDecisionType.ACCEPTED
    assert decision.category == "Groceries"
    assert decision.evidence_confidence is EvidenceConfidence.CONSENSUS
    assert decision.supporting_memory_ids == (UUID(int=1),)


def test_configurable_threshold_can_require_more_than_the_default() -> None:
    query = base_query(normalized_statement="wholefds 999")
    result = MemoryQueryResult(
        candidates=(
            evidence(1, normalized_statement="wholefds 111"),
            evidence(2, normalized_statement="wholefds 222"),
        ),
        category_counts=(CategoryCount(category="Groceries", count=2),),
    )

    decision = decide_categorization(query, result, merchant_consensus_threshold=3)

    assert decision.decision_type is LocalDecisionType.UNKNOWN
    assert decision.category is None
    assert decision.evidence_confidence is EvidenceConfidence.NONE


def test_amount_proximity_alone_does_not_trigger_a_local_decision() -> None:
    query = base_query(normalized_statement="wholefds 999", amount=Decimal("-42.19"))
    result = MemoryQueryResult(
        candidates=(
            evidence(
                1,
                normalized_statement="wholefds 111",
                amount=Decimal("-42.19"),
            ),
        ),
        category_counts=(CategoryCount(category="Groceries", count=1),),
    )

    decision = decide_categorization(query, result)

    assert decision.decision_type is LocalDecisionType.UNKNOWN
    assert decision.category is None
    assert decision.evidence_confidence is EvidenceConfidence.NONE
