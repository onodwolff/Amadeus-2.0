from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException, status
from sqlalchemy import select

from backend.gateway.app.routes import users
from backend.gateway.app.security import hash_password
from backend.gateway.db.models import Role, User, UserRole


@pytest.fixture()
def enable_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    """Temporarily enable authentication checks for settings routes."""

    monkeypatch.setattr(users.settings.auth, "enabled", True)


@pytest.mark.asyncio
async def test_get_account_settings_requires_admin(
    db_session, enable_auth: None
) -> None:
    actor = SimpleNamespace(is_admin=False)
    admin_role = await db_session.scalar(
        select(Role).where(Role.slug == UserRole.ADMIN.value)
    )
    assert admin_role is not None

    user = User(
        email="admin@example.com",
        username="admin",
        password_hash=hash_password("password-123"),
    )
    user.roles.append(admin_role)
    db_session.add(user)
    await db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        await users.get_account_settings(session=db_session, current_user=actor)

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.asyncio
async def test_update_account_settings_requires_admin(
    db_session, enable_auth: None
) -> None:
    actor = SimpleNamespace(is_admin=False)
    admin_role = await db_session.scalar(
        select(Role).where(Role.slug == UserRole.ADMIN.value)
    )
    assert admin_role is not None

    user = User(
        email="admin@example.com",
        username="admin",
        password_hash=hash_password("password-123"),
    )
    user.roles.append(admin_role)
    db_session.add(user)
    await db_session.commit()

    payload = users.AccountUpdateRequest(name="Updated Admin")

    with pytest.raises(HTTPException) as exc_info:
        await users.update_account_settings(
            payload=payload, session=db_session, current_user=actor
        )

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.asyncio
async def test_update_password_requires_admin(db_session, enable_auth: None) -> None:
    actor = SimpleNamespace(is_admin=False)
    admin_role = await db_session.scalar(
        select(Role).where(Role.slug == UserRole.ADMIN.value)
    )
    assert admin_role is not None

    user = User(
        email="admin@example.com",
        username="admin",
        password_hash=hash_password("password-123"),
    )
    user.roles.append(admin_role)
    db_session.add(user)
    await db_session.commit()

    payload = users.PasswordUpdateRequest(
        currentPassword="password-123", newPassword="another-pass-456"
    )

    with pytest.raises(HTTPException) as exc_info:
        await users.update_password(
            payload=payload, session=db_session, current_user=actor
        )

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

