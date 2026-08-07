from decimal import Decimal
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from bookkeeping_app.api import app
from bookkeeping_app.domain_contracts import (
    CanonicalTransaction,
    CategorizationDecision,
    DecisionType,
    SourceTransaction,
    TransactionDirection,
    TransactionIdentityQuality,
    TrustedCategorization,
    TrustedCategorizationSource,
)
from bookkeeping_app.memory import InMemoryMemoryStore, MemoryListQuery
from bookkeeping_app.review import (
    AcceptAiRequest,
    CategoryOutcome,
    CorrectRequest,
    EphemeralReviewSession,
    EvidenceCondition,
    KeepUnknownRequest,
    ReviewRequirement,
    ReviewResolution,
    TransactionItem,
)
from bookkeeping_app.review.processing import enqueue_canonical_review_items
from bookkeeping_app.review.service import (
    InvalidReviewActionError,
    MemoryPromotionError,
    ReviewConflictError,
    ReviewNotFoundError,
    ReviewService,
)

USER_ID = UUID("8a802680-06be-4815-986b-58b88392acfc")
OTHER_USER_ID = UUID("0c050ed3-d41b-468c-9c29-e9e6da905c04")


def review_item(
    *,
    outcome: CategoryOutcome = CategoryOutcome.SUGGESTED,
    evidence: EvidenceCondition = EvidenceCondition.SUPPORTING,
    user_id: UUID = USER_ID,
    transaction_number: int = 1,
    fingerprint: str | None = None,
) -> TransactionItem:
    category_fields: dict[str, str] = {}
    decision_type = DecisionType.UNRESOLVED
    if outcome is CategoryOutcome.SUGGESTED:
        decision_type = DecisionType.AI_SUGGESTION
        category_fields["suggested_category"] = "Groceries"
    elif outcome is CategoryOutcome.PROPOSED:
        decision_type = DecisionType.AI_PROPOSED_NEW_CATEGORY
        category_fields["proposed_category"] = "EV Charging"
    decision = CategorizationDecision(
        decision_id=f"decision-{transaction_number}",
        decision_type=decision_type,
        reason="Review this result.",
        **category_fields,
    )
    transaction = CanonicalTransaction(
        source=SourceTransaction(
            user_id=user_id,
            transaction_id=UUID(int=transaction_number),
            date="2026-08-01",
            merchant="Whole Foods",
            statement="WHOLE FOODS 123",
            amount=Decimal("-42.19"),
        ),
        normalized_merchant="whole foods",
        normalized_statement="whole foods 123",
        direction=TransactionDirection.DEBIT,
        identity_quality=TransactionIdentityQuality.COMPLETE,
        fingerprint=fingerprint or f"sha256:{transaction_number:064x}",
        ai_categorization=decision,
    )
    return TransactionItem(
        transaction=transaction,
        review_requirement=ReviewRequirement.NEEDS_REVIEW,
        evidence_condition=evidence,
    )


def service_for(item: TransactionItem) -> tuple[ReviewService, InMemoryMemoryStore]:
    memory = InMemoryMemoryStore()
    return ReviewService(EphemeralReviewSession((item,)), memory), memory


def memory_items(memory: InMemoryMemoryStore, user_id: UUID = USER_ID):
    return memory.list_for_user(MemoryListQuery(user_id=user_id)).transactions


def test_suggested_accept_ai_writes_trusted_memory() -> None:
    item = review_item()
    service, memory = service_for(item)

    resolved = service.resolve(
        USER_ID, item.transaction_id, AcceptAiRequest(action="accept_ai")
    )

    assert resolved.resolution is ReviewResolution.CONFIRMED
    assert resolved.category_outcome is CategoryOutcome.SUGGESTED
    assert resolved.transaction.ai_categorization == item.transaction.ai_categorization
    trusted = memory_items(memory)[0].trusted_categorization
    assert trusted is not None
    assert trusted.category == "Groceries"
    assert trusted.source == "confirmed_ai_suggestion"


