"""Legacy CSV memory flow retained until HTTP routes adopt ``MemoryStore``.

New domain code must use the Memory Store interface. These helpers preserve the
current public HTTP behavior without inventing an implicit user identity.
"""

import csv
import json
import re
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from bookkeeping_app.config import CATEGORIZATION_MEMORY_PATH
from bookkeeping_app.domain_contracts import TransactionDirection, UserId
from bookkeeping_app.parsers import normalize_amount, sanitize_text

MULTISPACE_PATTERN = re.compile(r"\s+")
PUNCTUATION_PATTERN = re.compile(r"[^a-z0-9\s]")


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


class CategorizationMemoryItem(BaseModel):
    """Deprecated flat persistence model used only by the current HTTP routes."""

    model_config = ConfigDict(extra="forbid")

    user_id: UserId
    id: str = Field(default_factory=lambda: str(uuid4()))
    date: str | None = None
    merchant: str
    statement: str | None = None
    normalized_merchant: str
    amount: float | None = None
    direction: TransactionDirection | None = None
    original_category: str | None = None
    corrected_category: str
    source: str = Field(
        default="imported_labeled_history",
        description=(
            "Legacy memory-item provenance; replaced by "
            "CanonicalTransaction.trusted_categorization.source"
        ),
    )
    notes: str | None = None
    created_at: str = Field(default_factory=_utc_now_iso)
    updated_at: str = Field(default_factory=_utc_now_iso)
    confidence: float = 1.0
    usage_count: int = 0
    last_matched_at: str | None = None


def normalize_merchant(value: str | None) -> str | None:
    cleaned = sanitize_text(value)
    if cleaned is None:
        return None

    lowered = cleaned.lower()
    without_punctuation = PUNCTUATION_PATTERN.sub(" ", lowered)
    collapsed = MULTISPACE_PATTERN.sub(" ", without_punctuation).strip()
    return collapsed or None


def infer_direction(amount: float | None) -> TransactionDirection | None:
    if amount is None:
        return None
    return TransactionDirection.CREDIT if amount >= 0 else TransactionDirection.DEBIT


def build_memory_item(
    *,
    user_id: UserId,
    merchant: str,
    corrected_category: str,
    amount: float | str | None = None,
    date: str | None = None,
    statement: str | None = None,
    original_category: str | None = None,
    notes: str | None = None,
    # Legacy memory-item provenance. TrustedCategorizationSource replaces this
    # once the memory routes migrate to CanonicalTransaction persistence.
    source: str = "imported_labeled_history",
) -> CategorizationMemoryItem:
    cleaned_merchant = sanitize_text(merchant)
    normalized_merchant = normalize_merchant(merchant)
    cleaned_category = sanitize_text(corrected_category)

    if cleaned_merchant is None:
        raise ValueError("merchant is required")
    if cleaned_category is None:
        raise ValueError("corrected_category is required")
    assert normalized_merchant is not None

    normalized_amount = normalize_amount(amount)
    return CategorizationMemoryItem(
        user_id=user_id,
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


def parse_memory_csv(
    csv_text: str,
    user_id: UserId,
) -> list[CategorizationMemoryItem]:
    reader = csv.DictReader(StringIO(csv_text))
    if not reader.fieldnames:
        raise ValueError("CSV file must include a header row")

    items: list[CategorizationMemoryItem] = []
    for row in reader:
        if not row:
            continue

        category = find_memory_csv_value(row, ["category", "corrected_category"])
        merchant = find_memory_csv_value(
            row, ["merchant", "description", "payee", "name"]
        )
        if merchant is None or category is None:
            continue

        items.append(
            build_memory_item(
                user_id=user_id,
                merchant=merchant,
                corrected_category=category,
                amount=find_memory_csv_value(
                    row, ["amount", "transaction amount", "value"]
                ),
                date=find_memory_csv_value(
                    row, ["date", "transaction date", "posted date"]
                ),
                statement=find_memory_csv_value(
                    row, ["original statement", "statement"]
                ),
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
    user_id: UserId,
    path: Path | None = None,
) -> dict[str, int]:
    imported_items = parse_memory_csv(csv_text, user_id)
    existing_items = _load_all_categorization_memory(path)
    combined_items = existing_items + imported_items
    save_categorization_memory(combined_items, path)

    return {
        "imported": len(imported_items),
        "skipped": 0,
    }


def _resolve_memory_path(path: Path | None = None) -> Path:
    return path or CATEGORIZATION_MEMORY_PATH


def _ensure_memory_file(path: Path | None = None) -> None:
    resolved = _resolve_memory_path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    if not resolved.exists():
        resolved.write_text("[]", encoding="utf-8")


def load_categorization_memory(
    user_id: UserId,
    path: Path | None = None,
) -> list[CategorizationMemoryItem]:
    return [
        item
        for item in _load_all_categorization_memory(path)
        if item.user_id == user_id
    ]


def _load_all_categorization_memory(
    path: Path | None = None,
) -> list[CategorizationMemoryItem]:
    resolved = _resolve_memory_path(path)
    _ensure_memory_file(resolved)
    raw_items = json.loads(resolved.read_text(encoding="utf-8"))
    return [CategorizationMemoryItem.model_validate(item) for item in raw_items]


def save_categorization_memory(
    items: list[CategorizationMemoryItem],
    path: Path | None = None,
) -> None:
    resolved = _resolve_memory_path(path)
    _ensure_memory_file(resolved)
    payload = [item.model_dump(mode="json") for item in items]
    resolved.write_text(json.dumps(payload, indent=2), encoding="utf-8")
