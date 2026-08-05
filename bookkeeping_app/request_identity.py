"""Resolve the active user for API requests before authentication exists."""

import json
import os
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import Header, HTTPException
from pydantic import ValidationError

from bookkeeping_app.domain_contracts import User, UserId

DEVELOPMENT_USERS_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "development_users.json"
)


def load_development_users(
    path: Path = DEVELOPMENT_USERS_PATH,
) -> dict[UserId, User]:
    """Load the checked-in catalog keyed by stable user ID."""
    try:
        raw_users = json.loads(path.read_text(encoding="utf-8"))
        users = [User.model_validate(item) for item in raw_users]
    except (OSError, json.JSONDecodeError, ValidationError, TypeError) as exc:
        raise RuntimeError(f"Invalid development user catalog: {path}") from exc

    return {user.user_id: user for user in users}


def resolve_user_id(explicit_user_id: UserId | None = None) -> UserId:
    """Prefer an explicit request identity, then use the local dev default."""
    if explicit_user_id is not None:
        return explicit_user_id

    if os.getenv("APP_ENV") != "development":
        raise HTTPException(status_code=401, detail="X-User-Id header is required")

    configured_user_id = os.getenv("DEV_USER_ID")
    if not configured_user_id:
        raise HTTPException(
            status_code=500,
            detail="DEV_USER_ID must be configured in development",
        )

    try:
        user_id = UUID(configured_user_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=500,
            detail="DEV_USER_ID must be a valid UUID",
        ) from exc

    if user_id not in load_development_users():
        raise HTTPException(
            status_code=500,
            detail="DEV_USER_ID must reference config/development_users.json",
        )

    return user_id


def request_user_id(
    x_user_id: Annotated[UUID | None, Header(alias="X-User-Id")] = None,
) -> UserId:
    """FastAPI dependency for the temporary request identity contract."""
    return resolve_user_id(x_user_id)
