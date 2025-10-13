"""Tests for the self-service password update endpoint."""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from backend.gateway.db.models import UserRole

from .utils import create_user


@pytest.mark.asyncio
async def test_user_can_change_own_password(app, db_session):
    await create_user(
        db_session,
        email="viewer@example.com",
        username="viewer",
        password="current-password",
        roles=[UserRole.VIEWER.value],
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        login = await client.post(
            "/auth/login",
            json={"email": "viewer@example.com", "password": "current-password"},
        )
        token = login.json()["accessToken"]

        response = await client.patch(
            "/users/me/password",
            headers={"Authorization": f"Bearer {token}"},
            json={"currentPassword": "current-password", "newPassword": "new-password"},
        )

        assert response.status_code == 204

        new_login = await client.post(
            "/auth/login",
            json={"email": "viewer@example.com", "password": "new-password"},
        )
        assert new_login.status_code == 200

        old_login = await client.post(
            "/auth/login",
            json={"email": "viewer@example.com", "password": "current-password"},
        )
        assert old_login.status_code == 401


@pytest.mark.asyncio
async def test_password_change_rejects_incorrect_current_password(app, db_session):
    await create_user(
        db_session,
        email="member@example.com",
        username="member",
        password="correct-password",
        roles=[UserRole.MEMBER.value],
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        login = await client.post(
            "/auth/login",
            json={"email": "member@example.com", "password": "correct-password"},
        )
        token = login.json()["accessToken"]

        response = await client.patch(
            "/users/me/password",
            headers={"Authorization": f"Bearer {token}"},
            json={"currentPassword": "wrong-password", "newPassword": "new-password"},
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid current password"


@pytest.mark.asyncio
async def test_password_change_requires_authentication(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.patch(
            "/users/me/password",
            json={"currentPassword": "irrelevant", "newPassword": "new-password"},
        )

    assert response.status_code == 401
    assert response.json()["detail"] == "Not authenticated"
