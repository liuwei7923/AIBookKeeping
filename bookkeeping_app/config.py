"""Central configuration values and file paths used across the application."""

from pathlib import Path

ALLOWED_IMAGE_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
ALLOWED_CSV_CONTENT_TYPES = {
    "text/csv",
    "application/csv",
    "application/vnd.ms-excel",
    "application/octet-stream",
}
MODEL_NAME = "gpt-4.1-mini"
MAX_CATEGORY_CONTEXT_ITEMS = 20
DATA_DIR = Path("data")
CATEGORIZATION_MEMORY_PATH = DATA_DIR / "categorization_memory.json"
