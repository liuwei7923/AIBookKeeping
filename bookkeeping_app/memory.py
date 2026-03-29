"""Helpers for normalizing, constructing, loading, and saving categorization memory."""

import json
import re
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
        normalized_merchant=normalized_merchant,
        amount=normalized_amount,
        direction=infer_direction(normalized_amount),
        original_category=sanitize_text(original_category),
        corrected_category=cleaned_category,
        source=source,
        notes=sanitize_text(notes),
    )


def ensure_memory_file(path: Path = CATEGORIZATION_MEMORY_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("[]", encoding="utf-8")


def load_categorization_memory(path: Path = CATEGORIZATION_MEMORY_PATH) -> list[CategorizationMemoryItem]:
    ensure_memory_file(path)
    raw_items = json.loads(path.read_text(encoding="utf-8"))
    return [CategorizationMemoryItem.model_validate(item) for item in raw_items]


def save_categorization_memory(
    items: list[CategorizationMemoryItem],
    path: Path = CATEGORIZATION_MEMORY_PATH,
) -> None:
    ensure_memory_file(path)
    payload = [item.model_dump(mode="json") for item in items]
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
