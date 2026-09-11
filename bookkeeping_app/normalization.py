"""Normalization helpers shared between source and canonical transactions."""

import re
from typing import Any

MULTISPACE_PATTERN = re.compile(r"\s+")
PUNCTUATION_PATTERN = re.compile(r"[^a-z0-9\s]")
CONTROL_CHAR_PATTERN = re.compile(r"[\x00-\x1f\x7f]")


def sanitize_text(value: str | None) -> str | None:
    if value is None:
        return None

    cleaned = CONTROL_CHAR_PATTERN.sub("", value).strip()
    return cleaned or None


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


def normalize_merchant(value: str | None) -> str | None:
    cleaned = sanitize_text(value)
    if cleaned is None:
        return None

    lowered = cleaned.lower()
    without_punctuation = PUNCTUATION_PATTERN.sub(" ", lowered)
    collapsed = MULTISPACE_PATTERN.sub(" ", without_punctuation).strip()
    return collapsed or None
