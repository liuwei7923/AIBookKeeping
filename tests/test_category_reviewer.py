import json
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

from bookkeeping_app.category_reviewer import (
    CategoryReviewClient,
    OpenAICategoryReviewClient,
    UnresolvedTransactionContext,
    review_categories,
)
from bookkeeping_app.domain_contracts import (
    CanonicalTransaction,
    DecisionType,
    SourceTransaction,
    TransactionDirection,
    TransactionIdentityQuality,
)
from bookkeeping_app.memory import CategoryCount, MemoryEvidence, MemoryQueryResult

USER_A = UUID("550e8400-e29b-41d4-a716-446655440000")


class FakeCategoryReviewClient(CategoryReviewClient):
    """Queues canned responses and records every request it receives."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.requests: list[tuple[str, str]] = []

    def complete(self, system_prompt: str, user_input: str) -> str:
        self.requests.append((system_prompt, user_input))
        return self._responses.pop(0)


def unresolved_context(
    *,
    transaction_id: UUID | None = None,
    normalized_merchant: str = "whole foods",
    normalized_statement: str | None = "wholefds 123",
    amount: Decimal | None = Decimal("-42.19"),
    original_category: str | None = None,
    memory_candidates: tuple[MemoryEvidence, ...] = (),
    category_counts: tuple[CategoryCount, ...] = (),
) -> UnresolvedTransactionContext:
    source = SourceTransaction(
        user_id=USER_A,
        transaction_id=transaction_id or uuid4(),
        date="2026-03-01",
        merchant=normalized_merchant,
        statement=normalized_statement,
        amount=amount,
        original_category=original_category,
    )
    transaction = CanonicalTransaction(
        source=source,
        normalized_merchant=normalized_merchant,
        normalized_statement=normalized_statement,
        direction=TransactionDirection.DEBIT,
        identity_quality=TransactionIdentityQuality.COMPLETE,
        fingerprint=f"sha256:{source.transaction_id}",
    )
    return UnresolvedTransactionContext(
        transaction=transaction,
        memory=MemoryQueryResult(
            candidates=memory_candidates, category_counts=category_counts
        ),
    )


def test_no_unresolved_transactions_makes_no_model_call() -> None:
    client = FakeCategoryReviewClient(responses=[])

    decisions = review_categories([], client, known_categories=set())

    assert decisions == []
    assert client.requests == []


def test_known_category_suggestion_is_correlated_by_transaction_id() -> None:
    item = unresolved_context()
    transaction_id = str(item.transaction.source.transaction_id)
    client = FakeCategoryReviewClient(
        responses=[
            json.dumps(
                [
                    {
                        "transaction_id": transaction_id,
                        "suggested_category": "Groceries",
                        "proposed_category": None,
                        "reason": "merchant matches known grocery memory",
                    }
                ]
            )
        ]
    )

    decisions = review_categories([item], client, known_categories={"Groceries"})

    assert len(decisions) == 1
    decision = decisions[0]
    assert decision.decision_id == transaction_id
    assert decision.decision_type is DecisionType.AI_SUGGESTION
    assert decision.suggested_category == "Groceries"
    assert decision.proposed_category is None
    assert decision.reason

    # the request sent this transaction's own bounded context, not a bare id
    assert len(client.requests) == 1
    _system_prompt, user_input = client.requests[0]
    assert transaction_id in user_input


def test_new_category_not_in_known_set_is_proposed() -> None:
    item = unresolved_context()
    transaction_id = str(item.transaction.source.transaction_id)
    client = FakeCategoryReviewClient(
        responses=[
            json.dumps(
                [
                    {
                        "transaction_id": transaction_id,
                        "suggested_category": None,
                        "proposed_category": "Pet Supplies",
                        "reason": "recurring pet-store merchant with no matching category",
                    }
                ]
            )
        ]
    )

    decisions = review_categories([item], client, known_categories={"Groceries"})

    decision = decisions[0]
    assert decision.decision_type is DecisionType.AI_PROPOSED_NEW_CATEGORY
    assert decision.proposed_category == "Pet Supplies"
    assert decision.suggested_category is None


def test_explicit_unresolved_model_result_is_kept_unresolved() -> None:
    item = unresolved_context()
    transaction_id = str(item.transaction.source.transaction_id)
    client = FakeCategoryReviewClient(
        responses=[
            json.dumps(
                [
                    {
                        "transaction_id": transaction_id,
                        "suggested_category": None,
                        "proposed_category": None,
                        "reason": "evidence is ambiguous",
                    }
                ]
            )
        ]
    )

    decisions = review_categories([item], client, known_categories={"Groceries"})

    decision = decisions[0]
    assert decision.decision_type is DecisionType.UNRESOLVED
    assert decision.suggested_category is None
    assert decision.proposed_category is None
    assert decision.reason == "evidence is ambiguous"


def test_missing_result_is_unresolved_and_correlated_not_positional() -> None:
    item_a = unresolved_context()
    item_b = unresolved_context()
    id_a = str(item_a.transaction.source.transaction_id)
    id_b = str(item_b.transaction.source.transaction_id)
    client = FakeCategoryReviewClient(
        responses=[
            json.dumps(
                [
                    # response order is reversed relative to input, and item_a is missing
                    {
                        "transaction_id": id_b,
                        "suggested_category": "Groceries",
                        "proposed_category": None,
                        "reason": "matches known grocery memory",
                    },
                ]
            )
        ]
    )

    decisions = review_categories(
        [item_a, item_b], client, known_categories={"Groceries"}
    )

    assert decisions[0].decision_id == id_a
    assert decisions[0].decision_type is DecisionType.UNRESOLVED
    assert decisions[1].decision_id == id_b
    assert decisions[1].decision_type is DecisionType.AI_SUGGESTION
    assert decisions[1].suggested_category == "Groceries"


def test_duplicate_result_for_same_transaction_id_is_unresolved() -> None:
    item = unresolved_context()
    transaction_id = str(item.transaction.source.transaction_id)
    client = FakeCategoryReviewClient(
        responses=[
            json.dumps(
                [
                    {
                        "transaction_id": transaction_id,
                        "suggested_category": "Groceries",
                        "proposed_category": None,
                        "reason": "first result",
                    },
                    {
                        "transaction_id": transaction_id,
                        "suggested_category": "Dining",
                        "proposed_category": None,
                        "reason": "second, conflicting result",
                    },
                ]
            )
        ]
    )

    decisions = review_categories(
        [item], client, known_categories={"Groceries", "Dining"}
    )

    assert decisions[0].decision_type is DecisionType.UNRESOLVED


def test_result_for_unknown_transaction_id_is_ignored() -> None:
    item = unresolved_context()
    transaction_id = str(item.transaction.source.transaction_id)
    stray_id = str(uuid4())
    client = FakeCategoryReviewClient(
        responses=[
            json.dumps(
                [
                    {
                        "transaction_id": transaction_id,
                        "suggested_category": "Groceries",
                        "proposed_category": None,
                        "reason": "matches known grocery memory",
                    },
                    {
                        "transaction_id": stray_id,
                        "suggested_category": "Dining",
                        "proposed_category": None,
                        "reason": "belongs to a transaction that was never sent",
                    },
                ]
            )
        ]
    )

    decisions = review_categories([item], client, known_categories={"Groceries"})

    assert len(decisions) == 1
    assert decisions[0].decision_type is DecisionType.AI_SUGGESTION
    assert decisions[0].suggested_category == "Groceries"


def test_non_json_response_fails_safely_to_unresolved() -> None:
    item = unresolved_context()
    client = FakeCategoryReviewClient(responses=["not valid json at all"])

    decisions = review_categories([item], client, known_categories={"Groceries"})

    assert decisions[0].decision_type is DecisionType.UNRESOLVED
    assert decisions[0].reason


def test_suggested_category_outside_known_set_fails_safely_to_unresolved() -> None:
    item = unresolved_context()
    transaction_id = str(item.transaction.source.transaction_id)
    client = FakeCategoryReviewClient(
        responses=[
            json.dumps(
                [
                    {
                        "transaction_id": transaction_id,
                        "suggested_category": "Made Up Category",
                        "proposed_category": None,
                        "reason": "looks close enough",
                    }
                ]
            )
        ]
    )

    decisions = review_categories([item], client, known_categories={"Groceries"})

    assert decisions[0].decision_type is DecisionType.UNRESOLVED


def test_both_category_fields_set_fails_safely_to_unresolved() -> None:
    item = unresolved_context()
    transaction_id = str(item.transaction.source.transaction_id)
    client = FakeCategoryReviewClient(
        responses=[
            json.dumps(
                [
                    {
                        "transaction_id": transaction_id,
                        "suggested_category": "Groceries",
                        "proposed_category": "Pet Supplies",
                        "reason": "ambiguous model output",
                    }
                ]
            )
        ]
    )

    decisions = review_categories([item], client, known_categories={"Groceries"})

    assert decisions[0].decision_type is DecisionType.UNRESOLVED


def test_result_missing_reason_fails_safely_to_unresolved() -> None:
    item = unresolved_context()
    transaction_id = str(item.transaction.source.transaction_id)
    client = FakeCategoryReviewClient(
        responses=[
            json.dumps(
                [
                    {
                        "transaction_id": transaction_id,
                        "suggested_category": "Groceries",
                        "proposed_category": None,
                    }
                ]
            )
        ]
    )

    decisions = review_categories([item], client, known_categories={"Groceries"})

    assert decisions[0].decision_type is DecisionType.UNRESOLVED


def test_batches_never_exceed_configured_batch_size() -> None:
    items = [unresolved_context() for _ in range(5)]

    def make_response(chunk: list[UnresolvedTransactionContext]) -> str:
        return json.dumps(
            [
                {
                    "transaction_id": str(chunk_item.transaction.source.transaction_id),
                    "suggested_category": "Groceries",
                    "proposed_category": None,
                    "reason": "matches known grocery memory",
                }
                for chunk_item in chunk
            ]
        )

    client = FakeCategoryReviewClient(
        responses=[
            make_response(items[0:2]),
            make_response(items[2:4]),
            make_response(items[4:5]),
        ]
    )

    decisions = review_categories(
        items, client, known_categories={"Groceries"}, batch_size=2
    )

    assert len(client.requests) == 3
    for _system_prompt, user_input in client.requests:
        payload = json.loads(user_input)
        assert len(payload["transactions"]) <= 2
    assert all(
        decision.decision_type is DecisionType.AI_SUGGESTION for decision in decisions
    )
    assert [decision.decision_id for decision in decisions] == [
        str(item.transaction.source.transaction_id) for item in items
    ]


def test_each_transaction_only_receives_its_own_memory_context() -> None:
    item_a = unresolved_context(
        normalized_merchant="whole foods",
        memory_candidates=(
            MemoryEvidence(
                evidence_id=uuid4(),
                normalized_statement="wholefds 111",
                date="2026-02-01",
                amount=Decimal("-40.00"),
                original_category=None,
                category="Groceries",
            ),
        ),
        category_counts=(CategoryCount(category="Groceries", count=1),),
    )
    item_b = unresolved_context(
        normalized_merchant="shell gas",
        memory_candidates=(
            MemoryEvidence(
                evidence_id=uuid4(),
                normalized_statement="shell 222",
                date="2026-02-02",
                amount=Decimal("-30.00"),
                original_category=None,
                category="Auto & Transport",
            ),
        ),
        category_counts=(CategoryCount(category="Auto & Transport", count=1),),
    )
    id_a = str(item_a.transaction.source.transaction_id)
    id_b = str(item_b.transaction.source.transaction_id)
    client = FakeCategoryReviewClient(
        responses=[
            json.dumps(
                [
                    {
                        "transaction_id": id_a,
                        "suggested_category": "Groceries",
                        "proposed_category": None,
                        "reason": "matches known grocery memory",
                    },
                    {
                        "transaction_id": id_b,
                        "suggested_category": "Auto & Transport",
                        "proposed_category": None,
                        "reason": "matches known auto memory",
                    },
                ]
            )
        ]
    )

    review_categories(
        [item_a, item_b],
        client,
        known_categories={"Groceries", "Auto & Transport"},
    )

    _system_prompt, user_input = client.requests[0]
    payload = json.loads(user_input)
    by_id = {entry["transaction_id"]: entry for entry in payload["transactions"]}

    assert [example["statement"] for example in by_id[id_a]["memory_examples"]] == [
        "wholefds 111"
    ]
    assert [example["statement"] for example in by_id[id_b]["memory_examples"]] == [
        "shell 222"
    ]


class FakeOpenAIResponses:
    def __init__(self, output_text: str) -> None:
        self._output_text = output_text
        self.create_kwargs: dict | None = None

    def create(self, **kwargs):
        self.create_kwargs = kwargs
        return SimpleNamespace(output_text=self._output_text)


class FakeOpenAISDKClient:
    def __init__(self, output_text: str) -> None:
        self.responses = FakeOpenAIResponses(output_text)


def test_openai_adapter_forwards_prompts_and_returns_output_text() -> None:
    sdk_client = FakeOpenAISDKClient(output_text="[]")
    adapter = OpenAICategoryReviewClient(client=sdk_client)

    result = adapter.complete("system prompt text", "user input text")

    assert result == "[]"
    kwargs = sdk_client.responses.create_kwargs
    assert kwargs["input"][0]["role"] == "system"
    assert kwargs["input"][0]["content"][0]["text"] == "system prompt text"
    assert kwargs["input"][1]["role"] == "user"
    assert kwargs["input"][1]["content"][0]["text"] == "user input text"
