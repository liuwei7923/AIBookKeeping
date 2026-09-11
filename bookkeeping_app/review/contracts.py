"""Request and query contracts for transaction review workflows."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from bookkeeping_app.domain_contracts import ReviewResolution, UserId


class TransactionReviewSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")
    transaction_id: UUID
    reviewed_category: str | None = None

    @field_validator("reviewed_category")
    @classmethod
    def category_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip():
            raise ValueError("reviewed_category must not be blank")
        return value.strip()


class TransactionReviewBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[TransactionReviewSubmission] = Field(min_length=1)


class TransactionItemQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: UserId
    resolution: ReviewResolution | None = None
