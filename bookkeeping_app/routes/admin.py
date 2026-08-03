"""Administrative and operational routes.

The URL prefix organizes admin-facing operations; authorization is deferred.
"""

from fastapi import APIRouter

from bookkeeping_app.metrics import metrics

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/openai-usage")
def openai_usage() -> dict[str, int | str]:
    return metrics.snapshot()
