import base64
import csv
import json
import logging
import os
from io import StringIO
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from openai import APIError, APIStatusError, OpenAI

load_dotenv()

app = FastAPI(title="AI Bookkeeping App MVP")
logger = logging.getLogger("bookkeeping_app")

if not logger.handlers:
    logging.basicConfig(level=logging.INFO)

openai_request_count = 0

SYSTEM_PROMPT = """You are a financial assistant.
Extract transactions from images into structured JSON.
Return ONLY valid JSON. No explanation.
Ensure amount is a number, not string.
If any field is unknown, use null.

Return a JSON array. Each item must have this schema:
{
  "date": string | null,
  "amount": number | null,
  "merchant": string | null,
  "category": string | null
}
"""

CATEGORY_REVIEW_PROMPT = """You are a financial assistant.
Review transaction categories and correct them when they are inaccurate.
Return ONLY valid JSON. No explanation.
Preserve the original transaction fields.
If the existing category is reasonable, keep it as the suggested category.
If a better category is obvious from merchant, amount, and context, change it.
Keep the reason short and practical.

Return a JSON array. Each item must have this schema:
{
  "date": string | null,
  "amount": number | null,
  "merchant": string | null,
  "original_category": string | null,
  "suggested_category": string | null,
  "reason": string | null
}
"""

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
ALLOWED_CSV_CONTENT_TYPES = {
    "text/csv",
    "application/csv",
    "application/vnd.ms-excel",
    "application/octet-stream",
}
MODEL_NAME = "gpt-4.1-mini"


def get_openai_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY is not set")
    return OpenAI(api_key=api_key)


def record_openai_request(endpoint_name: str) -> None:
    global openai_request_count
    openai_request_count += 1
    logger.info(
        "OpenAI request count=%s endpoint=%s model=%s",
        openai_request_count,
        endpoint_name,
        MODEL_NAME,
    )


def raise_openai_http_error(exc: Exception) -> None:
    if isinstance(exc, APIStatusError):
        logger.error(
            "OpenAI API status error status=%s message=%s",
            exc.status_code,
            str(exc),
        )

        if exc.status_code == 429:
            raise HTTPException(
                status_code=429,
                detail="OpenAI quota or rate limit exceeded. Check API billing, project limits, or try again later.",
            ) from exc

        raise HTTPException(
            status_code=502,
            detail=f"OpenAI API request failed with status {exc.status_code}",
        ) from exc

    if isinstance(exc, APIError):
        logger.error("OpenAI API error message=%s", str(exc))
        raise HTTPException(status_code=502, detail="OpenAI API request failed") from exc

    logger.exception("Unexpected error while calling OpenAI")
    raise HTTPException(status_code=502, detail="Unexpected error while calling OpenAI") from exc


def parse_transactions(raw_text: str) -> list[dict[str, Any]]:
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=502,
            detail="OpenAI response was not valid JSON",
        ) from exc

    if not isinstance(data, list):
        raise HTTPException(
            status_code=502,
            detail="OpenAI response was not a JSON array",
        )

    cleaned_transactions = []

    for item in data:
        if not isinstance(item, dict):
            continue

        amount = item.get("amount")
        if isinstance(amount, str):
            try:
                amount = float(amount)
            except ValueError:
                amount = None

        cleaned_transactions.append(
            {
                "date": item.get("date"),
                "amount": amount,
                "merchant": item.get("merchant"),
                "category": item.get("category"),
            }
        )

    return cleaned_transactions


def parse_category_review(raw_text: str) -> list[dict[str, Any]]:
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=502,
            detail="OpenAI response was not valid JSON",
        ) from exc

    if not isinstance(data, list):
        raise HTTPException(
            status_code=502,
            detail="OpenAI response was not a JSON array",
        )

    cleaned_reviews = []

    for item in data:
        if not isinstance(item, dict):
            continue

        amount = item.get("amount")
        if isinstance(amount, str):
            try:
                amount = float(amount)
            except ValueError:
                amount = None

        cleaned_reviews.append(
            {
                "date": item.get("date"),
                "amount": amount,
                "merchant": item.get("merchant"),
                "original_category": item.get("original_category"),
                "suggested_category": item.get("suggested_category"),
                "reason": item.get("reason"),
            }
        )

    return cleaned_reviews


