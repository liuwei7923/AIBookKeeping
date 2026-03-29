"""Helpers for normalizing, constructing, loading, and saving categorization memory."""

import csv
import json
import re
from io import StringIO
from pathlib import Path

from bookkeeping_app.config import CATEGORIZATION_MEMORY_PATH
from bookkeeping_app.memory_schema import CategorizationMemoryItem
from bookkeeping_app.parsers import normalize_amount, sanitize_text

MULTISPACE_PATTERN = re.compile(r"\s+")
PUNCTUATION_PATTERN = re.compile(r"[^a-z0-9\s]")


def normalize_merchant(value: str | None) -> str | None:
    cleaned = sanitize_text(value)
    if cleaned is None:
        return None

    lowered = cleaned.lower()
    without_punctuation = PUNCTUATION_PATTERN.sub(" ", lowered)
    collapsed = MULTISPACE_PATTERN.sub(" ", without_punctuation).strip()
    return collapsed or None


def infer_direction(amount: float | None) -> str | None:
    if amount is None:
        return None
    return "income" if amount >= 0 else "expense"


def build_memory_item(
    *,
    merchant: str,
    corrected_category: str,
    amount: float | str | None = None,
    date: str | None = None,
    statement: str | None = None,
    original_category: str | None = None,
    notes: str | None = None,
    source: str = "imported_labeled_history",
) -> CategorizationMemoryItem:
    cleaned_merchant = sanitize_text(merchant)
    normalized_merchant = normalize_merchant(merchant)
    cleaned_category = sanitize_text(corrected_category)

    if cleaned_merchant is None:
        raise ValueError("merchant is required")

    if cleaned_category is None:
        raise ValueError("corrected_category is required")

    normalized_amount = normalize_amount(amount)

    return CategorizationMemoryItem(
        date=sanitize_text(date),
        merchant=cleaned_merchant,
        statement=sanitize_text(statement),
        normalized_merchant=normalized_merchant,
        amount=normalized_amount,
        direction=infer_direction(normalized_amount),
        original_category=sanitize_text(original_category),
        corrected_category=cleaned_category,
        source=source,
        notes=sanitize_text(notes),
    )


def parse_memory_csv(csv_text: str) -> list[CategorizationMemoryItem]:
    reader = csv.DictReader(StringIO(csv_text))
    if not reader.fieldnames:
        raise ValueError("CSV file must include a header row")

    # TODO: Consider mapping currently ignored CSV fields such as Account,
    # Tags, and Owner into the memory schema once we
    # define how they should influence retrieval, merchant normalization,
    # and category decisions.
    items: list[CategorizationMemoryItem] = []
    for row in reader:
        if not row:
            continue

        category = find_memory_csv_value(row, ["category", "corrected_category"])
        merchant = find_memory_csv_value(row, ["merchant", "description", "payee", "name"])

        if merchant is None or category is None:
            continue

        items.append(
            build_memory_item(
                merchant=merchant,
                corrected_category=category,
                amount=find_memory_csv_value(row, ["amount", "transaction amount", "value"]),
                date=find_memory_csv_value(row, ["date", "transaction date", "posted date"]),
                statement=find_memory_csv_value(row, ["original statement", "statement"]),
                original_category=find_memory_csv_value(row, ["original_category"]),
                notes=find_memory_csv_value(row, ["notes"]),
            )
        )

    return items


def find_memory_csv_value(row: dict[str, str], candidates: list[str]) -> str | None:
    normalized_row = {key.strip().lower(): value for key, value in row.items() if key}
    for candidate in candidates:
        value = normalized_row.get(candidate)
        if value is not None:
            return sanitize_text(value)
    return None


def import_categorization_memory_csv(
    csv_text: str,
    path: Path | None = None,
) -> dict[str, int]:
    imported_items = parse_memory_csv(csv_text)
    existing_items = load_categorization_memory(path)
    combined_items = existing_items + imported_items
    save_categorization_memory(combined_items, path)

    return {
        "imported": len(imported_items),
        "skipped": 0,
    }


def resolve_memory_path(path: Path | None = None) -> Path:
    return path or CATEGORIZATION_MEMORY_PATH


def ensure_memory_file(path: Path | None = None) -> None:
    path = resolve_memory_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("[]", encoding="utf-8")


def load_categorization_memory(path: Path | None = None) -> list[CategorizationMemoryItem]:
    path = resolve_memory_path(path)
    ensure_memory_file(path)
    raw_items = json.loads(path.read_text(encoding="utf-8"))
    return [CategorizationMemoryItem.model_validate(item) for item in raw_items]


def save_categorization_memory(
    items: list[CategorizationMemoryItem],
    path: Path | None = None,
) -> None:
    path = resolve_memory_path(path)
    ensure_memory_file(path)
    payload = [item.model_dump(mode="json") for item in items]
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
