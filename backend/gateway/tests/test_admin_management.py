"""Administrative user and permission management tests."""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from backend.gateway.app.security import create_test_access_token
from backend.gateway.db.models import UserRole

from .utils import create_user


@pytest.mark.asyncio
async def test_viewer_cannot_create_user(app, db_session):
    await create_user(
        db_session,
        email="viewer@example.com",
        username="viewer",
        password="password",
        roles=[UserRole.VIEWER.value],
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        login_response = await client.post(
            "/auth/login",
            json={"email": "viewer@example.com", "password": "password"},
        )
        viewer_token = login_response.json()["accessToken"]

        create_response = await client.post(
            "/admin/users",
            json={
                "email": "new@example.com",
                "password": "temporary",
                "username": "newuser",
                "roles": [UserRole.VIEWER.value],
            },
            headers={"Authorization": f"Bearer {viewer_token}"},
        )
    assert create_response.status_code == 403
    assert create_response.json()["detail"] == "Insufficient role"


@pytest.mark.asyncio
async def test_forged_admin_token_does_not_escalate_privileges(app, db_session):
    viewer = await create_user(
        db_session,
        email="forged@example.com",
        username="forged",
        password="password",
        roles=[UserRole.VIEWER.value],
    )

    forged_token, _ = create_test_access_token(
        subject=viewer.id,
        roles=[UserRole.ADMIN.value],
        scopes=["gateway.admin"],
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get(
            "/admin/roles",
            headers={"Authorization": f"Bearer {forged_token}"},
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "Insufficient role"


@pytest.mark.asyncio
async def test_admin_manages_users_roles_and_permissions(app, db_session):
    await create_user(
        db_session,
        email="admin@example.com",
        username="admin",
        password="password",
        roles=[UserRole.ADMIN.value],
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        login_response = await client.post(
            "/auth/login",
            json={"email": "admin@example.com", "password": "password"},
        )
        admin_token = login_response.json()["accessToken"]

        create_response = await client.post(
            "/admin/users",
            json={
                "email": "managed@example.com",
                "password": "managed-pass",
                "username": "managed",
                "roles": [UserRole.VIEWER.value],
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert create_response.status_code == 200
        managed_user = create_response.json()
        assert managed_user["roles"] == [UserRole.VIEWER.value]
        managed_user_id = managed_user["id"]

        assign_response = await client.post(
            f"/admin/users/{managed_user_id}/roles/{UserRole.MEMBER.value}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert assign_response.status_code == 200
        assert set(assign_response.json()["roles"]) == {UserRole.VIEWER.value, UserRole.MEMBER.value}

        remove_response = await client.delete(
            f"/admin/users/{managed_user_id}/roles/{UserRole.VIEWER.value}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert remove_response.status_code == 200
        assert remove_response.json()["roles"] == [UserRole.MEMBER.value]

        permission_response = await client.post(
            "/admin/permissions",
            json={
                "code": "gateway.reports.view",
                "name": "View reports",
                "description": "Allows access to reporting dashboards.",
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert permission_response.status_code == 200

        update_permissions = await client.post(
            f"/admin/roles/{UserRole.MEMBER.value}/permissions",
            json={"permissions": ["gateway.users.view", "gateway.reports.view"]},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert update_permissions.status_code == 200
        assert set(update_permissions.json()["permissions"]) == {
            "gateway.users.view",
            "gateway.reports.view",
        }

        roles_response = await client.get(
            "/admin/roles",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert roles_response.status_code == 200
        roles_payload = roles_response.json()
        member_role = next(role for role in roles_payload if role["slug"] == UserRole.MEMBER.value)
        assert set(member_role["permissions"]) == {"gateway.users.view", "gateway.reports.view"}
        manager_role = next(role for role in roles_payload if role["slug"] == UserRole.MANAGER.value)
        assert set(manager_role["permissions"]) == {"gateway.users.manage", "gateway.users.view"}
        trader_role = next(role for role in roles_payload if role["slug"] == UserRole.TRADER.value)
        assert set(trader_role["permissions"]) == {"gateway.users.view"}

        login_managed = await client.post(
            "/auth/login",
            json={"email": "managed@example.com", "password": "managed-pass"},
        )
        assert login_managed.status_code == 200
        managed_payload = login_managed.json()["user"]
        assert set(managed_payload["permissions"]) == {"gateway.users.view", "gateway.reports.view"}


@pytest.mark.asyncio
async def test_manager_and_trader_permissions(app, db_session):
    await create_user(
        db_session,
        email="manager@example.com",
        username="manager",
        password="password",
        roles=[UserRole.MANAGER.value],
    )
    await create_user(
        db_session,
        email="trader@example.com",
        username="trader",
        password="password",
        roles=[UserRole.TRADER.value],
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        manager_login = await client.post(
            "/auth/login",
            json={"email": "manager@example.com", "password": "password"},
        )
        assert manager_login.status_code == 200
        manager_permissions = set(manager_login.json()["user"]["permissions"])
        assert manager_permissions == {"gateway.users.manage", "gateway.users.view"}

        trader_login = await client.post(
            "/auth/login",
            json={"email": "trader@example.com", "password": "password"},
        )
        assert trader_login.status_code == 200
        trader_permissions = set(trader_login.json()["user"]["permissions"])
        assert trader_permissions == {"gateway.users.view"}
