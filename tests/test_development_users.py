import json
from pathlib import Path
from uuid import UUID

import pytest
from fastapi import HTTPException

from bookkeeping_app.domain_contracts import User
from bookkeeping_app.request_identity import resolve_user_id

WEI_USER_ID = UUID("8a802680-06be-4815-986b-58b88392acfc")
JIA_USER_ID = UUID("0c050ed3-d41b-468c-9c29-e9e6da905c04")


def test_development_user_catalog_contains_valid_distinct_users() -> None:
    catalog_path = Path("config/development_users.json")
    users = [
        User.model_validate(item)
        for item in json.loads(catalog_path.read_text(encoding="utf-8"))
    ]

    assert [user.display_name for user in users] == ["Wei Liu", "Jia Zhang"]
    assert len({user.user_id for user in users}) == len(users)


def test_explicit_user_id_overrides_development_default(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEV_USER_ID", str(WEI_USER_ID))

    assert resolve_user_id(JIA_USER_ID) == JIA_USER_ID


def test_development_user_id_is_loaded_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEV_USER_ID", str(WEI_USER_ID))

    assert resolve_user_id() == WEI_USER_ID


def test_missing_request_identity_is_rejected_outside_development(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("DEV_USER_ID", raising=False)

    with pytest.raises(HTTPException) as error:
        resolve_user_id()

    assert error.value.status_code == 401
