"""Public contracts for trusted categorization-memory persistence."""

from collections.abc import Sequence
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bookkeeping_app.domain_contracts import (
    CanonicalTransaction,
    TransactionDirection,
    UserId,
)


class FingerprintConflictPolicy(StrEnum):
    """Allowed behavior when a fingerprint has a different trusted category."""

    REJECT = "reject"
    REPLACE_TRUSTED_CATEGORY = "replace_trusted_category"


class MemoryWriteStatus(StrEnum):
    """Outcome of recording one trusted transaction."""

    CREATED = "created"
    DUPLICATE = "duplicate"
    CONFLICT = "conflict"
    REPLACED = "replaced"
    REJECTED = "rejected"


class RecordTrustedCommand(BaseModel):
    """One request to record a trusted canonical transaction."""

    model_config = ConfigDict(extra="forbid")

    transaction: CanonicalTransaction
    conflict_policy: FingerprintConflictPolicy = FingerprintConflictPolicy.REJECT
    override_reason: str | None = None

    @model_validator(mode="after")
    def replacement_requires_reason(self) -> "RecordTrustedCommand":
        if self.conflict_policy is FingerprintConflictPolicy.REPLACE_TRUSTED_CATEGORY:
            if self.override_reason is None or not self.override_reason.strip():
                raise ValueError(
                    "replacing a trusted category requires override_reason"
                )
        return self


class MemoryWriteItemResult(BaseModel):
    """Observable result of recording one transaction."""

    model_config = ConfigDict(extra="forbid")

    transaction_id: UUID
    status: MemoryWriteStatus
    conflicting_transaction_ids: tuple[UUID, ...] = ()
    replaced_transaction_id: UUID | None = None
    reason: str | None = None


class MemoryWriteResult(BaseModel):
    """Ordered outcomes for one atomic recording request."""

    model_config = ConfigDict(extra="forbid")

    items: tuple[MemoryWriteItemResult, ...]

    def count(self, status: MemoryWriteStatus) -> int:
        return sum(item.status is status for item in self.items)


class MemoryQuery(BaseModel):
    """User-scoped fields used for persistence-efficient memory filtering."""

    model_config = ConfigDict(extra="forbid")

    user_id: UserId
    normalized_merchant: str = Field(min_length=1)
    direction: TransactionDirection


class MemoryListQuery(BaseModel):
    """Cursor-based request for one user's trusted memory."""

    model_config = ConfigDict(extra="forbid")

    user_id: UserId
    limit: int = Field(default=100, ge=1, le=500)
    cursor: str | None = None


class MemoryPage(BaseModel):
    """One stable page of trusted canonical transactions."""

    model_config = ConfigDict(extra="forbid")

    transactions: tuple[CanonicalTransaction, ...]
    next_cursor: str | None = None


@runtime_checkable
class MemoryStore(Protocol):
    """Persistence seam for user-owned trusted canonical transactions."""

    def record_trusted(
        self,
        commands: Sequence[RecordTrustedCommand],
    ) -> MemoryWriteResult:
        """Atomically record trusted canonical transactions."""
        ...

    def find_relevant(
        self,
        query: MemoryQuery,
    ) -> tuple[CanonicalTransaction, ...]:
        """Find trusted transactions for the same user, merchant, and direction."""
        ...

    def list_for_user(self, query: MemoryListQuery) -> MemoryPage:
        """List one user's trusted transactions with stable cursor pagination."""
        ...
