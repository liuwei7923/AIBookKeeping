"""Domain contracts for user-owned transaction review."""

from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

from bookkeeping_app.domain_contracts import CanonicalTransaction, DecisionType, UserId


class CategoryOutcome(StrEnum):
    ACCEPTED = "accepted"
    SUGGESTED = "suggested"
    PROPOSED = "proposed"
    UNKNOWN = "unknown"


class ReviewRequirement(StrEnum):
    NEEDS_REVIEW = "needs_review"
    NO_REVIEW_REQUIRED = "no_review_required"


class ReviewResolution(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CORRECTED = "corrected"
    KEPT_UNKNOWN = "kept_unknown"


class EvidenceCondition(StrEnum):
    SUPPORTING = "supporting"
    INSUFFICIENT = "insufficient"
    CONFLICTING = "conflicting"


class TransactionItem(BaseModel):
    """A canonical transaction together with its human-review state."""

    model_config = ConfigDict(extra="forbid")

    transaction: CanonicalTransaction
    review_requirement: ReviewRequirement
    resolution: ReviewResolution = ReviewResolution.PENDING
    evidence_condition: EvidenceCondition
    resolved_category: str | None = None

    @property
    def transaction_id(self) -> UUID:
        return self.transaction.source.transaction_id

    @property
    def user_id(self) -> UserId:
        return self.transaction.source.user_id

    @computed_field
    @property
    def category_outcome(self) -> CategoryOutcome:
        """Derive the outcome from preserved canonical categorization provenance."""
        decision = self.transaction.ai_categorization
        if decision is not None:
            if decision.decision_type is DecisionType.AI_SUGGESTION:
                return CategoryOutcome.SUGGESTED
            if decision.decision_type is DecisionType.AI_PROPOSED_NEW_CATEGORY:
                return CategoryOutcome.PROPOSED
            return CategoryOutcome.UNKNOWN
        if self.transaction.trusted_categorization is not None:
            return CategoryOutcome.ACCEPTED
        return CategoryOutcome.UNKNOWN


class AcceptAiRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["accept_ai"]


class CorrectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["correct"]
    category: str

    @field_validator("category")
    @classmethod
    def category_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("category must not be blank")
        return value.strip()


class KeepUnknownRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["keep_unknown"]


ReviewResolutionRequest = Annotated[
    AcceptAiRequest | CorrectRequest | KeepUnknownRequest,
    Field(discriminator="action"),
]


class TransactionItemQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: UserId
    resolution: ReviewResolution | None = None
