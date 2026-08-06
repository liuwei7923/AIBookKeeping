"""Normalization helpers shared between source and canonical transactions."""

import re

from bookkeeping_app.parsers import sanitize_text

MULTISPACE_PATTERN = re.compile(r"\s+")
PUNCTUATION_PATTERN = re.compile(r"[^a-z0-9\s]")


def _normalize_text(value: str | None) -> str | None:
    cleaned = sanitize_text(value)
    if cleaned is None:
        return None

    lowered = cleaned.lower()
    without_punctuation = PUNCTUATION_PATTERN.sub(" ", lowered)
    collapsed = MULTISPACE_PATTERN.sub(" ", without_punctuation).strip()
    return collapsed or None


def normalize_merchant(value: str | None) -> str | None:
    return _normalize_text(value)


def normalize_statement(value: str | None) -> str | None:
    return _normalize_text(value)
