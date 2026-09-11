"""Parsing utilities for CSV input and model JSON output."""

import csv
import json
from io import StringIO
from typing import Any

from fastapi import HTTPException

from bookkeeping_app.normalization import normalize_amount, sanitize_text


def parse_json_array(raw_text: str) -> list[dict[str, Any]]:
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=502, detail="OpenAI response was not valid JSON"
        ) from exc

    if not isinstance(data, list):
        raise HTTPException(
            status_code=502, detail="OpenAI response was not a JSON array"
        )

    return [item for item in data if isinstance(item, dict)]


def parse_transactions(raw_text: str) -> list[dict[str, Any]]:
    cleaned_transactions = []

    for item in parse_json_array(raw_text):
        cleaned_transactions.append(
            {
                "date": sanitize_text(item.get("date")),
                "amount": normalize_amount(item.get("amount")),
                "merchant": sanitize_text(item.get("merchant")),
                "category": sanitize_text(item.get("category")),
            }
        )

    return cleaned_transactions


def parse_category_review(raw_text: str) -> list[dict[str, Any]]:
    cleaned_reviews = []

    for item in parse_json_array(raw_text):
        cleaned_reviews.append(
            {
                "date": sanitize_text(item.get("date")),
                "amount": normalize_amount(item.get("amount")),
                "merchant": sanitize_text(item.get("merchant")),
                "original_category": sanitize_text(item.get("original_category")),
                "suggested_category": sanitize_text(item.get("suggested_category")),
                "reason": sanitize_text(item.get("reason")),
            }
        )

    return cleaned_reviews


def find_csv_value(row: dict[str, str], candidates: list[str]) -> str | None:
    normalized_row = {key.strip().lower(): value for key, value in row.items() if key}
    for candidate in candidates:
        value = normalized_row.get(candidate)
        if value is not None:
            return sanitize_text(value)
    return None


def parse_csv_transactions(csv_text: str) -> list[dict[str, Any]]:
    try:
        reader = csv.DictReader(StringIO(csv_text))
    except csv.Error as exc:
        raise HTTPException(status_code=400, detail="Could not read CSV file") from exc

    if not reader.fieldnames:
        raise HTTPException(
            status_code=400, detail="CSV file must include a header row"
        )

    transactions = []
    for row in reader:
        if not row:
            continue

        transactions.append(
            {
                "date": find_csv_value(
                    row,
                    ["date", "transaction date", "posted date", "date of transaction"],
                ),
                "amount": normalize_amount(
                    find_csv_value(
                        row, ["amount", "transaction amount", "value", "$ amount"]
                    )
                ),
                "merchant": find_csv_value(
                    row,
                    [
                        "merchant",
                        "description",
                        "payee",
                        "name",
                        "original statement",
                        "statement",
                        "merchant name or transaction description",
                    ],
                ),
                "category": find_csv_value(row, ["category"]),
            }
        )

    return transactions
