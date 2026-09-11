"""Framework-independent transaction review behavior."""

from datetime import UTC, datetime
from uuid import UUID

from bookkeeping_app.domain_contracts import (
    CategoryOutcome,
    EvidenceCondition,
    ReviewRecord,
    ReviewRequirement,
    ReviewResolution,
    TransactionItem,
    TrustedCategorization,
    TrustedCategorizationSource,
    UserId,
)
from bookkeeping_app.memory import MemoryStore, MemoryWriteStatus, RecordTrustedCommand
from bookkeeping_app.review.contracts import (
    TransactionItemQuery,
    TransactionReviewSubmission,
)
from bookkeeping_app.review.record_store import ReviewRecordStore
from bookkeeping_app.review.session import EphemeralReviewSession


class ReviewNotFoundError(Exception):
    pass


class InvalidReviewError(Exception):
    pass


class ReviewConflictError(Exception):
    pass


class MemoryPromotionError(Exception):
    pass


class ReviewService:
    def __init__(
        self,
        review_session: EphemeralReviewSession,
        review_store: ReviewRecordStore,
        memory_store: MemoryStore,
    ) -> None:
        self._review_session = review_session
        self._review_store = review_store
        self._memory_store = memory_store

    def list_todo(self, user_id: UserId) -> tuple[TransactionItem, ...]:
        return tuple(
            item
            for item in self._review_session.list_for_user(
                TransactionItemQuery(
                    user_id=user_id, resolution=ReviewResolution.PENDING
                )
            )
            if item.review_requirement is ReviewRequirement.NEEDS_REVIEW
        )

    def list_completed(
        self, user_id: UserId, resolution: ReviewResolution | None = None
    ) -> tuple[ReviewRecord, ...]:
        return self._review_store.list_for_user(user_id, resolution)

    def get_transaction(
        self, user_id: UserId, transaction_id: UUID
    ) -> TransactionItem | ReviewRecord:
        item = self._review_session.get(transaction_id)
        if item is not None and item.user_id == user_id:
            return item
        record = self._review_store.get(transaction_id)
        if record is not None and record.user_id == user_id:
            return record
        raise ReviewNotFoundError

    def complete(
        self, user_id: UserId, submission: TransactionReviewSubmission
    ) -> ReviewRecord:
        existing = self._review_store.get(submission.transaction_id)
        if existing is not None:
            if existing.user_id != user_id:
                raise ReviewNotFoundError
            if existing.reviewed_category == submission.reviewed_category:
                return existing
            raise ReviewConflictError("transaction was already reviewed differently")

        item = self._review_session.get(submission.transaction_id)
        if item is None or item.user_id != user_id:
            raise ReviewNotFoundError

        resolution = self._derive_resolution(item, submission.reviewed_category)
        transaction = item.transaction
        if resolution is not ReviewResolution.KEPT_UNKNOWN:
            assert submission.reviewed_category is not None
            source = (
                TrustedCategorizationSource.CONFIRMED_AI_SUGGESTION
                if resolution is ReviewResolution.CONFIRMED
                else TrustedCategorizationSource.CORRECTED_AI_SUGGESTION
            )
            transaction = transaction.model_copy(
                update={
                    "trusted_categorization": TrustedCategorization(
                        category=submission.reviewed_category,
                        source=source,
                        note="Resolved through transaction review.",
                    )
                }
            )
            result = self._memory_store.record_trusted(
                [RecordTrustedCommand(transaction=transaction)]
            )
            status = result.items[0].status
            if status not in {MemoryWriteStatus.CREATED, MemoryWriteStatus.DUPLICATE}:
                raise MemoryPromotionError(
                    result.items[0].reason or f"categorization memory write {status}"
                )

        record = ReviewRecord(
            transaction=transaction,
            evidence_condition=item.evidence_condition,
            resolution=resolution,
            reviewed_category=submission.reviewed_category,
            completed_at=datetime.now(UTC),
        )
        stored = self._review_store.record(record)
        if stored.reviewed_category != record.reviewed_category:
            raise ReviewConflictError("transaction was already reviewed differently")

        self._review_session.replace(
            item.model_copy(
                update={
                    "transaction": transaction,
                    "resolution": resolution,
                    "resolved_category": submission.reviewed_category,
                }
            )
        )
        return stored

    @staticmethod
    def _derive_resolution(
        item: TransactionItem, reviewed_category: str | None
    ) -> ReviewResolution:
        if reviewed_category is None:
            return ReviewResolution.KEPT_UNKNOWN

        decision = item.transaction.ai_categorization
        ai_category = decision.category if decision is not None else None
        if reviewed_category == ai_category:
            if item.category_outcome not in {
                CategoryOutcome.SUGGESTED,
                CategoryOutcome.PROPOSED,
            }:
                raise InvalidReviewError("unknown categorization cannot be confirmed")
            if item.evidence_condition is EvidenceCondition.CONFLICTING:
                raise InvalidReviewError("conflicting evidence requires correction")
            return ReviewResolution.CONFIRMED
        return ReviewResolution.CORRECTED