def test_proposed_accept_ai_preserves_provenance() -> None:
    item = review_item(outcome=CategoryOutcome.PROPOSED)
    service, memory = service_for(item)

    resolved = service.resolve(
        USER_ID, item.transaction_id, AcceptAiRequest(action="accept_ai")
    )

    assert resolved.category_outcome is CategoryOutcome.PROPOSED
    assert resolved.transaction.ai_categorization is not None
    assert resolved.transaction.ai_categorization.proposed_category == "EV Charging"
    assert (
        memory_items(memory)[0].ai_categorization == item.transaction.ai_categorization
    )


@pytest.mark.parametrize(
    ("outcome", "evidence"),
    [
        (CategoryOutcome.UNKNOWN, EvidenceCondition.INSUFFICIENT),
        (CategoryOutcome.SUGGESTED, EvidenceCondition.CONFLICTING),
    ],
)
def test_accept_ai_rejects_unknown_and_conflicting_evidence(
    outcome: CategoryOutcome, evidence: EvidenceCondition
) -> None:
    item = review_item(outcome=outcome, evidence=evidence)
    service, memory = service_for(item)

    with pytest.raises(InvalidReviewActionError):
        service.resolve(
            USER_ID, item.transaction_id, AcceptAiRequest(action="accept_ai")
        )

    assert not memory_items(memory)


def test_correction_writes_corrected_memory() -> None:
    item = review_item()
    service, memory = service_for(item)

    resolved = service.resolve(
        USER_ID,
        item.transaction_id,
        CorrectRequest(action="correct", category="Dining"),
    )

    assert resolved.resolution is ReviewResolution.CORRECTED
    trusted = memory_items(memory)[0].trusted_categorization
    assert trusted is not None
    assert trusted.category == "Dining"
    assert trusted.source == "corrected_ai_suggestion"


def test_keep_unknown_does_not_write_memory() -> None:
    item = review_item(outcome=CategoryOutcome.UNKNOWN)
    service, memory = service_for(item)

    resolved = service.resolve(
        USER_ID, item.transaction_id, KeepUnknownRequest(action="keep_unknown")
    )

    assert resolved.resolution is ReviewResolution.KEPT_UNKNOWN
    assert not memory_items(memory)


def test_identical_resolution_is_idempotent_and_different_one_conflicts() -> None:
    item = review_item()
    service, memory = service_for(item)
    request = AcceptAiRequest(action="accept_ai")

    first = service.resolve(USER_ID, item.transaction_id, request)
    second = service.resolve(USER_ID, item.transaction_id, request)

    assert second == first
    assert len(memory_items(memory)) == 1
    with pytest.raises(ReviewConflictError):
        service.resolve(
            USER_ID,
            item.transaction_id,
            CorrectRequest(action="correct", category="Dining"),
        )


def test_cross_user_access_is_rejected() -> None:
    item = review_item()
    service, _ = service_for(item)

    with pytest.raises(ReviewNotFoundError):
        service.get_item(OTHER_USER_ID, item.transaction_id)


def test_memory_duplicate_succeeds_and_conflict_leaves_item_pending() -> None:
    first = review_item(transaction_number=1, fingerprint="sha256:same")
    first_service, memory = service_for(first)
    first_service.resolve(
        USER_ID, first.transaction_id, AcceptAiRequest(action="accept_ai")
    )

    duplicate = review_item(transaction_number=2, fingerprint="sha256:same")
    duplicate_service = ReviewService(EphemeralReviewSession((duplicate,)), memory)
    assert (
        duplicate_service.resolve(
            USER_ID, duplicate.transaction_id, AcceptAiRequest(action="accept_ai")
        ).resolution
        is ReviewResolution.CONFIRMED
    )

    conflict = review_item(transaction_number=3, fingerprint="sha256:same")
    conflict_service = ReviewService(EphemeralReviewSession((conflict,)), memory)
    with pytest.raises(MemoryPromotionError):
        conflict_service.resolve(
            USER_ID,
            conflict.transaction_id,
            CorrectRequest(action="correct", category="Dining"),
        )
    assert (
        conflict_service.get_item(USER_ID, conflict.transaction_id).resolution
        is ReviewResolution.PENDING
    )


