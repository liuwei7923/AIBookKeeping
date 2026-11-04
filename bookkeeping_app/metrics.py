"""Simple in-memory request metrics and logging helpers for OpenAI usage."""

import logging

from bookkeeping_app.config import MODEL_NAME

logger = logging.getLogger("bookkeeping_app")

if not logger.handlers:
    logging.basicConfig(level=logging.INFO)


class UsageMetrics:
    def __init__(self) -> None:
        self.request_counts = {"openai": 0, "beam": 0}

    def record_request(self, provider: str, endpoint_name: str, model: str) -> None:
        if provider not in self.request_counts:
            raise ValueError(f"unsupported review provider: {provider}")
        self.request_counts[provider] += 1
        logger.info(
            "%s request count=%s endpoint=%s model=%s",
            provider.capitalize(),
            self.request_counts[provider],
            endpoint_name,
            model,
        )

    def snapshot(self) -> dict[str, int | str]:
        return {
            "model": MODEL_NAME,
            "openai_request_count": self.request_counts["openai"],
            "beam_request_count": self.request_counts["beam"],
        }


metrics = UsageMetrics()
