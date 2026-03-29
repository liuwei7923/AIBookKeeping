"""Pydantic schema definitions for persisted categorization memory items."""

from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


class CategorizationMemoryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid4()))
    date: str | None = None
    merchant: str
    normalized_merchant: str
    amount: float | None = None
    direction: str | None = None
    original_category: str | None = None
    corrected_category: str
    source: str = "imported_labeled_history"
    notes: str | None = None
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)
    confidence: float = 1.0
    usage_count: int = 0
    last_matched_at: str | None = None
