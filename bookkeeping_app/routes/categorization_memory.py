"""Categorization-memory collection routes."""

import logging
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from bookkeeping_app.config import CATEGORIZATION_MEMORY_PATH
from bookkeeping_app.memory import import_categorization_memory_csv, load_categorization_memory
from bookkeeping_app.memory_schema import CategorizationMemoryItem
from bookkeeping_app.uploads import read_csv_upload

logger = logging.getLogger("bookkeeping_app")
router = APIRouter(prefix="/categorization-memory", tags=["categorization-memory"])
MEMORY_PATH: Path = CATEGORIZATION_MEMORY_PATH


@router.get("")
def list_categorization_memory() -> list[dict[str, object]]:
    items = load_categorization_memory(MEMORY_PATH)
    return [serialize_memory_item(item) for item in items]


@router.post("")
async def create_categorization_memory(
    file: UploadFile = File(...),
) -> JSONResponse:
    csv_text = await read_csv_upload(file)

    try:
        result = import_categorization_memory_csv(csv_text, MEMORY_PATH)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    logger.info(
        "Imported categorization memory endpoint=categorization-memory "
        "filename=%s imported=%s skipped=%s",
        file.filename,
        result["imported"],
        result["skipped"],
    )
    return JSONResponse(content=result)


def serialize_memory_item(item: CategorizationMemoryItem) -> dict[str, object]:
    return {
        "date": item.date,
        "merchant": item.merchant,
        "statement": item.statement,
        "amount": item.amount,
        "direction": item.direction,
        "original_category": item.original_category,
        "category": item.corrected_category,
        "notes": item.notes,
    }
