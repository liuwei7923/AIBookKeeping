"""Deterministic categorization decisions drawn from trusted memory alone.

Pure: performs no file, HTTP, metrics, or OpenAI operations.
"""

from bookkeeping_app.config import DEFAULT_MERCHANT_CONSENSUS_THRESHOLD
from bookkeeping_app.domain_contracts import (
    EvidenceConfidence,
    LocalCategorizationDecision,
    LocalDecisionType,
)
from bookkeeping_app.memory.contracts import (
    MemoryEvidence,
    MemoryQuery,
    MemoryQueryResult,
)


def decide_categorization(
    query: MemoryQuery,
    result: MemoryQueryResult,
    *,
    merchant_consensus_threshold: int = DEFAULT_MERCHANT_CONSENSUS_THRESHOLD,
) -> LocalCategorizationDecision:
    """Resolve trusted memory evidence into a conservative local decision."""

    exact_decision = _exact_statement_decision(query, result)
    if exact_decision is not None:
        return exact_decision

    consensus_decision = _merchant_consensus_decision(
        result, merchant_consensus_threshold
    )
    if consensus_decision is not None:
        return consensus_decision

    return LocalCategorizationDecision(
        decision_type=LocalDecisionType.UNKNOWN,
        evidence_confidence=EvidenceConfidence.NONE,
        reason="no local decision rule matched the available evidence",
    )


def _exact_statement_decision(
    query: MemoryQuery,
    result: MemoryQueryResult,
) -> LocalCategorizationDecision | None:
    if query.normalized_statement is None:
        return None

    matches: list[MemoryEvidence] = [
        candidate
        for candidate in result.candidates
        if candidate.normalized_statement == query.normalized_statement
    ]
    if not matches:
        return None

    categories = {candidate.category for candidate in matches}
    if len(categories) != 1:
        return None

    (category,) = categories
    return LocalCategorizationDecision(
        decision_type=LocalDecisionType.ACCEPTED,
        category=category,
        evidence_confidence=EvidenceConfidence.HIGH,
        reason="exact normalized-statement evidence agrees on one category",
        supporting_memory_ids=tuple(candidate.evidence_id for candidate in matches),
    )


def _merchant_consensus_decision(
    result: MemoryQueryResult,
    merchant_consensus_threshold: int,
) -> LocalCategorizationDecision | None:
    if len(result.category_counts) != 1:
        return None

    (only_category,) = result.category_counts
    if only_category.count < merchant_consensus_threshold:
        return None

    supporting = tuple(
        candidate.evidence_id
        for candidate in result.candidates
        if candidate.category == only_category.category
    )
    return LocalCategorizationDecision(
        decision_type=LocalDecisionType.ACCEPTED,
        category=only_category.category,
        evidence_confidence=EvidenceConfidence.CONSENSUS,
        reason=(
            "merchant consensus: "
            f"{only_category.count} unanimous distinct examples met the "
            f"threshold of {merchant_consensus_threshold}"
        ),
        supporting_memory_ids=supporting,
    )
