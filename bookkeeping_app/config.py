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
BEAM_MODEL_NAME = os.getenv("BEAM_MODEL", "Beam-1.0-501B-A23B")
DEFAULT_AI_BATCH_SIZE = 25
MAX_CATEGORY_CONTEXT_ITEMS = 20
DEFAULT_MEMORY_CANDIDATE_LIMIT = 5
DEFAULT_MERCHANT_CONSENSUS_THRESHOLD = 2
DATA_DIR = Path("data")
CATEGORIZATION_MEMORY_PATH = Path(
    os.getenv(
        "CATEGORIZATION_MEMORY_PATH", str(DATA_DIR / "categorization_memory.json")
    )
)
