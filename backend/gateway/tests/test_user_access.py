"""User API access control tests."""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from backend.gateway.db.models import UserRole

from .utils import create_user


@pytest.mark.asyncio
async def test_user_listing_requires_authentication(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/users")
    assert response.status_code == 401
    assert response.json()["detail"] == "Not authenticated"


@pytest.mark.asyncio
async def test_viewer_can_list_users(app, db_session):
    await create_user(
        db_session,
        email="viewer@example.com",
        username="viewer",
        password="password",
        roles=[UserRole.VIEWER.value],
    )
    await create_user(
        db_session,
        email="member@example.com",
        username="member",
        password="password",
        roles=[UserRole.MEMBER.value],
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        login_response = await client.post(
            "/auth/login",
            json={"email": "viewer@example.com", "password": "password"},
        )
        token = login_response.json()["accessToken"]
        response = await client.get(
            "/users",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 200
    payload = response.json()
    assert any(user["email"] == "member@example.com" for user in payload)
    assert any(user["email"] == "viewer@example.com" for user in payload)
