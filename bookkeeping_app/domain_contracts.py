"""Framework-independent domain contracts for Phase 1 recategorization."""

from enum import StrEnum

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)


def _require_non_blank(value: str, field_name: str) -> str:
    if not value.strip():
        raise ValueError(f"{field_name} must not be blank")
    return value


class TransactionDirection(StrEnum):
    """The flow of money represented by a transaction."""

    DEBIT = "debit"
    CREDIT = "credit"
    UNKNOWN = "unknown"


class TransactionIdentityQuality(StrEnum):
    """How reliably the transaction can be identified and matched."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    INSUFFICIENT = "insufficient"


class DecisionType(StrEnum):
    """Every categorization path available in Phase 1."""

    EXACT_STATEMENT_MEMORY_MATCH = "exact_statement_memory_match"
    MERCHANT_CONSENSUS = "merchant_consensus"
    AI_SUGGESTION_WITH_RELEVANT_MEMORY = "ai_suggestion_with_relevant_memory"
    AI_SUGGESTION_WITHOUT_RELEVANT_MEMORY = "ai_suggestion_without_relevant_memory"
    AI_PROPOSED_NEW_CATEGORY = "ai_proposed_new_category"
    UNRESOLVED = "unresolved"


class DecisionConfidence(StrEnum):
    """The strength of evidence supporting a categorization decision."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class BatchStatus(StrEnum):
    """The externally observable state of a Phase 1 batch."""

    COMPLETED = "completed"
    APPROVAL_REQUIRED = "approval_required"


class CanonicalTransaction(BaseModel):
    """A source transaction normalized for categorization within one request."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    transaction_id: str
    date: str | None = None
    merchant: str | None = None
    statement: str | None = None
    amount: float | None = None
    original_category: str | None = None
    normalized_merchant: str | None = None
    normalized_statement: str | None = None
    direction: TransactionDirection
    identity_quality: TransactionIdentityQuality
    fingerprint: str | None = Field(default=None, min_length=1)

    @field_validator("transaction_id")
    @classmethod
    def transaction_id_must_not_be_blank(cls, value: str) -> str:
        return _require_non_blank(value, "transaction_id")


class CategorizationDecision(BaseModel):
    """The outcome and evidence of categorizing one canonical transaction."""

    model_config = ConfigDict(extra="forbid")

    transaction_id: str
    decision_type: DecisionType
    accepted_category: str | None = None
    suggested_category: str | None = None
    proposed_category: str | None = None
    needs_review: bool
    confidence: DecisionConfidence | None = None
    reason: str = Field(min_length=1)
    supporting_memory_ids: list[str] = Field(default_factory=list)

    @field_validator("transaction_id")
    @classmethod
    def transaction_id_must_not_be_blank(cls, value: str) -> str:
        return _require_non_blank(value, "transaction_id")

    @model_validator(mode="after")
    def deterministic_decision_has_only_accepted_category(self) -> "CategorizationDecision":
        deterministic_types = {
            DecisionType.EXACT_STATEMENT_MEMORY_MATCH,
            DecisionType.MERCHANT_CONSENSUS,
        }
        if self.decision_type not in deterministic_types:
            return self
        if not self.accepted_category:
            raise ValueError("deterministic decision requires accepted_category")
        if self.suggested_category or self.proposed_category:
            raise ValueError("deterministic decision may only contain accepted_category")
        if self.needs_review:
            raise ValueError("deterministic decision must not need review")
        return self

    @model_validator(mode="after")
    def ai_decision_has_reviewable_category(self) -> "CategorizationDecision":
        suggestion_types = {
            DecisionType.AI_SUGGESTION_WITH_RELEVANT_MEMORY,
            DecisionType.AI_SUGGESTION_WITHOUT_RELEVANT_MEMORY,
        }
        ai_types = suggestion_types | {DecisionType.AI_PROPOSED_NEW_CATEGORY}
        if self.decision_type not in ai_types:
            return self
        if not self.needs_review:
            raise ValueError("every AI decision must need review")
        if self.accepted_category:
            raise ValueError("AI decisions cannot contain accepted_category")
        if self.decision_type in suggestion_types:
            if not self.suggested_category or self.proposed_category:
                raise ValueError("AI suggestion must contain only suggested_category")
        elif not self.proposed_category or self.suggested_category:
            raise ValueError("AI-proposed category must contain only proposed_category")
        if (
            self.decision_type is DecisionType.AI_SUGGESTION_WITH_RELEVANT_MEMORY
            and not self.supporting_memory_ids
        ):
            raise ValueError("AI suggestion with relevant memory requires supporting memory IDs")
        if (
            self.decision_type is DecisionType.AI_SUGGESTION_WITHOUT_RELEVANT_MEMORY
            and self.supporting_memory_ids
        ):
            raise ValueError("AI suggestion without relevant memory cannot cite memory IDs")
        return self

    @model_validator(mode="after")
    def unresolved_decision_has_no_category(self) -> "CategorizationDecision":
        if self.decision_type is not DecisionType.UNRESOLVED:
            return self
        if self.accepted_category or self.suggested_category or self.proposed_category:
            raise ValueError("unresolved decision cannot contain a category")
        if not self.needs_review:
            raise ValueError("unresolved decision must need review")
        return self


class RecategorizationResult(BaseModel):
    """A transaction and its decision at the transaction's original position."""

    model_config = ConfigDict(extra="forbid")

    position: int = Field(ge=0)
    transaction: CanonicalTransaction
    decision: CategorizationDecision

    @model_validator(mode="after")
    def transaction_and_decision_ids_match(self) -> "RecategorizationResult":
        if self.transaction.transaction_id != self.decision.transaction_id:
            raise ValueError("transaction and decision IDs must match")
        return self


