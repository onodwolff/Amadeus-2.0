"""Tests covering password reset and e-mail verification token flows."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update

from backend.gateway.app.token_service import TokenService
from backend.gateway.config import settings
from backend.gateway.db import models as db_models

from .utils import create_user


@pytest.mark.asyncio
async def test_forgot_password_issues_token(app, db_session, email_outbox):
    user = await create_user(
        db_session,
        email="reset@example.com",
        username="reset",
        password="initial-pass",
        roles=[db_models.UserRole.MEMBER.value],
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(
            "/auth/forgot-password",
            json={"email": "reset@example.com"},
        )
    assert response.status_code == 200
    assert response.json()["detail"].startswith("If the account exists")

    assert len(email_outbox) == 1
    message = email_outbox[0]
    assert message["type"] == "password_reset"
    assert message["email"] == "reset@example.com"
    token = message["token"]
    assert token
    expires_at = message["expires_at"]
    assert isinstance(expires_at, datetime)
    now = datetime.now(timezone.utc)
    assert expires_at.tzinfo is not None
    ttl = expires_at - now
    configured_ttl = settings.auth.password_reset_token_ttl_seconds
    assert configured_ttl - 30 <= ttl.total_seconds() <= configured_ttl + 30

    stmt = select(db_models.UserToken).where(
        db_models.UserToken.user_id == user.id,
        db_models.UserToken.purpose == db_models.UserTokenPurpose.PASSWORD_RESET,
    )
    result = await db_session.execute(stmt)
    record = result.scalars().first()
    assert record is not None
    assert record.consumed_at is None

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        reset_response = await client.post(
            "/auth/reset-password",
            json={"token": token, "newPassword": "updated-pass"},
        )
    assert reset_response.status_code == 200
    assert reset_response.json()["detail"] == "Password updated"

    refreshed = await db_session.execute(stmt)
    updated_record = refreshed.scalars().first()
    assert updated_record is not None and updated_record.consumed_at is not None

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        login_response = await client.post(
            "/auth/login",
            json={"email": "reset@example.com", "password": "updated-pass"},
        )
    assert login_response.status_code == 200


@pytest.mark.asyncio
async def test_password_reset_token_expires(app, db_session, email_outbox):
    user = await create_user(
        db_session,
        email="expire@example.com",
        username="expire",
        password="initial-pass",
        roles=[db_models.UserRole.MEMBER.value],
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        await client.post("/auth/forgot-password", json={"email": "expire@example.com"})

    assert email_outbox
    token = email_outbox[0]["token"]

    expire_time = datetime.now(timezone.utc) - timedelta(seconds=30)
    await db_session.execute(
        update(db_models.UserToken)
        .where(
            db_models.UserToken.user_id == user.id,
            db_models.UserToken.purpose == db_models.UserTokenPurpose.PASSWORD_RESET,
        )
        .values(expires_at=expire_time)
    )
    await db_session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(
            "/auth/reset-password",
            json={"token": token, "newPassword": "irrelevant"},
        )
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid or expired token"


@pytest.mark.asyncio
async def test_password_reset_token_is_single_use(app, db_session, email_outbox):
    await create_user(
        db_session,
        email="single@example.com",
        username="single",
        password="initial-pass",
        roles=[db_models.UserRole.MEMBER.value],
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        await client.post("/auth/forgot-password", json={"email": "single@example.com"})
    token = email_outbox[0]["token"]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        success = await client.post(
            "/auth/reset-password",
            json={"token": token, "newPassword": "new-pass"},
        )
        assert success.status_code == 200
        failure = await client.post(
            "/auth/reset-password",
            json={"token": token, "newPassword": "another-pass"},
        )
    assert failure.status_code == 400
    assert failure.json()["detail"] == "Invalid or expired token"


@pytest.mark.asyncio
async def test_email_verification_marks_user_verified(app, db_session):
    user = await create_user(
        db_session,
        email="verify@example.com",
        username="verify",
        password="initial-pass",
        roles=[db_models.UserRole.MEMBER.value],
    )
    service = TokenService(db_session)
    record, token = await service.issue(
        user=user,
        purpose=db_models.UserTokenPurpose.EMAIL_VERIFICATION,
        ttl_seconds=settings.auth.email_verification_token_ttl_seconds,
    )
    await db_session.commit()
    await db_session.refresh(user)
    assert user.email_verified is False

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/auth/verify-email", params={"token": token})
    assert response.status_code == 200
    assert response.json()["detail"] == "Email verified"

    await db_session.refresh(user)
    assert user.email_verified is True

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        reuse = await client.get("/auth/verify-email", params={"token": token})
    assert reuse.status_code == 400
    assert reuse.json()["detail"] == "Invalid or expired token"
