from __future__ import annotations

import pytest
from fastapi import status
from httpx import ASGITransport, AsyncClient

from backend.gateway.config import settings
from backend.gateway.db.models import UserRole

from .utils import create_user


@pytest.mark.asyncio
async def test_login_rate_limit_blocks_after_five_attempts(app, db_session):
    await create_user(
        db_session,
        email="ratelimit@example.com",
        username="ratelimit",
        password="correct-horse",
        roles=[UserRole.MEMBER.value],
    )

    attempt_limit = settings.auth.login_rate_limit_attempts
    captcha_threshold = settings.auth.login_captcha_failure_threshold

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        for attempt in range(attempt_limit):
            payload: dict[str, str] = {
                "email": "ratelimit@example.com",
                "password": "wrong-password",
            }
            if attempt + 1 > captcha_threshold:
                payload["captchaToken"] = "valid-captcha"
            response = await client.post("/auth/login", json=payload)
            assert response.status_code == status.HTTP_401_UNAUTHORIZED

        final_payload = {
            "email": "ratelimit@example.com",
            "password": "wrong-password",
            "captchaToken": "valid-captcha",
        }
        blocked = await client.post("/auth/login", json=final_payload)

    assert blocked.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    assert blocked.json()["detail"] == "Too many login attempts. Try again later."


@pytest.mark.asyncio
async def test_captcha_required_after_three_failures(app, db_session):
    await create_user(
        db_session,
        email="captcha@example.com",
        username="captcha",
        password="correct-horse",
        roles=[UserRole.MEMBER.value],
    )

    captcha_threshold = settings.auth.login_captcha_failure_threshold

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        for _ in range(captcha_threshold):
            response = await client.post(
                "/auth/login",
                json={"email": "captcha@example.com", "password": "bad"},
            )
            assert response.status_code == status.HTTP_401_UNAUTHORIZED

        challenge = await client.post(
            "/auth/login",
            json={"email": "captcha@example.com", "password": "correct-horse"},
        )
        assert challenge.status_code == status.HTTP_403_FORBIDDEN
        assert challenge.json()["detail"] == "CAPTCHA verification required"

        success = await client.post(
            "/auth/login",
            json={
                "email": "captcha@example.com",
                "password": "correct-horse",
                "captchaToken": "valid-captcha",
            },
        )

    assert success.status_code == status.HTTP_200_OK
    body = success.json()
    assert body["accessToken"]
    assert body["user"]["email"] == "captcha@example.com"


@pytest.mark.asyncio
async def test_successful_login_resets_counters(app, db_session):
    await create_user(
        db_session,
        email="reset@example.com",
        username="reset",
        password="correct-horse",
        roles=[UserRole.MEMBER.value],
    )

    captcha_threshold = settings.auth.login_captcha_failure_threshold

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        for _ in range(captcha_threshold):
            response = await client.post(
                "/auth/login",
                json={"email": "reset@example.com", "password": "bad"},
            )
            assert response.status_code == status.HTTP_401_UNAUTHORIZED

        initial_success = await client.post(
            "/auth/login",
            json={
                "email": "reset@example.com",
                "password": "correct-horse",
                "captchaToken": "valid-captcha",
            },
        )
        assert initial_success.status_code == status.HTTP_200_OK

        second_success = await client.post(
            "/auth/login",
            json={"email": "reset@example.com", "password": "correct-horse"},
        )

    assert second_success.status_code == status.HTTP_200_OK
