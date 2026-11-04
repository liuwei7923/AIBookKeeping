import json
from decimal import Decimal
from uuid import uuid4

import pytest

from bookkeeping_app.domain_contracts import SourceTransaction
from bookkeeping_app.merchant_reviewer import MerchantReviewResponse, review_merchants
from bookkeeping_app.model_inference import ModelInferenceError


class FakeModel:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    def complete(self, system_prompt, user_input, *, output_schema=None):
        self.requests.append((system_prompt, json.loads(user_input), output_schema))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def transaction(**overrides):
    return SourceTransaction.model_validate(
        {"user_id": USER, "source_description": "POS COFFEE #12", **overrides}
    )


USER = uuid4()


def test_generated_schema_requires_all_fields_and_forbids_extra_properties():
    schema = MerchantReviewResponse.model_json_schema()

    def check(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node.get("additionalProperties") is False
                assert set(node.get("required", [])) == set(node.get("properties", {}))
            if node.get("type") == "array":
                assert "items" in node
            for value in node.values():
                check(value)
        elif isinstance(node, list):
            for value in node:
                check(value)

    check(schema)


def response(item, **overrides):
    return {
        "transaction_id": str(item.transaction_id),
        "merchant": "Northstar Cafe",
        "alternatives": None,
        "reason": "Description identifies cafe",
        **overrides,
    }


def test_payload_preserves_source_and_excludes_user_identity(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    item = transaction(
        amount=Decimal("-12.500000000001"),
        memo="Synthetic memo",
        transaction_type="Sale",
    )
    client = FakeModel([json.dumps({"results": [response(item)]})])

    result = review_merchants([item], client)

    assert result[0].merchant == "Northstar Cafe"
    assert item.confirmed_merchant is None
    _, payload, schema = client.requests[0]
    assert payload["transactions"] == [
        {
            "transaction_id": str(item.transaction_id),
            "description": "POS COFFEE #12",
            "source_merchant": None,
            "type": "Sale",
        }
    ]
    assert "user_id" not in json.dumps(payload)
    assert schema["additionalProperties"] is False


def test_batches_and_reversed_results_restore_input_order():
    items = [transaction() for _ in range(5)]
    client = FakeModel(
        [
            json.dumps(
                {
                    "results": [
                        response(item) for item in reversed(items[start : start + 2])
                    ]
                }
            )
            for start in range(0, 5, 2)
        ]
    )
    results = review_merchants(items, client, batch_size=2)
    assert [item.transaction_id for item in results] == [
        str(item.transaction_id) for item in items
    ]
    assert [len(payload["transactions"]) for _, payload, _ in client.requests] == [
        2,
        2,
        1,
    ]


@pytest.mark.parametrize(
    "override",
    [
        {"merchant": 123},
        {"merchant": " "},
        {"reason": None},
        {"reason": ""},
        {"unexpected": "value"},
    ],
)
def test_invalid_result_is_unknown_without_losing_valid_neighbor(override):
    first, second = transaction(), transaction()
    client = FakeModel(
        [json.dumps({"results": [response(first, **override), response(second)]})]
    )
    results = review_merchants([first, second], client)
    assert results[0].merchant is None
    assert results[1].merchant == "Northstar Cafe"


def test_duplicate_missing_and_foreign_ids_do_not_produce_wrong_suggestion():
    first, second = transaction(), transaction()
    client = FakeModel(
        [
            json.dumps(
                {"results": [response(first), response(first), response(transaction())]}
            )
        ]
    )
    assert all(
        result.merchant is None for result in review_merchants([first, second], client)
    )


@pytest.mark.parametrize(
    "raw", ["not JSON", "[]", '{"results":{}}', '{"results":[],"extra":1}']
)
def test_invalid_envelope_is_unknown(raw):
    assert review_merchants([transaction()], FakeModel([raw]))[0].merchant is None


def test_model_unknown_is_retained():
    item = transaction()
    result = review_merchants(
        [item], FakeModel([json.dumps({"results": [response(item, merchant=None)]})])
    )
    assert result[0].merchant is None
    assert result[0].reason == "Description identifies cafe"


def test_failed_chunk_does_not_discard_successful_chunks():
    first, second = transaction(), transaction()
    client = FakeModel(
        [
            ModelInferenceError("private details"),
            json.dumps({"results": [response(second)]}),
        ]
    )
    results = review_merchants([first, second], client, batch_size=1)
    assert results[0].merchant is None
    assert "private details" not in results[0].reason
    assert results[1].merchant == "Northstar Cafe"


def test_empty_input_makes_no_request():
    client = FakeModel([])
    assert review_merchants([], client) == []
    assert client.requests == []


@pytest.mark.parametrize("size", [0, -1, True, 1.5, 26])
def test_invalid_batch_size_rejected_before_call(size):
    client = FakeModel([])
    with pytest.raises(ValueError):
        review_merchants([transaction()], client, batch_size=size)
    assert client.requests == []


def test_duplicate_ids_and_mixed_users_rejected_before_call():
    item = transaction()
    client = FakeModel([])
    for items in ([item, item], [item, transaction(user_id=uuid4())]):
        with pytest.raises(ValueError):
            review_merchants(items, client)
    assert client.requests == []
