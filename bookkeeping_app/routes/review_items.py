"""HTTP adapter for transaction review operations."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from bookkeeping_app.config import CATEGORIZATION_MEMORY_PATH
from bookkeeping_app.domain_contracts import UserId
from bookkeeping_app.memory import FileMemoryStore, MemoryStore
from bookkeeping_app.request_identity import request_user_id
from bookkeeping_app.review import (
    EphemeralReviewSession,
    ReviewResolution,
    ReviewResolutionRequest,
    TransactionItem,
)
from bookkeeping_app.review.service import (
    InvalidReviewActionError,
    MemoryPromotionError,
    ReviewConflictError,
    ReviewNotFoundError,
    ReviewService,
)

router = APIRouter(prefix="/review-items", tags=["review-items"])
REVIEW_SESSION = EphemeralReviewSession()
MEMORY_STORE: MemoryStore = FileMemoryStore(CATEGORIZATION_MEMORY_PATH)


def service() -> ReviewService:
    return ReviewService(REVIEW_SESSION, MEMORY_STORE)


@router.get("")
def list_review_items(
    response: Response,
    user_id: Annotated[UserId, Depends(request_user_id)],
    resolution: Annotated[ReviewResolution | None, Query()] = None,
) -> list[TransactionItem]:
    response.headers["X-User-Id"] = str(user_id)
    return list(service().list_items(user_id, resolution))


@router.get("/{transaction_id}")
def get_review_item(
    transaction_id: UUID,
    response: Response,
    user_id: Annotated[UserId, Depends(request_user_id)],
) -> TransactionItem:
    response.headers["X-User-Id"] = str(user_id)
    try:
        return service().get_item(user_id, transaction_id)
    except ReviewNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Review item not found") from exc


@router.post("/{transaction_id}")
def resolve_review_item(
    transaction_id: UUID,
    request: ReviewResolutionRequest,
    response: Response,
    user_id: Annotated[UserId, Depends(request_user_id)],
) -> TransactionItem:
    response.headers["X-User-Id"] = str(user_id)
    try:
        return service().resolve(user_id, transaction_id, request)
    except ReviewNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Review item not found") from exc
    except InvalidReviewActionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (ReviewConflictError, MemoryPromotionError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
