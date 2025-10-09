from __future__ import annotations

import pytest
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.gateway.app.routes import auth
from backend.gateway.app.security import hash_password, verify_password
from backend.gateway.db.models import User, UserRole


@pytest.mark.asyncio
async def test_create_user_as_admin(db_session):
    admin = User(
        email="admin@example.com",
        username="admin",
        name="Admin",
        password_hash=hash_password("admin-pass-123"),
        role=UserRole.ADMIN,
        is_admin=True,
        email_verified=True,
    )
    db_session.add(admin)
    await db_session.commit()

    payload = auth.UserCreatePayload(
        email="New.User@example.com",
        username=" new-user ",
        password="S3curePass!",
        name="  New User  ",
        role=UserRole.VIEWER,
        isAdmin=False,
        emailVerified=False,
    )

    resource = await auth.create_user(payload=payload, current_user=admin, db=db_session)

    assert resource.email == "new.user@example.com"
    assert resource.is_admin is False
    assert resource.email_verified is False
    assert resource.mfa_enabled is False
    assert resource.last_login_at is None

    result = await db_session.execute(select(User).where(User.id == int(resource.id)))
    user = result.scalar_one()
    assert user.username == "new-user"
    assert user.name == "New User"
    assert user.role == UserRole.VIEWER
    assert user.is_admin is False
    assert verify_password(user.password_hash, "S3curePass!")
    assert user.email_verified is False
    assert user.mfa_enabled is False
    assert user.mfa_secret is None
    assert user.last_login_at is None


@pytest.mark.asyncio
async def test_create_user_rejects_duplicate_email_or_username(db_session):
    admin = User(
        email="admin@example.com",
        username="admin",
        password_hash=hash_password("admin-pass-123"),
        role=UserRole.ADMIN,
        is_admin=True,
    )
    existing = User(
        email="existing@example.com",
        username="existing",
        password_hash=hash_password("existing-pass"),
        role=UserRole.MEMBER,
        is_admin=False,
    )
    db_session.add_all([admin, existing])
    await db_session.commit()

    duplicate_email = auth.UserCreatePayload(
        email="existing@example.com",
        username="unique",
        password="Password123",
    )

    with pytest.raises(HTTPException) as exc_info:
        await auth.create_user(payload=duplicate_email, current_user=admin, db=db_session)
    assert exc_info.value.status_code == status.HTTP_409_CONFLICT

    duplicate_email_case = auth.UserCreatePayload(
        email="Existing@Example.com",
        username="unique-case",
        password="Password123",
    )

    with pytest.raises(HTTPException) as exc_info:
        await auth.create_user(
            payload=duplicate_email_case, current_user=admin, db=db_session
        )
    assert exc_info.value.status_code == status.HTTP_409_CONFLICT

    duplicate_username = auth.UserCreatePayload(
        email="unique@example.com",
        username="existing",
        password="Password123",
    )

    with pytest.raises(HTTPException) as exc_info:
        await auth.create_user(payload=duplicate_username, current_user=admin, db=db_session)
    assert exc_info.value.status_code == status.HTTP_409_CONFLICT

    duplicate_username_case = auth.UserCreatePayload(
        email="unique-case@example.com",
        username="Existing",
        password="Password123",
    )

    with pytest.raises(HTTPException) as exc_info:
        await auth.create_user(
            payload=duplicate_username_case, current_user=admin, db=db_session
        )
    assert exc_info.value.status_code == status.HTTP_409_CONFLICT


@pytest.mark.asyncio
async def test_create_user_requires_admin_privileges(db_session):
    actor = User(
        email="user@example.com",
        username="user",
        password_hash=hash_password("user-pass-123"),
        role=UserRole.MEMBER,
        is_admin=False,
    )
    db_session.add(actor)
    await db_session.commit()

    payload = auth.UserCreatePayload(
        email="member@example.com",
        username="member",
        password="Password123",
    )

    with pytest.raises(HTTPException) as exc_info:
        await auth.create_user(payload=payload, current_user=actor, db=db_session)
    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.asyncio
async def test_user_admin_role_consistency_enforced(db_session):
    inconsistent_admin_flag = User(
        email="member-admin-flag@example.com",
        username="member-admin-flag",
        password_hash=hash_password("Password123!"),
        role=UserRole.MEMBER,
        is_admin=True,
    )
    db_session.add(inconsistent_admin_flag)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()

    inconsistent_role = User(
        email="admin-role@example.com",
        username="admin-role",
        password_hash=hash_password("Password123!"),
        role=UserRole.ADMIN,
        is_admin=False,
    )
    db_session.add(inconsistent_role)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()
