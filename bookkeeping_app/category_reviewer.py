"""Structured, bounded OpenAI category review for unresolved transactions.

Sends only unresolved canonical transactions, each with its own bounded
memory context, and correlates model results by transaction ID rather than
response position. Never assigns trust, evidence confidence, or a final
application decision.
"""

import json
from collections.abc import Sequence, Set
from typing import Any, Protocol

from openai import OpenAI
from pydantic import BaseModel, ConfigDict

from bookkeeping_app.config import DEFAULT_AI_BATCH_SIZE, MODEL_NAME
from bookkeeping_app.domain_contracts import (
    CanonicalTransaction,
    CategorizationDecision,
    DecisionType,
)
from bookkeeping_app.memory.contracts import MemoryQueryResult
from bookkeeping_app.metrics import metrics
from bookkeeping_app.openai_service import get_openai_client, raise_openai_http_error
from bookkeeping_app.prompts import CATEGORY_REVIEWER_PROMPT


class CategoryReviewClient(Protocol):
    """Seam for the model call, replaceable with a fake in tests."""

    def complete(self, system_prompt: str, user_input: str) -> str:
        """Return the raw model response text for one bounded batch."""
        ...


class OpenAICategoryReviewClient:
    """Production CategoryReviewClient backed by the OpenAI Responses API."""

    def __init__(self, client: OpenAI | None = None, model: str = MODEL_NAME) -> None:
        self._client = client
        self._model = model

    def complete(self, system_prompt: str, user_input: str) -> str:
        client = self._client or get_openai_client()

        try:
            response = client.responses.create(
                model=self._model,
                input=[
                    {
                        "role": "system",
                        "content": [{"type": "input_text", "text": system_prompt}],
                    },
                    {
                        "role": "user",
                        "content": [{"type": "input_text", "text": user_input}],
                    },
                ],
            )
        except Exception as exc:
            raise_openai_http_error(exc)

        return getattr(response, "output_text", "") or ""


class UnresolvedTransactionContext(BaseModel):
    """One unresolved transaction paired with its own bounded memory evidence."""

    model_config = ConfigDict(extra="forbid")

    transaction: CanonicalTransaction
    memory: MemoryQueryResult


def review_categories(
    items: Sequence[UnresolvedTransactionContext],
    client: CategoryReviewClient,
    known_categories: Set[str],
    *,
    batch_size: int = DEFAULT_AI_BATCH_SIZE,
) -> list[CategorizationDecision]:
    """Review unresolved transactions in bounded batches, keyed by transaction ID."""

    decisions: dict[str, CategorizationDecision] = {}

    for chunk in _chunk(items, batch_size):
        decisions.update(_review_chunk(chunk, client, known_categories))

    return [decisions[str(item.transaction.source.transaction_id)] for item in items]


def _chunk(
    items: Sequence[UnresolvedTransactionContext], batch_size: int
) -> list[list[UnresolvedTransactionContext]]:
    return [
        list(items[index : index + batch_size])
        for index in range(0, len(items), batch_size)
    ]


def _review_chunk(
    chunk: list[UnresolvedTransactionContext],
    client: CategoryReviewClient,
    known_categories: Set[str],
) -> dict[str, CategorizationDecision]:
    by_id = {str(item.transaction.source.transaction_id): item for item in chunk}

    metrics.record_openai_request("category_review")
    raw_response = client.complete(
        CATEGORY_REVIEWER_PROMPT, _build_request(chunk, known_categories)
    )

    results = _parse_response(raw_response)
    decisions: dict[str, CategorizationDecision] = {}

    for transaction_id in by_id:
        raw_results = results.get(transaction_id, [])
        decisions[transaction_id] = _decide(
            transaction_id, raw_results, known_categories
        )

    return decisions


def _build_request(
    chunk: list[UnresolvedTransactionContext], known_categories: Set[str]
) -> str:
    payload = {
        "known_categories": sorted(known_categories),
        "transactions": [
            {
                "transaction_id": str(item.transaction.source.transaction_id),
                "date": item.transaction.source.date,
                "amount": str(item.transaction.source.amount)
                if item.transaction.source.amount is not None
                else None,
                "merchant": item.transaction.normalized_merchant,
                "original_category": item.transaction.source.original_category,
                "memory_examples": [
                    {
                        "statement": candidate.normalized_statement,
                        "date": candidate.date,
                        "amount": str(candidate.amount)
                        if candidate.amount is not None
                        else None,
                        "original_category": candidate.original_category,
                        "category": candidate.category,
                    }
                    for candidate in item.memory.candidates
                ],
                "category_counts": [
                    {"category": count.category, "count": count.count}
                    for count in item.memory.category_counts
                ],
            }
            for item in chunk
        ],
    }
    return json.dumps(payload)


def _parse_response(raw_response: str) -> dict[str, list[dict[str, Any]]]:
    """Group raw result objects by transaction_id, tolerating malformed input."""

    try:
        data = json.loads(raw_response)
    except json.JSONDecodeError:
        return {}

    if not isinstance(data, list):
        return {}

    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        transaction_id = item.get("transaction_id")
        if not isinstance(transaction_id, str):
            continue
        grouped.setdefault(transaction_id, []).append(item)

    return grouped


def _decide(
    transaction_id: str,
    raw_results: list[dict[str, Any]],
    known_categories: Set[str],
) -> CategorizationDecision:
    if not raw_results:
        return _unresolved(transaction_id, "no model result for this transaction")

    if len(raw_results) > 1:
        return _unresolved(
            transaction_id, "model returned duplicate results for this transaction"
        )

    (result,) = raw_results
    return _decide_single(transaction_id, result, known_categories)


def _decide_single(
    transaction_id: str,
    result: dict[str, Any],
    known_categories: Set[str],
) -> CategorizationDecision:
    reason = result.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        return _unresolved(transaction_id, "model result was missing a reason")

    suggested_category = _clean_category(result.get("suggested_category"))
    proposed_category = _clean_category(result.get("proposed_category"))

    if suggested_category and proposed_category:
        return _unresolved(
            transaction_id,
            "model result set both suggested_category and proposed_category",
        )

    if suggested_category:
        if suggested_category not in known_categories:
            return _unresolved(
                transaction_id,
                "model suggested a category outside the known set",
            )
        return CategorizationDecision(
            decision_id=transaction_id,
            decision_type=DecisionType.AI_SUGGESTION,
            suggested_category=suggested_category,
            reason=reason,
        )

    if proposed_category:
        if proposed_category in known_categories:
            return _unresolved(
                transaction_id,
                "model proposed a category that is already known",
            )
        return CategorizationDecision(
            decision_id=transaction_id,
            decision_type=DecisionType.AI_PROPOSED_NEW_CATEGORY,
            proposed_category=proposed_category,
            reason=reason,
        )

    return CategorizationDecision(
        decision_id=transaction_id,
        decision_type=DecisionType.UNRESOLVED,
        reason=reason,
    )


def _clean_category(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _unresolved(transaction_id: str, reason: str) -> CategorizationDecision:
    return CategorizationDecision(
        decision_id=transaction_id,
        decision_type=DecisionType.UNRESOLVED,
        reason=reason,
    )
