"""Framework-independent transaction and categorization domain contracts."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _require_non_blank(value: str, field_name: str) -> str:
    if not value.strip():
        raise ValueError(f"{field_name} must not be blank")
    return value


class DecisionType(StrEnum):
    """The AI categorization outcomes supported in the initial workflow."""

    AI_SUGGESTION = "ai_suggestion"
    AI_PROPOSED_NEW_CATEGORY = "ai_proposed_new_category"
    UNRESOLVED = "unresolved"


class TransactionDirection(StrEnum):
    """The flow of money represented by a canonical transaction."""

    DEBIT = "debit"
    CREDIT = "credit"
    UNKNOWN = "unknown"


class TransactionIdentityQuality(StrEnum):
    """How reliably a canonical transaction can be identified and matched."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    INSUFFICIENT = "insufficient"


class SourceTransaction(BaseModel):
    """Transaction values preserved as received from a source."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    transaction_id: str
    date: str | None = None
    merchant: str | None = None
    statement: str | None = None
    amount: float | None = None
    original_category: str | None = None

    @field_validator("transaction_id")
    @classmethod
    def transaction_id_must_not_be_blank(cls, value: str) -> str:
        return _require_non_blank(value, "transaction_id")


class ManualCategorization(BaseModel):
    """A category explicitly selected by a user and therefore trusted."""

    model_config = ConfigDict(extra="forbid")

    category: str
    note: str | None = None

    @field_validator("category")
    @classmethod
    def category_must_not_be_blank(cls, value: str) -> str:
        return _require_non_blank(value, "category")


class CategorizationDecision(BaseModel):
    """The details and evidence of one AI categorization outcome."""

    model_config = ConfigDict(extra="forbid")

    decision_id: str
    decision_type: DecisionType
    suggested_category: str | None = None
    proposed_category: str | None = None
    reason: str
    supporting_memory_ids: list[str] = Field(default_factory=list)

    @field_validator("decision_id", "reason")
    @classmethod
    def required_text_must_not_be_blank(cls, value: str, info) -> str:
        return _require_non_blank(value, info.field_name)

    @model_validator(mode="after")
    def suggestion_contains_only_suggested_category(self) -> "CategorizationDecision":
        if self.decision_type is not DecisionType.AI_SUGGESTION:
            return self
        if not self.suggested_category or self.proposed_category:
            raise ValueError("AI suggestion must contain only suggested_category")
        return self

    @model_validator(mode="after")
    def proposal_contains_only_proposed_category(self) -> "CategorizationDecision":
        if self.decision_type is not DecisionType.AI_PROPOSED_NEW_CATEGORY:
            return self
        if not self.proposed_category or self.suggested_category:
            raise ValueError("AI category proposal must contain only proposed_category")
        return self

    @model_validator(mode="after")
    def unresolved_contains_no_category(self) -> "CategorizationDecision":
        if self.decision_type is not DecisionType.UNRESOLVED:
            return self
        if self.suggested_category or self.proposed_category:
            raise ValueError("unresolved AI decision cannot contain a category")
        return self


class CanonicalTransaction(BaseModel):
    """A processed transaction with canonical identity and categorization state."""

    model_config = ConfigDict(extra="forbid")

    source: SourceTransaction
    normalized_merchant: str | None = None
    normalized_statement: str | None = None
    direction: TransactionDirection
    identity_quality: TransactionIdentityQuality
    fingerprint: str | None = Field(default=None, min_length=1)
    ai_categorization: CategorizationDecision | None = None
    manual_categorization: ManualCategorization | None = None