def test_review_item_api_list_detail_filter_and_resolution(monkeypatch) -> None:
    pending = review_item(transaction_number=10)
    review_session = EphemeralReviewSession((pending,))
    memory_store = InMemoryMemoryStore()
    monkeypatch.setattr(
        "bookkeeping_app.routes.review_items.REVIEW_SESSION", review_session
    )
    monkeypatch.setattr(
        "bookkeeping_app.routes.review_items.MEMORY_STORE", memory_store
    )
    client = TestClient(app, headers={"X-User-Id": str(USER_ID)})

    listed = client.get("/review-items", params={"resolution": "pending"})
    detailed = client.get(f"/review-items/{pending.transaction_id}")
    resolved = client.post(
        f"/review-items/{pending.transaction_id}", json={"action": "accept_ai"}
    )

    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert detailed.status_code == 200
    assert resolved.status_code == 200
    assert resolved.json()["resolution"] == "confirmed"
    assert client.get("/review-items", params={"resolution": "pending"}).json() == []
    assert (
        len(client.get("/review-items", params={"resolution": "confirmed"}).json()) == 1
    )


def test_review_api_enforces_user_isolation_and_conflict(monkeypatch) -> None:
    pending = review_item(transaction_number=11)
    monkeypatch.setattr(
        "bookkeeping_app.routes.review_items.REVIEW_SESSION",
        EphemeralReviewSession((pending,)),
    )
    monkeypatch.setattr(
        "bookkeeping_app.routes.review_items.MEMORY_STORE", InMemoryMemoryStore()
    )
    owner = TestClient(app, headers={"X-User-Id": str(USER_ID)})
    other = TestClient(app, headers={"X-User-Id": str(OTHER_USER_ID)})

    assert other.get(f"/review-items/{pending.transaction_id}").status_code == 404
    assert (
        owner.post(
            f"/review-items/{pending.transaction_id}", json={"action": "keep_unknown"}
        ).status_code
        == 200
    )
    assert (
        owner.post(
            f"/review-items/{pending.transaction_id}",
            json={"action": "correct", "category": "Dining"},
        ).status_code
        == 409
    )


def test_deterministic_accepted_transaction_does_not_enter_review_view() -> None:
    accepted = review_item().transaction.model_copy(update={"ai_categorization": None})
    review_session = EphemeralReviewSession()

    queued = enqueue_canonical_review_items([accepted], review_session)

    assert queued == ()
    assert review_session.list_all() == ()


def test_review_session_state_is_process_local_and_not_recovered() -> None:
    first_process = EphemeralReviewSession((review_item(transaction_number=22),))
    restarted_process = EphemeralReviewSession()

    assert len(first_process.list_all()) == 1
    assert restarted_process.list_all() == ()


def test_category_outcome_is_derived_from_canonical_provenance() -> None:
    suggested = review_item(outcome=CategoryOutcome.SUGGESTED)
    confirmed = suggested.model_copy(
        update={
            "transaction": suggested.transaction.model_copy(
                update={"trusted_categorization": memory_categorization()}
            )
        }
    )
    deterministic = suggested.model_copy(
        update={
            "transaction": suggested.transaction.model_copy(
                update={
                    "ai_categorization": None,
                    "trusted_categorization": memory_categorization(),
                }
            ),
            "review_requirement": ReviewRequirement.NO_REVIEW_REQUIRED,
        }
    )

    assert confirmed.category_outcome is CategoryOutcome.SUGGESTED
    assert deterministic.category_outcome is CategoryOutcome.ACCEPTED


def memory_categorization() -> TrustedCategorization:
    return TrustedCategorization(
        category="Groceries",
        source=TrustedCategorizationSource.MANUAL_CLASSIFICATION,
    )
