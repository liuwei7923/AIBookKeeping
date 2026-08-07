"""Framework-independent user, transaction, and categorization contracts."""

from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

UserId = UUID


def _require_non_blank(value: str, field_name: str) -> str:
    if not value.strip():
        raise ValueError(f"{field_name} must not be blank")
    return value


class CategorizationType(StrEnum):
    """Whether AI suggested a known category, proposed one, or withheld one."""

    SUGGESTED = "suggested"
    PROPOSED = "proposed"
    NOT_AVAILABLE = "not_available"


class TransactionDirection(StrEnum):
    """The flow of money represented by a canonical transaction."""

    DEBIT = "debit"
    CREDIT = "credit"


class TransactionIdentityQuality(StrEnum):
    """How reliably a canonical transaction can be identified and matched."""

    COMPLETE = "complete"
    PARTIAL = "partial"


class TrustedCategorizationSource(StrEnum):
    """How a categorization became trusted by the application."""

    MANUAL_CLASSIFICATION = "manual_classification"
    CONFIRMED_AI_SUGGESTION = "confirmed_ai_suggestion"
    CORRECTED_AI_SUGGESTION = "corrected_ai_suggestion"


class User(BaseModel):
    """A person with a stable identity inside the bookkeeping application."""

    model_config = ConfigDict(extra="forbid")

    user_id: UserId = Field(default_factory=uuid4)
    display_name: str | None = None

    @field_validator("display_name")
    @classmethod
    def display_name_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_non_blank(value, "display_name").strip()


class SourceTransaction(BaseModel):
    """Transaction values preserved as received from a source."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    user_id: UserId
    transaction_id: UUID = Field(default_factory=uuid4)
    date: str | None = None
    merchant: str | None = None
    statement: str | None = None
    amount: Decimal | None = None
    original_category: str | None = None


class TrustedCategorization(BaseModel):
    """A category trusted through an explicit user decision."""

    model_config = ConfigDict(extra="forbid")

    category: str
    source: TrustedCategorizationSource
    note: str | None = None

    @field_validator("category")
    @classmethod
    def category_must_not_be_blank(cls, value: str) -> str:
        return _require_non_blank(value, "category")


class AICategorization(BaseModel):
    """The details and evidence of one AI categorization outcome."""

    model_config = ConfigDict(extra="forbid")

    decision_id: str
    categorization_type: CategorizationType
    category: str | None = None
    reason: str
    supporting_memory_ids: list[str] = Field(default_factory=list)

    @field_validator("decision_id", "reason")
    @classmethod
    def required_text_must_not_be_blank(cls, value: str, info: ValidationInfo) -> str:
        return _require_non_blank(value, info.field_name)

    @field_validator("category")
    @classmethod
    def category_must_not_be_blank(
        cls,
        value: str | None,
        info: ValidationInfo,
    ) -> str | None:
        if value is None:
            return None
        return _require_non_blank(value, info.field_name)

    @field_validator("supporting_memory_ids")
    @classmethod
    def supporting_memory_ids_must_not_be_blank(cls, values: list[str]) -> list[str]:
        return [_require_non_blank(value, "supporting_memory_id") for value in values]

    @model_validator(mode="after")
    def category_matches_categorization_type(self) -> "AICategorization":
        if self.categorization_type in {
            CategorizationType.SUGGESTED,
            CategorizationType.PROPOSED,
        }:
            if self.category is None:
                raise ValueError(
                    "suggested and proposed categorizations need a category"
                )
        elif self.category is not None:
            raise ValueError("not_available categorization cannot contain a category")
        return self


class CanonicalTransaction(BaseModel):
    """A processed transaction with canonical identity and categorization state."""

    model_config = ConfigDict(extra="forbid")

    source: SourceTransaction
    normalized_merchant: str | None = None
    normalized_statement: str | None = None
    direction: TransactionDirection
    identity_quality: TransactionIdentityQuality
    fingerprint: str = Field(min_length=1)
    ai_categorization: AICategorization | None = None
    trusted_categorization: TrustedCategorization | None = None
