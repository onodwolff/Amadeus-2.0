"""Tests ensuring administrator-only actions enforce access controls."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException, status

from backend.gateway.app import main as app_main


@pytest.fixture()
def enable_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    """Temporarily enable authentication for authorization checks."""

    monkeypatch.setattr(app_main.settings.auth, "enabled", True)


def test_update_user_role_requires_admin(enable_auth: None) -> None:
    """Non-administrators cannot escalate their role permissions."""

    actor = SimpleNamespace(id=1, is_admin=False)
    payload = app_main.UserUpdatePayload(role="admin")

    with pytest.raises(HTTPException) as exc_info:
        app_main.update_user("1", payload, current_user=actor)

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN


def test_update_user_active_flag_requires_admin(enable_auth: None) -> None:
    """Non-administrators cannot change activation status."""

    actor = SimpleNamespace(id=1, is_admin=False)
    payload = app_main.UserUpdatePayload(active=False)

    with pytest.raises(HTTPException) as exc_info:
        app_main.update_user("1", payload, current_user=actor)

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN


def test_admin_can_modify_restricted_fields(
    enable_auth: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Administrators retain the ability to manage privileged fields."""

    admin = SimpleNamespace(id=42, is_admin=True)
    captured: dict[str, object] = {}

    def fake_update(user_id: str, payload: dict[str, object]) -> dict[str, object]:
        captured["user_id"] = user_id
        captured["payload"] = payload
        return {"user": {"id": user_id, **payload}}

    monkeypatch.setattr(app_main.svc, "update_user", fake_update)

    payload = app_main.UserUpdatePayload(role="viewer", active=False)
    result = app_main.update_user("24", payload, current_user=admin)

    assert captured["user_id"] == "24"
    assert captured["payload"] == {"role": "viewer", "active": False}
    assert result == {"user": {"id": "24", "role": "viewer", "active": False}}


def test_non_admin_can_modify_allowed_fields(
    enable_auth: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Standard users may still update their own basic profile fields."""

    actor = SimpleNamespace(id=7, is_admin=False)
    captured: dict[str, object] = {}

    def fake_update(user_id: str, payload: dict[str, object]) -> dict[str, object]:
        captured["user_id"] = user_id
        captured["payload"] = payload
        return {"user": {"id": user_id, **payload}}

    monkeypatch.setattr(app_main.svc, "update_user", fake_update)

    payload = app_main.UserUpdatePayload(name="Updated Name", username="updated")
    result = app_main.update_user("7", payload, current_user=actor)

    assert captured["user_id"] == "7"
    assert captured["payload"] == {"name": "Updated Name", "username": "updated"}
    assert result == {
        "user": {
            "id": "7",
            "name": "Updated Name",
            "username": "updated",
        }
    }
