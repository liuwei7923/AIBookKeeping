"""Framework-independent transaction review behavior."""

from uuid import UUID

from bookkeeping_app.domain_contracts import (
    TrustedCategorization,
    TrustedCategorizationSource,
    UserId,
)
from bookkeeping_app.memory import (
    MemoryStore,
    MemoryWriteStatus,
    RecordTrustedCommand,
)
from bookkeeping_app.review.contracts import (
    AcceptAiRequest,
    CategoryOutcome,
    CorrectRequest,
    EvidenceCondition,
    KeepUnknownRequest,
    ReviewRequirement,
    ReviewResolution,
    ReviewResolutionRequest,
    TransactionItem,
    TransactionItemQuery,
)
from bookkeeping_app.review.session import EphemeralReviewSession


class ReviewNotFoundError(Exception):
    pass


class InvalidReviewActionError(Exception):
    pass


class ReviewConflictError(Exception):
    pass


class MemoryPromotionError(Exception):
    pass


class ReviewService:
    def __init__(
        self, review_session: EphemeralReviewSession, memory_store: MemoryStore
    ) -> None:
        self._review_session = review_session
        self._memory_store = memory_store

    def list_items(
        self, user_id: UserId, resolution: ReviewResolution | None = None
    ) -> tuple[TransactionItem, ...]:
        return tuple(
            item
            for item in self._review_session.list_for_user(
                TransactionItemQuery(user_id=user_id, resolution=resolution)
            )
            if item.review_requirement is ReviewRequirement.NEEDS_REVIEW
        )

    def get_item(self, user_id: UserId, transaction_id: UUID) -> TransactionItem:
        item = self._review_session.get(transaction_id)
        if (
            item is None
            or item.user_id != user_id
            or item.review_requirement is not ReviewRequirement.NEEDS_REVIEW
        ):
            raise ReviewNotFoundError
        return item

    def resolve(
        self,
        user_id: UserId,
        transaction_id: UUID,
        request: ReviewResolutionRequest,
    ) -> TransactionItem:
        item = self.get_item(user_id, transaction_id)
        desired_resolution, category = self._desired_result(item, request)

        if item.resolution is not ReviewResolution.PENDING:
            if (
                item.resolution is desired_resolution
                and item.resolved_category == category
            ):
                return item
            raise ReviewConflictError("review item already has a different resolution")

        if desired_resolution is ReviewResolution.KEPT_UNKNOWN:
            resolved = item.model_copy(
                update={"resolution": desired_resolution, "resolved_category": None}
            )
            self._review_session.replace(resolved)
            return resolved

        assert category is not None
        source = (
            TrustedCategorizationSource.CONFIRMED_AI_SUGGESTION
            if desired_resolution is ReviewResolution.CONFIRMED
            else TrustedCategorizationSource.CORRECTED_AI_SUGGESTION
        )
        trusted_transaction = item.transaction.model_copy(
            update={
                "trusted_categorization": TrustedCategorization(
                    category=category,
                    source=source,
                    note="Resolved through transaction review.",
                )
            }
        )
        result = self._memory_store.record_trusted(
            [RecordTrustedCommand(transaction=trusted_transaction)]
        )
        status = result.items[0].status
        if status not in {MemoryWriteStatus.CREATED, MemoryWriteStatus.DUPLICATE}:
            raise MemoryPromotionError(
                result.items[0].reason or f"categorization memory write {status}"
            )

        resolved = item.model_copy(
            update={
                "transaction": trusted_transaction,
                "resolution": desired_resolution,
                "resolved_category": category,
            }
        )
        self._review_session.replace(resolved)
        return resolved

    @staticmethod
    def _desired_result(
        item: TransactionItem, request: ReviewResolutionRequest
    ) -> tuple[ReviewResolution, str | None]:
        if isinstance(request, KeepUnknownRequest):
            return ReviewResolution.KEPT_UNKNOWN, None
        if isinstance(request, CorrectRequest):
            return ReviewResolution.CORRECTED, request.category

        assert isinstance(request, AcceptAiRequest)
        if item.evidence_condition is EvidenceCondition.CONFLICTING:
            raise InvalidReviewActionError("conflicting evidence requires correction")
        decision = item.transaction.ai_categorization
        if item.category_outcome is CategoryOutcome.SUGGESTED and decision is not None:
            return ReviewResolution.CONFIRMED, decision.category
        if item.category_outcome is CategoryOutcome.PROPOSED and decision is not None:
            return ReviewResolution.CONFIRMED, decision.category
        raise InvalidReviewActionError(
            "accept_ai requires a suggested or proposed AI category"
        )