def normalize_amount(value: Any) -> float | None:
    if value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    if not isinstance(value, str):
        return None

    cleaned = value.strip().replace("$", "").replace(",", "")
    if not cleaned:
        return None

    try:
        return float(cleaned)
    except ValueError:
        return None


def find_csv_value(row: dict[str, str], candidates: list[str]) -> str | None:
    normalized_row = {key.strip().lower(): value for key, value in row.items() if key}
    for candidate in candidates:
        value = normalized_row.get(candidate)
        if value is not None:
            stripped = value.strip()
            return stripped or None
    return None


def parse_csv_transactions(csv_text: str) -> list[dict[str, Any]]:
    try:
        reader = csv.DictReader(StringIO(csv_text))
    except csv.Error as exc:
        raise HTTPException(status_code=400, detail="Could not read CSV file") from exc

    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV file must include a header row")

    transactions = []

    for row in reader:
        if not row:
            continue

        transaction = {
            "date": find_csv_value(row, ["date", "transaction date", "posted date"]),
            "amount": normalize_amount(
                find_csv_value(row, ["amount", "transaction amount", "value"])
            ),
            "merchant": find_csv_value(row, ["merchant", "description", "payee", "name"]),
            "category": find_csv_value(row, ["category"]),
        }
        transactions.append(transaction)

    return transactions


def is_valid_csv_upload(file: UploadFile) -> bool:
    if file.content_type in ALLOWED_CSV_CONTENT_TYPES:
        return True

    filename = file.filename or ""
    return filename.lower().endswith(".csv")


def review_transaction_categories(transactions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not transactions:
        return []

    review_input = [
        {
            "date": transaction.get("date"),
            "amount": transaction.get("amount"),
            "merchant": transaction.get("merchant"),
            "original_category": transaction.get("category"),
        }
        for transaction in transactions
    ]

    try:
        client = get_openai_client()
        record_openai_request("recategorize-transactions-csv")
        response = client.responses.create(
            model=MODEL_NAME,
            input=[
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": CATEGORY_REVIEW_PROMPT}],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "Review these transactions and suggest corrected categories "
                                "when needed.\n\n"
                                f"{json.dumps(review_input)}"
                            ),
                        }
                    ],
                },
            ],
        )
    except Exception as exc:
        raise_openai_http_error(exc)

    output_text = getattr(response, "output_text", "").strip()
    if not output_text:
        raise HTTPException(status_code=502, detail="OpenAI returned an empty response")

    return parse_category_review(output_text)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/extract-transactions")
async def extract_transactions(file: UploadFile = File(...)) -> JSONResponse:
    if file.content_type not in ALLOWED_CONTENT_TYPES:
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

    base64_image = base64.b64encode(image_bytes).decode("utf-8")
    image_url = f"data:{file.content_type};base64,{base64_image}"

    try:
        client = get_openai_client()
        record_openai_request("extract-transactions")
        response = client.responses.create(
            model=MODEL_NAME,
            input=[
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": SYSTEM_PROMPT}],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "Extract all visible transactions from this image.",
                        },
                        {
                            "type": "input_image",
                            "image_url": image_url,
                        },
                    ],
                },
            ],
        )
    except Exception as exc:
        raise_openai_http_error(exc)

    output_text = getattr(response, "output_text", "").strip()
    if not output_text:
        raise HTTPException(status_code=502, detail="OpenAI returned an empty response")

    transactions = parse_transactions(output_text)
    logger.info(
        "Completed image extraction endpoint=extract-transactions transactions=%s",
        len(transactions),
    )
    return JSONResponse(content=transactions)


@app.post("/extract-transactions-csv")
async def extract_transactions_csv(file: UploadFile = File(...)) -> JSONResponse:
    if not is_valid_csv_upload(file):
        raise HTTPException(
            status_code=400,
            detail="Invalid file type. Use a CSV file.",
        )

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    try:
        csv_text = file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=400,
            detail="CSV file must be UTF-8 encoded",
        ) from exc

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
        raise HTTPException(
            status_code=400,
            detail="Invalid file type. Use a CSV file.",
        )

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    try:
        csv_text = file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=400,
            detail="CSV file must be UTF-8 encoded",
        ) from exc

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


@app.get("/openai-usage")
def openai_usage() -> dict[str, int | str]:
    return {
        "model": MODEL_NAME,
        "openai_request_count": openai_request_count,
    }
