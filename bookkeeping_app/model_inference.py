"""Small inference boundary shared by domain reviewers; no HTTP route concerns."""

import os
from collections.abc import Callable
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit

from openai import APIStatusError, OpenAI, OpenAIError

from bookkeeping_app.config import BEAM_MODEL_NAME, MODEL_NAME
from bookkeeping_app.metrics import metrics


class ModelInferenceError(Exception):
    """An inference request failed or produced no usable text."""

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class ModelClient(Protocol):
    def complete(
        self,
        system_prompt: str,
        user_input: str,
        *,
        output_schema: dict[str, Any] | None = None,
    ) -> str:
        """Return text; adapters translate provider failures to ModelInferenceError."""
        ...


def get_review_client(
    stage: Literal["merchant", "category"],
    *,
    openai_client_factory: Callable[[], OpenAI] | None = None,
) -> ModelClient:
    """Select a stage's configured client without making an inference request.

    Merchant review uses the configured Beam endpoint; category review uses
    OpenAI.
    """
    if stage == "merchant":
        return BeamModelClient(
            model=BEAM_MODEL_NAME, operation="merchant_review", max_output_tokens=8192
        )
    if stage == "category":
        return OpenAIModelClient(
            model=MODEL_NAME,
            operation="category_review",
            client=openai_client_factory() if openai_client_factory else None,
        )
    raise ValueError("unsupported review stage")


class _ModelClientBase:
    """Shared adapter validation and failure translation for the inference boundary."""

    def __init__(
        self,
        *,
        model: str,
        operation: str,
        client: OpenAI | None = None,
        timeout: float = 60,
        max_output_tokens: int | None = None,
    ) -> None:
        if (
            not model.strip()
            or timeout <= 0
            or (max_output_tokens is not None and max_output_tokens <= 0)
        ):
            raise ValueError("model, positive timeout and output limit are required")
        self._model = model
        self._operation = operation
        self._client = client
        self._timeout = timeout
        self._max_output_tokens = max_output_tokens

    def complete(
        self,
        system_prompt: str,
        user_input: str,
        *,
        output_schema: dict[str, Any] | None = None,
    ) -> str:
        """Request inference without implicit retries or a different-model fallback."""
        client = self._client if self._client is not None else self._connect()
        request = self._build_request(system_prompt, user_input, output_schema)
        try:
            response = self._send(client, request)
        except APIStatusError as exc:
            raise ModelInferenceError(
                "Model request failed", status_code=exc.status_code
            ) from None
        except OpenAIError:
            raise ModelInferenceError("Model request failed") from None
        return self._parse_response(response)

    # Provider-specific hooks; each adapter implements these four.

    def _connect(self) -> OpenAI:
        raise NotImplementedError

    def _build_request(
        self,
        system_prompt: str,
        user_input: str,
        output_schema: dict[str, Any] | None,
    ) -> dict[str, Any]:
        raise NotImplementedError

    def _send(self, client: OpenAI, request: dict[str, Any]) -> Any:
        raise NotImplementedError

    def _parse_response(self, response: Any) -> str:
        raise NotImplementedError


class OpenAIModelClient(_ModelClientBase):
    """Lazy Responses API adapter; fakes and future providers implement ModelClient."""

    def _connect(self) -> OpenAI:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ModelInferenceError("OPENAI_API_KEY is not configured")
        return OpenAI(api_key=api_key, max_retries=0)

    def _build_request(
        self,
        system_prompt: str,
        user_input: str,
        output_schema: dict[str, Any] | None,
    ) -> dict[str, Any]:
        request: dict[str, Any] = {
            "model": self._model,
            "input": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input},
            ],
            "timeout": self._timeout,
            "store": False,
        }
        if self._max_output_tokens is not None:
            request["max_output_tokens"] = self._max_output_tokens
        if output_schema is not None:
            request["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": "review_results",
                    "strict": True,
                    "schema": output_schema,
                }
            }
        return request

    def _send(self, client: OpenAI, request: dict[str, Any]) -> Any:
        metrics.record_openai_request(self._operation, self._model)
        return client.responses.create(**request)

    def _parse_response(self, response: Any) -> str:
        text = getattr(response, "output_text", None)
        if not isinstance(text, str) or not text.strip():
            raise ModelInferenceError("Model returned no text")
        if getattr(response, "status", "completed") != "completed":
            raise ModelInferenceError("Model response was incomplete")
        return text


class BeamModelClient(_ModelClientBase):
    """OpenAI-compatible Chat Completions adapter for a self-configured endpoint."""

    def _connect(self) -> OpenAI:
        api_key = os.getenv("BEAM_API_KEY")
        base_url = os.getenv("BEAM_BASE_URL")
        if not api_key or not base_url:
            raise ModelInferenceError(
                "BEAM_API_KEY and BEAM_BASE_URL are not configured"
            )
        if urlsplit(base_url).scheme != "https":
            raise ModelInferenceError("BEAM_BASE_URL must use https")
        return OpenAI(api_key=api_key, base_url=base_url, max_retries=0)

    def _build_request(
        self,
        system_prompt: str,
        user_input: str,
        output_schema: dict[str, Any] | None,
    ) -> dict[str, Any]:
        request: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input},
            ],
            "timeout": self._timeout,
            "store": False,
        }
        if self._max_output_tokens is not None:
            request["max_completion_tokens"] = self._max_output_tokens
        if output_schema is not None:
            request["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "review_results",
                    "strict": True,
                    "schema": output_schema,
                },
            }
        return request

    def _send(self, client: OpenAI, request: dict[str, Any]) -> Any:
        metrics.record_beam_request(self._operation, self._model)
        return client.chat.completions.create(**request)

    def _parse_response(self, response: Any) -> str:
        choices = getattr(response, "choices", None)
        if not isinstance(choices, list) or len(choices) != 1:
            raise ModelInferenceError("Model returned an invalid response")
        choice = choices[0]
        message = getattr(choice, "message", None)
        content = getattr(message, "content", None)
        if (
            getattr(choice, "finish_reason", None) != "stop"
            or getattr(message, "refusal", None)
            or not isinstance(content, str)
            or not content.strip()
        ):
            raise ModelInferenceError("Model response was incomplete or refused")
        return content
