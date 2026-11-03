from types import SimpleNamespace

import httpx2 as httpx
import pytest
from openai import OpenAI

from bookkeeping_app.metrics import metrics
from bookkeeping_app.model_inference import (
    BeamModelClient,
    ModelInferenceError,
    OpenAIModelClient,
    get_review_client,
)


def test_beam_adapter_uses_reflection_chat_api_with_mock_transport(monkeypatch):
    import json

    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "created": 0,
                "model": "Beam-1.0-501B-A23B",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": '{"results":[]}'},
                    }
                ],
            },
        )

    monkeypatch.setattr(metrics, "openai_request_count", 0)
    monkeypatch.setattr(metrics, "beam_request_count", 0)
    with httpx.Client(transport=httpx.MockTransport(respond)) as http_client:
        sdk = OpenAI(
            api_key="synthetic-test-key",
            base_url="https://api.reflection.ai/openai/v1",
            http_client=http_client,
            max_retries=0,
        )
        adapter = BeamModelClient(
            model="Beam-1.0-501B-A23B", operation="merchant_review", client=sdk
        )
        schema = {"type": "object", "properties": {}, "additionalProperties": False}
        assert (
            adapter.complete("system", "input", output_schema=schema)
            == '{"results":[]}'
        )
    request = requests[0]
    body = json.loads(request.content)
    assert str(request.url) == "https://api.reflection.ai/openai/v1/chat/completions"
    assert body["response_format"]["json_schema"]["schema"] == schema
    assert body["store"] is False
    assert metrics.beam_request_count == 1
    assert metrics.openai_request_count == 0


def test_category_path_can_select_beam_without_openai_credentials(monkeypatch):
    from bookkeeping_app.openai_service import review_transaction_categories

    requests = []
    text = '[{"date":null,"amount":null,"merchant":"Cafe","original_category":null,"suggested_category":"Food","reason":"Cafe"}]'
    sdk = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **kwargs: (
                    requests.append(kwargs)
                    or SimpleNamespace(
                        choices=[
                            SimpleNamespace(
                                finish_reason="stop",
                                message=SimpleNamespace(refusal=None, content=text),
                            )
                        ]
                    )
                )
            )
        )
    )
    monkeypatch.setattr(
        "bookkeeping_app.model_inference.CATEGORY_REVIEW_PROVIDER", "beam"
    )
    monkeypatch.setattr("bookkeeping_app.model_inference.OpenAI", lambda **kwargs: sdk)
    monkeypatch.setenv("BEAM_API_KEY", "synthetic")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    results = review_transaction_categories([{"merchant": "Cafe"}])
    assert results[0]["suggested_category"] == "Food"
    assert requests[0]["model"] == "Beam-1.0-501B-A23B"


def test_category_missing_openai_key_reports_configuration_error(monkeypatch):
    from fastapi import HTTPException

    from bookkeeping_app.openai_service import review_transaction_categories

    monkeypatch.setattr(
        "bookkeeping_app.model_inference.CATEGORY_REVIEW_PROVIDER", "openai"
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(HTTPException) as error:
        review_transaction_categories([{"merchant": "Cafe"}])
    assert error.value.status_code == 500


def test_missing_beam_credentials_does_not_fall_back(monkeypatch):
    monkeypatch.delenv("BEAM_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic")
    with pytest.raises(ModelInferenceError, match="BEAM_API_KEY"):
        BeamModelClient(model="beam", operation="test").complete("s", "u")


@pytest.mark.parametrize(
    "finish,refusal,content",
    [("length", None, "{}"), ("stop", "refused", None), ("stop", None, "")],
)
def test_beam_rejects_incomplete_refused_or_empty_output(finish, refusal, content):
    message = SimpleNamespace(content=content, refusal=refusal)
    sdk = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **kwargs: SimpleNamespace(
                    choices=[SimpleNamespace(finish_reason=finish, message=message)]
                )
            )
        )
    )
    with pytest.raises(ModelInferenceError):
        BeamModelClient(model="test", operation="test", client=sdk).complete(
            "system", "user"
        )


def test_luna_adapter_uses_real_sdk_with_mock_transport(monkeypatch):
    import json

    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "resp_test",
                "object": "response",
                "created_at": 0,
                "model": "gpt-6-luna",
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "id": "msg_test",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {
                                "type": "output_text",
                                "text": '{"results":[]}',
                                "annotations": [],
                            }
                        ],
                    }
                ],
            },
        )

    monkeypatch.setattr(metrics, "openai_request_count", 0)
    with httpx.Client(transport=httpx.MockTransport(respond)) as http_client:
        sdk = OpenAI(
            api_key="synthetic-test-key", http_client=http_client, max_retries=0
        )
        adapter = OpenAIModelClient(
            model="gpt-6-luna", operation="merchant_review", client=sdk
        )
        schema = {"type": "object", "properties": {}, "additionalProperties": False}
        assert (
            adapter.complete("system", "input", output_schema=schema)
            == '{"results":[]}'
        )
    assert requests[0]["model"] == "gpt-6-luna"
    assert requests[0]["store"] is False
    assert requests[0]["text"]["format"]["schema"] == schema
    assert requests[0]["max_output_tokens"] == 8192
    assert metrics.openai_request_count == 1


@pytest.mark.parametrize("status", [429, 500])
def test_provider_errors_are_sanitized_without_retry(status):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(
            status, json={"error": {"message": "sensitive provider detail"}}
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as http_client:
        sdk = OpenAI(api_key="synthetic", http_client=http_client, max_retries=0)
        with pytest.raises(ModelInferenceError, match="Model request failed"):
            OpenAIModelClient(
                model="gpt-6-luna", operation="test", client=sdk
            ).complete("s", "u")
    assert len(calls) == 1


def test_missing_credentials_are_lazy_and_not_counted(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    before = metrics.openai_request_count
    client = get_review_client("merchant")
    with pytest.raises(ModelInferenceError, match="OPENAI_API_KEY"):
        client.complete("s", "u")
    assert metrics.openai_request_count == before


@pytest.mark.parametrize("text,status", [("", "completed"), ("partial", "incomplete")])
def test_empty_or_incomplete_response_is_failure(text, status):
    sdk = SimpleNamespace(
        responses=SimpleNamespace(
            create=lambda **kwargs: SimpleNamespace(output_text=text, status=status)
        )
    )
    with pytest.raises(ModelInferenceError):
        OpenAIModelClient(model="gpt-6-luna", operation="test", client=sdk).complete(
            "s", "u"
        )


def test_per_stage_model_selection(monkeypatch):
    monkeypatch.setattr(
        "bookkeeping_app.model_inference.MERCHANT_MODEL_NAME", "merchant-test"
    )
    monkeypatch.setattr("bookkeeping_app.model_inference.MODEL_NAME", "category-test")
    requests = []
    sdk = SimpleNamespace(
        responses=SimpleNamespace(
            create=lambda **kwargs: (
                requests.append(kwargs) or SimpleNamespace(output_text="{}")
            )
        )
    )
    monkeypatch.setattr("bookkeeping_app.model_inference.OpenAI", lambda **kwargs: sdk)
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic")
    get_review_client("merchant").complete("s", "u")
    get_review_client("category").complete("s", "u")
    assert [request["model"] for request in requests] == [
        "merchant-test",
        "category-test",
    ]
