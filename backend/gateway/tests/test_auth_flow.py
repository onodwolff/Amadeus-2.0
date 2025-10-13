"""Authentication flow integration tests."""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from backend.gateway.db.models import AuthSession, UserRole

from .utils import create_user


@pytest.mark.asyncio
async def test_login_and_refresh_flow(app, db_session):
    await create_user(
        db_session,
        email="admin@example.com",
        username="admin",
        password="secret",
        roles=[UserRole.ADMIN.value],
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        login_response = await client.post(
            "/auth/login",
            json={"email": "admin@example.com", "password": "secret"},
        )
        assert login_response.status_code == 200
        token_payload = login_response.json()
        assert token_payload["tokenType"] == "bearer"
        assert token_payload["expiresIn"] > 0
        assert token_payload["user"]["isAdmin"] is True
        assert "refreshToken" not in token_payload

        refresh_cookie = login_response.cookies.get("refreshToken")
        assert refresh_cookie

        access_token = token_payload["accessToken"]

        me_response = await client.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert me_response.status_code == 200
        me_payload = me_response.json()
        assert me_payload["email"] == "admin@example.com"
        assert set(me_payload["roles"]) == {UserRole.ADMIN.value}
        assert "gateway.admin" in me_payload["permissions"]

        refresh_response = await client.post(
            "/auth/refresh",
            cookies={"refreshToken": refresh_cookie},
        )
        assert refresh_response.status_code == 200
        refreshed = refresh_response.json()
        assert refreshed["accessToken"]
        assert isinstance(refreshed["accessToken"], str)
        assert refreshed["user"]["email"] == "admin@example.com"
        assert "refreshToken" not in refreshed

        refreshed_cookie = refresh_response.cookies.get("refreshToken")
        assert refreshed_cookie
        assert refreshed_cookie != refresh_cookie

    result = await db_session.execute(select(AuthSession))
    sessions = result.scalars().all()
    assert len(sessions) == 2
    revoked = [session for session in sessions if session.revoked_at is not None]
    assert len(revoked) == 1


@pytest.mark.asyncio
async def test_login_rejects_invalid_credentials(app, db_session):
    await create_user(
        db_session,
        email="member@example.com",
        username="member",
        password="correct-password",
        roles=[UserRole.MEMBER.value],
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(
            "/auth/login",
            json={"email": "member@example.com", "password": "wrong"},
        )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials"


@pytest.mark.asyncio
async def test_logout_revokes_refresh_token(app, db_session):
    await create_user(
        db_session,
        email="viewer@example.com",
        username="viewer",
        password="logout-pass",
        roles=[UserRole.VIEWER.value],
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        login_response = await client.post(
            "/auth/login",
            json={"email": "viewer@example.com", "password": "logout-pass"},
        )
        refresh_cookie = login_response.cookies.get("refreshToken")
        assert refresh_cookie

        logout_response = await client.post(
            "/auth/logout",
            cookies={"refreshToken": refresh_cookie},
        )
        assert logout_response.status_code == 200
        assert logout_response.json()["detail"] == "Logged out"
        cookie_header = logout_response.headers.get("set-cookie", "")
        assert "refreshToken=" in cookie_header

    result = await db_session.execute(select(AuthSession))
    sessions = result.scalars().all()
    assert len(sessions) == 1
    assert sessions[0].revoked_at is not None
