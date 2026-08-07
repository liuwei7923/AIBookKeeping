"""Central configuration values and file paths used across the application."""

import os
from pathlib import Path

ALLOWED_CSV_CONTENT_TYPES = {
    "text/csv",
    "application/csv",
    "application/vnd.ms-excel",
    "application/octet-stream",
}
MODEL_NAME = "gpt-4.1-mini"
MAX_CATEGORY_CONTEXT_ITEMS = 20
DATA_DIR = Path("data")
CATEGORIZATION_MEMORY_PATH = Path(
    os.getenv(
        "CATEGORIZATION_MEMORY_PATH", str(DATA_DIR / "categorization_memory.json")
    )
)
REVIEW_RECORD_PATH = Path(
    os.getenv("REVIEW_RECORD_PATH", str(DATA_DIR / "review_records.json"))
)
