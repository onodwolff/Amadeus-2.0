"""Tests for automatic administrator provisioning on application startup."""
from __future__ import annotations

import sys

import pytest
from sqlalchemy import select

import backend.gateway as backend_gateway
import backend.gateway.db as backend_db
import backend.gateway.db.base as backend_db_base
import backend.gateway.db.models as backend_db_models

sys.modules.setdefault("gateway", backend_gateway)
sys.modules.setdefault("gateway.db", backend_db)
sys.modules.setdefault("gateway.db.base", backend_db_base)
sys.modules.setdefault("gateway.db.models", backend_db_models)

from backend.gateway.app import main as app_main
from backend.gateway.app.security import hash_password, verify_password
from backend.gateway.config import settings
from backend.gateway.db.models import User as DbUser, UserRole

app_main.create_session = backend_db_base.create_session  # type: ignore[attr-defined]
app_main.DbUser = backend_db_models.User  # type: ignore[attr-defined]
app_main.UserRole = backend_db_models.UserRole  # type: ignore[attr-defined]

_ensure_admin_user = app_main._ensure_admin_user


@pytest.fixture
def admin_credentials() -> None:
    """Reset configured admin credentials after each test."""

    original_email = settings.auth.admin_email
    original_password = settings.auth.admin_password
    settings.auth.admin_email = None
    settings.auth.admin_password = None
    try:
        yield
    finally:
        settings.auth.admin_email = original_email
        settings.auth.admin_password = original_password


@pytest.mark.asyncio
async def test_ensure_admin_creates_user(admin_credentials, db_session) -> None:
    """A new administrator account is created when none exists."""

    settings.auth.admin_email = "Volkov.Zheka@Example.COM"
    settings.auth.admin_password = "SuperSecret123"

    await _ensure_admin_user()

    result = await db_session.execute(select(DbUser))
    user = result.scalars().one()

    assert user.email == "volkov.zheka@example.com"
    assert user.username == "volkov.zheka"
    assert user.role == UserRole.ADMIN
    assert user.is_admin is True
    assert user.email_verified is True
    assert user.mfa_enabled is False
    assert user.mfa_secret is None
    assert verify_password(user.password_hash, "SuperSecret123")


@pytest.mark.asyncio
async def test_ensure_admin_updates_existing_user(admin_credentials, db_session) -> None:
    """Existing administrator records are updated instead of duplicated."""

    existing = DbUser(
        email="admin@example.com",
        username="admin",
        name="Existing Admin",
        password_hash=hash_password("initial"),
        role=UserRole.MEMBER,
        is_admin=False,
        email_verified=False,
        mfa_enabled=True,
        mfa_secret="secret",
    )
    db_session.add(existing)
    await db_session.commit()

    settings.auth.admin_email = "Admin@Example.com"
    settings.auth.admin_password = "NewSecret456"

    await _ensure_admin_user()

    await db_session.refresh(existing)

    assert existing.email == "admin@example.com"
    assert verify_password(existing.password_hash, "NewSecret456")
    assert existing.role == UserRole.ADMIN
    assert existing.is_admin is True
    assert existing.email_verified is True
    assert existing.mfa_enabled is False
    assert existing.mfa_secret is None


@pytest.mark.asyncio
async def test_ensure_admin_generates_unique_username(admin_credentials, db_session) -> None:
    """Generated administrator username avoids collisions with existing users."""

    clash = DbUser(
        email="someone@example.com",
        username="volkov.zheka",
        name="Collision",
        password_hash=hash_password("password"),
        role=UserRole.MEMBER,
        is_admin=False,
        email_verified=False,
        mfa_enabled=False,
    )
    db_session.add(clash)
    await db_session.commit()

    settings.auth.admin_email = "Volkov.Zheka@example.com"
    settings.auth.admin_password = "Secret789"

    await _ensure_admin_user()

    result = await db_session.execute(
        select(DbUser).where(DbUser.email == "volkov.zheka@example.com")
    )
    admin = result.scalars().one()

    assert admin.username == "volkov.zheka2"
