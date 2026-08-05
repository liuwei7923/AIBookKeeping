"""Pydantic schema definitions for persisted categorization memory items."""

from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from bookkeeping_app.domain_contracts import TransactionDirection, UserId


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


class CategorizationMemoryItem(BaseModel):
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
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)
    confidence: float = 1.0
    usage_count: int = 0
    last_matched_at: str | None = None
