"""Transaction collection routes."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import JSONResponse

from bookkeeping_app.domain_contracts import UserId
from bookkeeping_app.openai_service import review_transaction_categories
from bookkeeping_app.parsers import parse_csv_transactions
from bookkeeping_app.request_identity import request_user_id
from bookkeeping_app.review.processing import enqueue_review_results
from bookkeeping_app.routes.review_items import REVIEW_SESSION
from bookkeeping_app.uploads import read_csv_upload

logger = logging.getLogger("bookkeeping_app")
router = APIRouter(prefix="/transactions", tags=["transactions"])


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
