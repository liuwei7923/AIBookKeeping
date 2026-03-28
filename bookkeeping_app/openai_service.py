import base64
import json
import logging
import os
from typing import Any

from fastapi import HTTPException
from openai import APIError, APIStatusError, OpenAI

from bookkeeping_app.config import MAX_CATEGORY_CONTEXT_ITEMS, MODEL_NAME
from bookkeeping_app.metrics import metrics
from bookkeeping_app.parsers import parse_category_review, parse_transactions
from bookkeeping_app.prompts import CATEGORY_REVIEW_PROMPT, SYSTEM_PROMPT

logger = logging.getLogger("bookkeeping_app")


def get_openai_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY is not set")
    return OpenAI(api_key=api_key)


def raise_openai_http_error(exc: Exception) -> None:
    if isinstance(exc, APIStatusError):
        logger.error("OpenAI API status error status=%s message=%s", exc.status_code, str(exc))
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
        logger.error("OpenAI API error message=%s", str(exc))
        raise HTTPException(status_code=502, detail="OpenAI API request failed") from exc

    logger.exception("Unexpected error while calling OpenAI")
    raise HTTPException(status_code=502, detail="Unexpected error while calling OpenAI") from exc


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
                "original_category": transaction.get("category"),
            }
            for transaction in transactions
        ]
    }

    if category_history:
        payload["manual_override_examples"] = category_history[:MAX_CATEGORY_CONTEXT_ITEMS]

    return (
        "Review these transactions and suggest corrected categories when needed.\n\n"
        f"{json.dumps(payload)}"
    )


def extract_transactions_from_image(image_bytes: bytes, content_type: str) -> list[dict[str, Any]]:
    base64_image = base64.b64encode(image_bytes).decode("utf-8")
    image_url = f"data:{content_type};base64,{base64_image}"

    try:
        client = get_openai_client()
        metrics.record_openai_request("extract-transactions")
        response = client.responses.create(
            model=MODEL_NAME,
            input=[
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": SYSTEM_PROMPT}],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "Extract all visible transactions from this image.",
                        },
                        {
                            "type": "input_image",
                            "image_url": image_url,
                        },
                    ],
                },
            ],
        )
    except Exception as exc:
        raise_openai_http_error(exc)

    output_text = getattr(response, "output_text", "").strip()
    if not output_text:
        raise HTTPException(status_code=502, detail="OpenAI returned an empty response")

    return parse_transactions(output_text)


def review_transaction_categories(
    transactions: list[dict[str, Any]],
    category_history: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if not transactions:
        return []

    try:
        client = get_openai_client()
        metrics.record_openai_request("recategorize-transactions-csv")
        response = client.responses.create(
            model=MODEL_NAME,
            input=[
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": CATEGORY_REVIEW_PROMPT}],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": build_category_review_input(transactions, category_history),
                        }
                    ],
                },
            ],
        )
    except Exception as exc:
        raise_openai_http_error(exc)

    output_text = getattr(response, "output_text", "").strip()
    if not output_text:
        raise HTTPException(status_code=502, detail="OpenAI returned an empty response")

    return parse_category_review(output_text)
