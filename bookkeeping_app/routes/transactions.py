"""Transaction collection routes."""

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from fastapi.responses import JSONResponse

from bookkeeping_app.domain_contracts import UserId
from bookkeeping_app.openai_service import review_transaction_categories
from bookkeeping_app.parsers import parse_csv_transactions
from bookkeeping_app.request_identity import request_user_id
from bookkeeping_app.review import (
    ReviewRecord,
    ReviewResolution,
    ReviewStatus,
    TransactionItem,
)
from bookkeeping_app.review.processing import enqueue_review_results
from bookkeeping_app.review.service import ReviewNotFoundError, ReviewService
from bookkeeping_app.routes.transaction_reviews import (
    MEMORY_STORE,
    REVIEW_SESSION,
    REVIEW_STORE,
)
from bookkeeping_app.uploads import read_csv_upload

logger = logging.getLogger("bookkeeping_app")
router = APIRouter(prefix="/transactions", tags=["transactions"])


def review_service() -> ReviewService:
    return ReviewService(REVIEW_SESSION, REVIEW_STORE, MEMORY_STORE)


@router.get("")
def list_transactions(
    response: Response,
    user_id: Annotated[UserId, Depends(request_user_id)],
    review_status: Annotated[ReviewStatus, Query()] = ReviewStatus.TODO,
    review_resolution: Annotated[ReviewResolution | None, Query()] = None,
) -> list[TransactionItem | ReviewRecord]:
    response.headers["X-User-Id"] = str(user_id)
    if review_status is ReviewStatus.TODO:
        return list(review_service().list_todo(user_id))
    return list(review_service().list_completed(user_id, review_resolution))


@router.get("/{transaction_id}")
def get_transaction(
    transaction_id: UUID,
    response: Response,
    user_id: Annotated[UserId, Depends(request_user_id)],
) -> TransactionItem | ReviewRecord:
    response.headers["X-User-Id"] = str(user_id)
    try:
        return review_service().get_transaction(user_id, transaction_id)
    except ReviewNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Transaction not found") from exc


@router.post("")
async def create_transactions(
    user_id: Annotated[UserId, Depends(request_user_id)],
    file: UploadFile = File(...),
) -> JSONResponse:
    csv_text = await read_csv_upload(file)
    transactions = parse_csv_transactions(csv_text)
    logger.info(
        "Parsed transaction CSV endpoint=transactions user_id=%s filename=%s "
        "transactions=%s",
        user_id,
        file.filename,
        len(transactions),
    )

    reviewed_transactions = review_transaction_categories(transactions)
    logger.info(
        "Completed category review endpoint=transactions reviewed_transactions=%s",
        len(reviewed_transactions),
    )
    queued_transactions = enqueue_review_results(
        user_id=user_id,
        source_rows=transactions,
        reviewed_rows=reviewed_transactions,
        review_session=REVIEW_SESSION,
    )
    return JSONResponse(
        content=queued_transactions,
        headers={"X-User-Id": str(user_id)},
    )