class RecategorizationBatch(BaseModel):
    """An ordered Phase 1 recategorization response with derived summary counts."""

    model_config = ConfigDict(extra="forbid")

    batch_id: str = Field(min_length=1)
    status: BatchStatus
    results: list[RecategorizationResult]
    openai_request_count: int = Field(ge=0)

    @field_validator("batch_id")
    @classmethod
    def batch_id_must_not_be_blank(cls, value: str) -> str:
        return _require_non_blank(value, "batch_id")

    @model_validator(mode="after")
    def results_follow_input_order(self) -> "RecategorizationBatch":
        positions = [result.position for result in self.results]
        if positions != list(range(len(self.results))):
            raise ValueError("result positions must preserve zero-based input order")
        transaction_ids = [result.transaction.transaction_id for result in self.results]
        if len(transaction_ids) != len(set(transaction_ids)):
            raise ValueError("transaction IDs must be unique within a batch")
        return self

    @computed_field
    @property
    def total_count(self) -> int:
        return len(self.results)

    @computed_field
    @property
    def deterministic_count(self) -> int:
        deterministic_types = {
            DecisionType.EXACT_STATEMENT_MEMORY_MATCH,
            DecisionType.MERCHANT_CONSENSUS,
        }
        return sum(
            result.decision.decision_type in deterministic_types for result in self.results
        )

    @computed_field
    @property
    def ai_reviewed_count(self) -> int:
        ai_types = {
            DecisionType.AI_SUGGESTION_WITH_RELEVANT_MEMORY,
            DecisionType.AI_SUGGESTION_WITHOUT_RELEVANT_MEMORY,
            DecisionType.AI_PROPOSED_NEW_CATEGORY,
        }
        return sum(result.decision.decision_type in ai_types for result in self.results)

    @computed_field
    @property
    def unknown_count(self) -> int:
        return sum(
            result.decision.decision_type is DecisionType.UNRESOLVED for result in self.results
        )

    @computed_field
    @property
    def needs_review_count(self) -> int:
        return sum(result.decision.needs_review for result in self.results)

    @computed_field
    @property
    def approval_required(self) -> bool:
        return self.status is BatchStatus.APPROVAL_REQUIRED
