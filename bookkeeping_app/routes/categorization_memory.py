"""Read-only inspection of user-confirmed categorization memory."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from bookkeeping_app.config import CATEGORIZATION_MEMORY_PATH
from bookkeeping_app.domain_contracts import CanonicalTransaction, UserId
from bookkeeping_app.memory import (
    FileMemoryStore,
    MemoryListQuery,
    MemoryStore,
)
from bookkeeping_app.request_identity import request_user_id

router = APIRouter(prefix="/categorization-memory", tags=["categorization-memory"])
MEMORY_STORE: MemoryStore = FileMemoryStore(CATEGORIZATION_MEMORY_PATH)


@router.get("")
def list_categorization_memory(
    response: Response,
    user_id: Annotated[UserId, Depends(request_user_id)],
) -> list[dict[str, object]]:
    response.headers["X-User-Id"] = str(user_id)
    transactions: list[CanonicalTransaction] = []
    cursor: str | None = None
    while True:
        page = MEMORY_STORE.list_for_user(
            MemoryListQuery(user_id=user_id, limit=500, cursor=cursor)
        )
        transactions.extend(page.transactions)
        if page.next_cursor is None:
            break
        cursor = page.next_cursor
    return [serialize_memory_transaction(item) for item in transactions]


def serialize_memory_transaction(
    transaction: CanonicalTransaction,
) -> dict[str, object]:
    trusted = transaction.trusted_categorization
    assert trusted is not None
    return {
        "date": transaction.source.date,
        "merchant": transaction.source.merchant,
        "statement": transaction.source.statement,
        "amount": (
            float(transaction.source.amount)
            if transaction.source.amount is not None
            else None
        ),
        "direction": transaction.direction,
        "original_category": transaction.source.original_category,
        "category": trusted.category,
        "notes": trusted.note,
    }
