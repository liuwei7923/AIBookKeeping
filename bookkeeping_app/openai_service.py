"""OpenAI request helpers for category review flows."""

import json
import logging
import os
from decimal import Decimal
from typing import Any

import httpx
from fastapi import HTTPException
from openai import APIError, APIStatusError, OpenAI

from bookkeeping_app.config import MAX_CATEGORY_CONTEXT_ITEMS, OPENAI_BASE_URL
from bookkeeping_app.model_inference import ModelInferenceError, get_review_client
from bookkeeping_app.parsers import parse_category_review
from bookkeeping_app.domain_contracts import ReviewStage
from bookkeeping_app.prompts import CATEGORY_REVIEW_PROMPT

logger = logging.getLogger("bookkeeping_app")


def _json_default(value: Any) -> str:
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def get_openai_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY is not set")
    return OpenAI(
        api_key=api_key,
        base_url=OPENAI_BASE_URL,
        max_retries=0,
        http_client=httpx.Client(follow_redirects=False),
    )


def raise_openai_http_error(exc: Exception) -> None:
    if isinstance(exc, APIStatusError):
        logger.error("OpenAI API status error status=%s", exc.status_code)
        if exc.status_code == 429:
            raise HTTPException(
                status_code=429,
                detail="OpenAI quota or rate limit exceeded. Check API billing, project limits, or try again later.",
            ) from exc

        raise HTTPException(
            status_code=502,
            detail=f"OpenAI API request failed with status {exc.status_code}",
        ) from exc

    if isinstance(exc, APIError):
        logger.error("OpenAI API error type=%s", type(exc).__name__)
        raise HTTPException(
            status_code=502, detail="OpenAI API request failed"
        ) from exc

    logger.error("Unexpected model error type=%s", type(exc).__name__)
    raise HTTPException(
        status_code=502, detail="Unexpected error while calling OpenAI"
    ) from exc


def build_category_review_input(
    transactions: list[dict[str, Any]],
    category_history: list[dict[str, Any]] | None = None,
) -> str:
    payload = {
        "transactions": [
            {
                "date": transaction.get("date"),
                "amount": transaction.get("amount"),
                "merchant": transaction.get("merchant"),
                "source_description": (
                    transaction.get("source_description")
                    or transaction.get("description")
                    or transaction.get("statement")
                ),
                "original_category": transaction.get("category"),
            }
            for transaction in transactions
        ]
    }

    if category_history:
        payload["manual_override_examples"] = category_history[
            :MAX_CATEGORY_CONTEXT_ITEMS
        ]

    return (
        "Review these transactions and suggest corrected categories when needed.\n\n"
        # Statement amounts are Decimal so serialization must not round them
        # through float; encode exact monetary values as JSON strings.
        f"{json.dumps(payload, default=_json_default)}"
    )


def review_transaction_categories(
    transactions: list[dict[str, Any]],
    category_history: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if not transactions:
        return []

    try:
        output_text = get_review_client(
            ReviewStage.CATEGORY, openai_client_factory=get_openai_client
        ).complete(
            CATEGORY_REVIEW_PROMPT,
            build_category_review_input(transactions, category_history),
        )
    except ModelInferenceError as exc:
        status = 429 if exc.status_code == 429 else 502
        logger.error(
            "Model inference failed status=%s message=%s", exc.status_code, exc
        )
        detail = (
            "OpenAI quota or rate limit exceeded. Check API billing, project limits, or try again later."
            if status == 429
            else "OpenAI API request failed"
        )
        raise HTTPException(status_code=status, detail=detail) from None
    except HTTPException:
        raise
    except Exception as exc:
        raise_openai_http_error(exc)

    return parse_category_review(output_text)
