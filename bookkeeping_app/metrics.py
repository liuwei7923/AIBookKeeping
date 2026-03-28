import logging

from bookkeeping_app.config import MODEL_NAME

logger = logging.getLogger("bookkeeping_app")

if not logger.handlers:
    logging.basicConfig(level=logging.INFO)


class UsageMetrics:
    def __init__(self) -> None:
        self.openai_request_count = 0

    def record_openai_request(self, endpoint_name: str) -> None:
        self.openai_request_count += 1
        logger.info(
            "OpenAI request count=%s endpoint=%s model=%s",
            self.openai_request_count,
            endpoint_name,
            MODEL_NAME,
        )

    def snapshot(self) -> dict[str, int | str]:
        return {
            "model": MODEL_NAME,
            "openai_request_count": self.openai_request_count,
        }


metrics = UsageMetrics()
