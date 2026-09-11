from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from bookkeeping_app.api import app
from bookkeeping_app.domain_contracts import (
    AICategorization,
    CanonicalTransaction,
    CategorizationType,
    SourceTransaction,
    TransactionDirection,
    TransactionIdentityQuality,
)
from bookkeeping_app.memory import InMemoryMemoryStore, MemoryListQuery
from bookkeeping_app.review import (
    CategoryOutcome,
    EphemeralReviewSession,
    EvidenceCondition,
    ReviewRequirement,
    ReviewResolution,
    TransactionItem,
    TransactionReviewSubmission,
)
from bookkeeping_app.review.record_store import (
    FileReviewRecordStore,
    InMemoryReviewRecordStore,
)
from bookkeeping_app.review.service import (
    InvalidReviewError,
    MemoryPromotionError,
    ReviewConflictError,
    ReviewNotFoundError,
    ReviewService,
)

USER_ID = UUID("8a802680-06be-4815-986b-58b88392acfc")
OTHER_USER_ID = UUID("0c050ed3-d41b-468c-9c29-e9e6da905c04")


def transaction_item(
    *,
    outcome: CategoryOutcome = CategoryOutcome.SUGGESTED,
    evidence: EvidenceCondition = EvidenceCondition.SUPPORTING,
    user_id: UUID = USER_ID,
    number: int = 1,
    fingerprint: str | None = None,
) -> TransactionItem:
    categorization_type = CategorizationType.NOT_AVAILABLE
    category = None
    if outcome is CategoryOutcome.SUGGESTED:
        categorization_type = CategorizationType.SUGGESTED
        category = "Groceries"
    elif outcome is CategoryOutcome.PROPOSED:
        categorization_type = CategorizationType.PROPOSED
        category = "EV Charging"
    transaction = CanonicalTransaction(
        source=SourceTransaction(
            user_id=user_id,
            transaction_id=UUID(int=number),
            date="2026-08-01",
            merchant="Whole Foods",
            statement="WHOLE FOODS 123",
            amount=Decimal("-42.19"),
        ),
        normalized_merchant="whole foods",
        normalized_statement="whole foods 123",
        direction=TransactionDirection.DEBIT,
        identity_quality=TransactionIdentityQuality.COMPLETE,
        fingerprint=fingerprint or f"sha256:{number:064x}",
        ai_categorization=AICategorization(
            decision_id=f"decision-{number}",
            categorization_type=categorization_type,
            category=category,
            reason="Review this result.",
        ),
    )
    return TransactionItem(
        transaction=transaction,
        review_requirement=ReviewRequirement.NEEDS_REVIEW,
        evidence_condition=evidence,
    )


def service_for(item: TransactionItem):
    memory = InMemoryMemoryStore()
    records = InMemoryReviewRecordStore()
    service = ReviewService(EphemeralReviewSession((item,)), records, memory)
    return service, records, memory


def submit(item: TransactionItem, category: str | None):
    return TransactionReviewSubmission(
        transaction_id=item.transaction_id, reviewed_category=category
    )


def memory_items(memory: InMemoryMemoryStore):
    return memory.list_for_user(MemoryListQuery(user_id=USER_ID)).transactions


def test_matching_suggested_category_confirms_and_writes_memory() -> None:
    item = transaction_item()
    service, records, memory = service_for(item)

    record = service.complete(USER_ID, submit(item, "Groceries"))

    assert record.resolution is ReviewResolution.CONFIRMED
    assert record.category_outcome is CategoryOutcome.SUGGESTED
    assert records.get(item.transaction_id) == record
    trusted = memory_items(memory)[0].trusted_categorization
    assert trusted is not None
    assert trusted.source == "confirmed_ai_suggestion"
    assert record.transaction.ai_categorization == item.transaction.ai_categorization


def test_matching_proposed_category_confirms_and_preserves_provenance() -> None:
    item = transaction_item(outcome=CategoryOutcome.PROPOSED)
    service, _, memory = service_for(item)

    record = service.complete(USER_ID, submit(item, "EV Charging"))

    assert record.resolution is ReviewResolution.CONFIRMED
    assert record.category_outcome is CategoryOutcome.PROPOSED
    assert (
        memory_items(memory)[0].ai_categorization == item.transaction.ai_categorization
    )


