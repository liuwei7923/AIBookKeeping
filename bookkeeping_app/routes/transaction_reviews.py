"""HTTP adapter for completed human transaction reviews."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from bookkeeping_app.config import CATEGORIZATION_MEMORY_PATH, REVIEW_RECORD_PATH
from bookkeeping_app.domain_contracts import UserId
from bookkeeping_app.memory import FileMemoryStore, MemoryStore
from bookkeeping_app.request_identity import request_user_id
from bookkeeping_app.review import (
    EphemeralReviewSession,
    ReviewRecord,
    ReviewResolution,
    TransactionReviewBatchRequest,
)
from bookkeeping_app.review.record_store import (
    FileReviewRecordStore,
    ReviewRecordStore,
)
from bookkeeping_app.review.service import (
    InvalidReviewError,
    MemoryPromotionError,
    ReviewConflictError,
    ReviewNotFoundError,
    ReviewService,
)

router = APIRouter(prefix="/transaction-reviews", tags=["transaction-reviews"])
REVIEW_SESSION = EphemeralReviewSession()
REVIEW_STORE: ReviewRecordStore = FileReviewRecordStore(REVIEW_RECORD_PATH)
MEMORY_STORE: MemoryStore = FileMemoryStore(CATEGORIZATION_MEMORY_PATH)


def service() -> ReviewService:
    return ReviewService(REVIEW_SESSION, REVIEW_STORE, MEMORY_STORE)


@router.post("")
def create_transaction_reviews(
    request: TransactionReviewBatchRequest,
    response: Response,
    user_id: Annotated[UserId, Depends(request_user_id)],
) -> list[ReviewRecord]:
    response.headers["X-User-Id"] = str(user_id)
    try:
        return [service().complete(user_id, item) for item in request.items]
    except ReviewNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Transaction not found") from exc
    except InvalidReviewError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (ReviewConflictError, MemoryPromotionError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("")
def list_transaction_reviews(
    response: Response,
    user_id: Annotated[UserId, Depends(request_user_id)],
    resolution: Annotated[ReviewResolution | None, Query()] = None,
) -> list[ReviewRecord]:
    response.headers["X-User-Id"] = str(user_id)
    return list(service().list_completed(user_id, resolution))
