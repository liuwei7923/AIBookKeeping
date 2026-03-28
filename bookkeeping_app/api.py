import logging

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from bookkeeping_app.config import ALLOWED_IMAGE_CONTENT_TYPES
from bookkeeping_app.metrics import metrics
from bookkeeping_app.openai_service import (
    extract_transactions_from_image,
    review_transaction_categories,
)
from bookkeeping_app.parsers import is_valid_csv_upload, parse_csv_transactions

logger = logging.getLogger("bookkeeping_app")

app = FastAPI(title="AI Bookkeeping App MVP")


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/openai-usage")
def openai_usage() -> dict[str, int | str]:
    return metrics.snapshot()


@app.post("/extract-transactions")
async def extract_transactions(file: UploadFile = File(...)) -> JSONResponse:
    if file.content_type not in ALLOWED_IMAGE_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Invalid file type. Use JPEG, PNG, or WEBP image files.",
        )

    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    logger.info(
        "Received image upload endpoint=extract-transactions filename=%s content_type=%s size_bytes=%s",
        file.filename,
        file.content_type,
        len(image_bytes),
    )

    transactions = extract_transactions_from_image(image_bytes, file.content_type)
    logger.info(
        "Completed image extraction endpoint=extract-transactions transactions=%s",
        len(transactions),
    )
    return JSONResponse(content=transactions)


@app.post("/extract-transactions-csv")
async def extract_transactions_csv(file: UploadFile = File(...)) -> JSONResponse:
    if not is_valid_csv_upload(file):
        raise HTTPException(status_code=400, detail="Invalid file type. Use a CSV file.")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    try:
        csv_text = file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="CSV file must be UTF-8 encoded") from exc

    transactions = parse_csv_transactions(csv_text)
    logger.info(
        "Parsed CSV endpoint=extract-transactions-csv filename=%s transactions=%s",
        file.filename,
        len(transactions),
    )
    return JSONResponse(content=transactions)


@app.post("/recategorize-transactions-csv")
async def recategorize_transactions_csv(file: UploadFile = File(...)) -> JSONResponse:
    if not is_valid_csv_upload(file):
        raise HTTPException(status_code=400, detail="Invalid file type. Use a CSV file.")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    try:
        csv_text = file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="CSV file must be UTF-8 encoded") from exc

    transactions = parse_csv_transactions(csv_text)
    logger.info(
        "Parsed CSV endpoint=recategorize-transactions-csv filename=%s transactions=%s",
        file.filename,
        len(transactions),
    )
    reviewed_transactions = review_transaction_categories(transactions)
    logger.info(
        "Completed AI category review endpoint=recategorize-transactions-csv reviewed_transactions=%s",
        len(reviewed_transactions),
    )
    return JSONResponse(content=reviewed_transactions)
