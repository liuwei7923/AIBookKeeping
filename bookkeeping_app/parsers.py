"""Parsing and normalization utilities for CSV input and model JSON output."""

import csv
import json
import re
from io import StringIO
from typing import Any

from fastapi import HTTPException, UploadFile

from bookkeeping_app.config import ALLOWED_CSV_CONTENT_TYPES

CONTROL_CHAR_PATTERN = re.compile(r"[\x00-\x1f\x7f]")


def sanitize_text(value: str | None) -> str | None:
    if value is None:
        return None

    cleaned = CONTROL_CHAR_PATTERN.sub("", value).strip()
    return cleaned or None


def normalize_amount(value: Any) -> float | None:
    if value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    if not isinstance(value, str):
        return None

    cleaned = value.strip().replace("$", "").replace(",", "")
    if not cleaned:
        return None

    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_json_array(raw_text: str) -> list[dict[str, Any]]:
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail="OpenAI response was not valid JSON") from exc

    if not isinstance(data, list):
        raise HTTPException(status_code=502, detail="OpenAI response was not a JSON array")

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
        raise HTTPException(status_code=400, detail="CSV file must include a header row")

    transactions = []
    for row in reader:
        if not row:
            continue

        transactions.append(
            {
                "date": find_csv_value(row, ["date", "transaction date", "posted date"]),
                "amount": normalize_amount(
                    find_csv_value(row, ["amount", "transaction amount", "value"])
                ),
                "merchant": find_csv_value(row, ["merchant", "description", "payee", "name"]),
                "category": find_csv_value(row, ["category"]),
            }
        )

    return transactions


def is_valid_csv_upload(file: UploadFile) -> bool:
    if file.content_type in ALLOWED_CSV_CONTENT_TYPES:
        return True

    filename = file.filename or ""
    return filename.lower().endswith(".csv")
