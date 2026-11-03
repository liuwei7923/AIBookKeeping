"""Application entrypoint that loads environment variables and exposes the FastAPI app."""

from dotenv import load_dotenv

load_dotenv()

from bookkeeping_app.api import app  # noqa: E402, I001 -- load configuration first