def test_different_category_corrects_and_writes_memory() -> None:
    item = transaction_item()
    service, _, memory = service_for(item)

    record = service.complete(USER_ID, submit(item, "Business Meals"))

    assert record.resolution is ReviewResolution.CORRECTED
    trusted = memory_items(memory)[0].trusted_categorization
    assert trusted is not None
    assert trusted.source == "corrected_ai_suggestion"


def test_null_category_keeps_unknown_without_memory_write() -> None:
    item = transaction_item(outcome=CategoryOutcome.UNKNOWN)
    service, records, memory = service_for(item)

    record = service.complete(USER_ID, submit(item, None))

    assert record.resolution is ReviewResolution.KEPT_UNKNOWN
    assert records.get(item.transaction_id) == record
    assert memory_items(memory) == ()


def test_conflicting_evidence_rejects_confirming_ai_category() -> None:
    item = transaction_item(evidence=EvidenceCondition.CONFLICTING)
    service, _, _ = service_for(item)

    with pytest.raises(InvalidReviewError):
        service.complete(USER_ID, submit(item, "Groceries"))


def test_identical_retry_is_idempotent_and_different_retry_conflicts() -> None:
    item = transaction_item()
    service, _, memory = service_for(item)
    submission = submit(item, "Groceries")

    first = service.complete(USER_ID, submission)
    second = service.complete(USER_ID, submission)

    assert second == first
    assert len(memory_items(memory)) == 1
    with pytest.raises(ReviewConflictError):
        service.complete(USER_ID, submit(item, "Dining"))


def test_cross_user_access_is_rejected() -> None:
    item = transaction_item()
    service, _, _ = service_for(item)

    with pytest.raises(ReviewNotFoundError):
        service.complete(OTHER_USER_ID, submit(item, "Groceries"))


def test_memory_conflict_leaves_review_unrecorded() -> None:
    first = transaction_item(number=1, fingerprint="sha256:same")
    service, _, memory = service_for(first)
    service.complete(USER_ID, submit(first, "Groceries"))
    conflict = transaction_item(number=2, fingerprint="sha256:same")
    records = InMemoryReviewRecordStore()
    conflict_service = ReviewService(
        EphemeralReviewSession((conflict,)), records, memory
    )

    with pytest.raises(MemoryPromotionError):
        conflict_service.complete(USER_ID, submit(conflict, "Dining"))

    assert records.get(conflict.transaction_id) is None


def test_file_review_store_persists_completed_records(tmp_path: Path) -> None:
    item = transaction_item()
    path = tmp_path / "review_records.json"
    store = FileReviewRecordStore(path)
    service = ReviewService(
        EphemeralReviewSession((item,)), store, InMemoryMemoryStore()
    )
    record = service.complete(USER_ID, submit(item, "Groceries"))

    assert FileReviewRecordStore(path).get(item.transaction_id) == record


def test_transaction_and_review_routes_support_todo_completed_and_batch(
    monkeypatch,
) -> None:
    item = transaction_item(number=10)
    unknown = transaction_item(outcome=CategoryOutcome.UNKNOWN, number=11)
    session = EphemeralReviewSession((item, unknown))
    records = InMemoryReviewRecordStore()
    memory = InMemoryMemoryStore()
    for module in (
        "bookkeeping_app.routes.transactions",
        "bookkeeping_app.routes.transaction_reviews",
    ):
        monkeypatch.setattr(f"{module}.REVIEW_SESSION", session)
        monkeypatch.setattr(f"{module}.REVIEW_STORE", records)
        monkeypatch.setattr(f"{module}.MEMORY_STORE", memory)
    client = TestClient(app, headers={"X-User-Id": str(USER_ID)})

    todo = client.get("/transactions", params={"review_status": "todo"})
    completed = client.post(
        "/transaction-reviews",
        json={
            "items": [
                {
                    "transaction_id": str(item.transaction_id),
                    "reviewed_category": "Groceries",
                },
                {
                    "transaction_id": str(unknown.transaction_id),
                    "reviewed_category": None,
                },
            ]
        },
    )
    history = client.get("/transactions", params={"review_status": "completed"})
    audit = client.get("/transaction-reviews")

    assert todo.status_code == 200 and len(todo.json()) == 2
    assert completed.status_code == 200
    assert completed.json()[0]["resolution"] == "confirmed"
    assert completed.json()[1]["resolution"] == "kept_unknown"
    assert len(history.json()) == 2
    assert len(audit.json()) == 2
    assert client.get("/transactions", params={"review_status": "todo"}).json() == []
