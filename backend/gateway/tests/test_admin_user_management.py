from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, status
from pydantic import ValidationError
import sqlalchemy as sa
from sqlalchemy import select

import pytest_asyncio

if "jwt" not in sys.modules:
    sys.modules["jwt"] = SimpleNamespace(
        encode=lambda *args, **kwargs: "token",
        decode=lambda *args, **kwargs: {},
        ExpiredSignatureError=Exception,
        InvalidTokenError=Exception,
    )

if "pyotp" not in sys.modules:
    sys.modules["pyotp"] = SimpleNamespace(
        TOTP=lambda *args, **kwargs: SimpleNamespace(verify=lambda *a, **k: False)
    )

import backend.gateway as backend_gateway
import backend.gateway.app as backend_gateway_app
import backend.gateway.app.dependencies as backend_app_dependencies
import backend.gateway.app.security as backend_app_security
import backend.gateway.config as backend_config
import backend.gateway.db as backend_db
import backend.gateway.db.models as backend_db_models

sys.modules.setdefault("gateway", backend_gateway)
sys.modules.setdefault("gateway.app", backend_gateway_app)
sys.modules.setdefault("gateway.app.dependencies", backend_app_dependencies)
sys.modules.setdefault("gateway.app.security", backend_app_security)
sys.modules.setdefault("gateway.config", backend_config)
sys.modules.setdefault("gateway.db", backend_db)
sys.modules.setdefault("gateway.db.models", backend_db_models)

from backend.gateway.db.base import (
    Base as GatewayBase,
    create_engine,
    create_session,
    dispose_engine,
    metadata as gateway_metadata,
)
from backend.gateway.app.state_sync import Base as EngineBase

gateway_metadata.schema = None
for table in gateway_metadata.tables.values():
    table.schema = None

from backend.gateway.app.routes import admin_users
from backend.gateway.app.security import hash_password, verify_password
from backend.gateway.config import settings
from backend.gateway.db import models as db_models
from backend.gateway.db.models import User, UserRole

_SQLITE_SCHEMA = None

gateway_metadata.schema = _SQLITE_SCHEMA
for table in gateway_metadata.tables.values():
    table.schema = _SQLITE_SCHEMA

db_models.Base.metadata.schema = _SQLITE_SCHEMA
for table in db_models.Base.metadata.tables.values():
    table.schema = _SQLITE_SCHEMA


_DEFAULT_PERMISSIONS = [
    {
        "code": "gateway.admin",
        "name": "Gateway administration",
        "description": "Provides complete access to all administrative actions.",
    },
    {
        "code": "gateway.users.manage",
        "name": "Manage users",
        "description": "Allows creating and editing standard user accounts.",
    },
    {
        "code": "gateway.users.view",
        "name": "View users",
        "description": "Allows viewing basic user information.",
    },
]

_DEFAULT_ROLES = [
    {
        "slug": db_models.UserRole.ADMIN.value,
        "name": "Administrator",
        "description": "Full administrative control over the gateway.",
    },
    {
        "slug": db_models.UserRole.MEMBER.value,
        "name": "Member",
        "description": "Standard user with management capabilities.",
    },
    {
        "slug": db_models.UserRole.VIEWER.value,
        "name": "Viewer",
        "description": "Read-only access to user and node data.",
    },
]

_DEFAULT_ROLE_PERMISSIONS = {
    db_models.UserRole.ADMIN.value: {
        "gateway.admin",
        "gateway.users.manage",
        "gateway.users.view",
    },
    db_models.UserRole.MEMBER.value: {
        "gateway.users.manage",
        "gateway.users.view",
    },
    db_models.UserRole.VIEWER.value: {
        "gateway.users.view",
    },
}


async def _seed_access_control(session) -> None:
    permissions_result = await session.execute(select(db_models.Permission))
    permissions = {permission.code: permission for permission in permissions_result.scalars()}

    for definition in _DEFAULT_PERMISSIONS:
        permission = permissions.get(definition["code"])
        if permission is None:
            permission = db_models.Permission(**definition)
            session.add(permission)
            await session.flush()
            permissions[permission.code] = permission
        else:
            permission.name = definition["name"]
            permission.description = definition["description"]

    roles_result = await session.execute(select(db_models.Role))
    roles = {role.slug: role for role in roles_result.scalars()}

    for definition in _DEFAULT_ROLES:
        role = roles.get(definition["slug"])
        if role is None:
            role = db_models.Role(**definition)
            session.add(role)
            await session.flush()
            roles[role.slug] = role
        else:
            role.name = definition["name"]
            role.description = definition["description"]

    await session.execute(sa.delete(db_models.role_permissions_table))
    rows: list[dict[str, int]] = []
    for slug, permission_codes in _DEFAULT_ROLE_PERMISSIONS.items():
        role = roles[slug]
        for code in sorted(permission_codes):
            rows.append({"role_id": role.id, "permission_id": permissions[code].id})
    if rows:
        await session.execute(sa.insert(db_models.role_permissions_table), rows)


async def _get_role(session, role: UserRole):
    result = await session.execute(
        select(db_models.Role).where(db_models.Role.slug == role.value)
    )
    role_obj = result.scalars().first()
    assert role_obj is not None
    return role_obj


async def _assign_role(session, user: User, role: UserRole) -> None:
    role_obj = await _get_role(session, role)
    user.roles.append(role_obj)


@pytest_asyncio.fixture(scope="session")
async def db_engine(db_url: str):
    GatewayBase.metadata.schema = None
    for table in GatewayBase.metadata.tables.values():
        table.schema = None
    EngineBase.metadata.schema = None
    for table in EngineBase.metadata.tables.values():
        table.schema = None

    engine = create_engine(
        db_url,
        echo=False,
        future=True,
        execution_options={"schema_translate_map": {"public": None}},
    )
    async with engine.begin() as connection:
        await connection.run_sync(GatewayBase.metadata.create_all)
        await connection.run_sync(EngineBase.metadata.create_all)
    session = create_session()
    try:
        async with session.begin():
            await _seed_access_control(session)
    finally:
        await session.close()
    try:
        yield engine
    finally:
        await dispose_engine()


@pytest.fixture(autouse=True)
def enable_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure administrative routes require authentication during tests."""

    monkeypatch.setattr(settings.auth, "enabled", True)


@pytest.fixture
def log_events(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, object]]]:
    """Capture structured logging emitted by the admin user routes."""

    events: list[tuple[str, dict[str, object]]] = []

    class _Logger:
        def info(self, event: str, **kwargs: object) -> None:
            events.append((event, kwargs))

    monkeypatch.setattr(admin_users, "logger", _Logger())
    return events


@pytest.mark.asyncio
async def test_create_user_as_admin(db_session, log_events):
    admin = User(
        email="admin@example.com",
        username="admin",
        name="Admin",
        password_hash=hash_password("admin-pass-123"),
        email_verified=True,
    )
    await _assign_role(db_session, admin, UserRole.ADMIN)
    db_session.add(admin)
    await db_session.commit()

    payload = admin_users.AdminUserCreateRequest(
        email="New.User@example.com",
        password="S3curePass!",
        username=" new-user ",
        name="  New User  ",
        role=UserRole.VIEWER,
    )

    response = await admin_users.create_user(
        payload=payload, session=db_session, current_user=admin
    )

    resource = response.user
    assert resource.email == "new.user@example.com"
    assert resource.username == "new-user"
    assert resource.name == "New User"
    assert resource.role == UserRole.VIEWER.value
    assert sorted(resource.roles) == [UserRole.VIEWER.value]
    assert resource.active is True
    assert resource.is_admin is False
    assert resource.email_verified is False
    assert resource.mfa_enabled is False

    result = await db_session.execute(select(User).where(User.id == int(resource.id)))
    user = result.scalar_one()
    assert user.username == "new-user"
    assert user.name == "New User"
    assert user.has_role(UserRole.VIEWER)
    assert user.has_role(UserRole.ADMIN) is False
    assert user.active is True
    assert user.is_admin is False
    assert verify_password(user.password_hash, "S3curePass!")
    assert user.email_verified is False
    assert user.mfa_enabled is False
    assert user.mfa_secret is None
    assert user.last_login_at is None

    assert any(
        event == "admin_user.created"
        and details["actor_id"] == str(admin.id)
        and details["actor_email"] == admin.email
        and details["user_id"] == resource.id
        and details["user_email"] == resource.email
        and details["user_username"] == resource.username
        and details["user_role"] == resource.role
        for event, details in log_events
    )


@pytest.mark.asyncio
async def test_create_user_can_set_inactive(db_session):
    admin = User(
        email="admin@example.com",
        username="admin",
        name="Admin",
        password_hash=hash_password("admin-pass-123"),
    )
    await _assign_role(db_session, admin, UserRole.ADMIN)
    db_session.add(admin)
    await db_session.commit()

    payload = admin_users.AdminUserCreateRequest(
        email="inactive@example.com",
        password="S3curePass!",
        name="Inactive User",
        role=UserRole.VIEWER,
        active=False,
    )

    response = await admin_users.create_user(
        payload=payload, session=db_session, current_user=admin
    )

    resource = response.user
    assert resource.active is False

    result = await db_session.execute(select(User).where(User.id == int(resource.id)))
    created = result.scalar_one()
    assert created.active is False


@pytest.mark.asyncio
async def test_create_user_rejects_duplicate_email_or_username(db_session):
    admin = User(
        email="admin@example.com",
        username="admin",
        password_hash=hash_password("admin-pass-123"),
    )
    await _assign_role(db_session, admin, UserRole.ADMIN)
    existing = User(
        email="existing@example.com",
        username="existing",
        password_hash=hash_password("existing-pass"),
    )
    await _assign_role(db_session, existing, UserRole.MEMBER)
    db_session.add_all([admin, existing])
    await db_session.commit()

    duplicate_email = admin_users.AdminUserCreateRequest(
        email="existing@example.com",
        username="unique",
        password="Password123",
    )

    with pytest.raises(HTTPException) as exc_info:
        await admin_users.create_user(
            payload=duplicate_email, session=db_session, current_user=admin
        )
    assert exc_info.value.status_code == status.HTTP_409_CONFLICT

    duplicate_email_case = admin_users.AdminUserCreateRequest(
        email="Existing@Example.com",
        username="unique-case",
        password="Password123",
    )

    with pytest.raises(HTTPException) as exc_info:
        await admin_users.create_user(
            payload=duplicate_email_case, session=db_session, current_user=admin
        )
    assert exc_info.value.status_code == status.HTTP_409_CONFLICT

    duplicate_username = admin_users.AdminUserCreateRequest(
        email="unique@example.com",
        username="existing",
        password="Password123",
    )

    with pytest.raises(HTTPException) as exc_info:
        await admin_users.create_user(
            payload=duplicate_username, session=db_session, current_user=admin
        )
    assert exc_info.value.status_code == status.HTTP_409_CONFLICT

    duplicate_username_case = admin_users.AdminUserCreateRequest(
        email="unique-case@example.com",
        username="Existing",
        password="Password123",
    )

    with pytest.raises(HTTPException) as exc_info:
        await admin_users.create_user(
            payload=duplicate_username_case, session=db_session, current_user=admin
        )
    assert exc_info.value.status_code == status.HTTP_409_CONFLICT


@pytest.mark.asyncio
async def test_create_user_requires_admin_privileges(db_session):
    actor = User(
        email="user@example.com",
        username="user",
        password_hash=hash_password("user-pass-123"),
    )
    await _assign_role(db_session, actor, UserRole.MEMBER)
    db_session.add(actor)
    await db_session.commit()

    payload = admin_users.AdminUserCreateRequest(
        email="member@example.com",
        username="member",
        password="Password123",
    )

    with pytest.raises(HTTPException) as exc_info:
        await admin_users.create_user(
            payload=payload, session=db_session, current_user=actor
        )
    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.asyncio
async def test_create_user_rejects_admin_role(db_session):
    admin = User(
        email="admin@example.com",
        username="admin",
        password_hash=hash_password("admin-pass-123"),
    )
    await _assign_role(db_session, admin, UserRole.ADMIN)
    db_session.add(admin)
    await db_session.commit()

    payload = admin_users.AdminUserCreateRequest(
        email="member@example.com",
        username="member",
        password="Password123",
        role=UserRole.ADMIN,
    )

    with pytest.raises(HTTPException) as exc_info:
        await admin_users.create_user(
            payload=payload, session=db_session, current_user=admin
        )
    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST


def test_create_user_payload_rejects_is_admin_field():
    with pytest.raises(ValidationError):
        admin_users.AdminUserCreateRequest.model_validate(
            {
                "email": "member@example.com",
                "password": "Password123",
                "isAdmin": True,
            }
        )


@pytest.mark.asyncio
async def test_user_admin_role_reflects_assignment(db_session):
    candidate = User(
        email="member-admin-flag@example.com",
        username="member-admin-flag",
        password_hash=hash_password("Password123!"),
    )
    await _assign_role(db_session, candidate, UserRole.MEMBER)
    db_session.add(candidate)
    await db_session.commit()

    assert candidate.is_admin is False

    await _assign_role(db_session, candidate, UserRole.ADMIN)
    await db_session.commit()
    await db_session.refresh(candidate)

    assert candidate.is_admin is True


@pytest.mark.asyncio
async def test_update_user_toggle_active_and_name(db_session, log_events):
    admin = User(
        email="admin@example.com",
        username="admin",
        password_hash=hash_password("admin-pass-123"),
    )
    target = User(
        email="member@example.com",
        username="member",
        name="Member User",
        password_hash=hash_password("Password123!"),
        active=True,
    )
    await _assign_role(db_session, admin, UserRole.ADMIN)
    await _assign_role(db_session, target, UserRole.MEMBER)
    db_session.add_all([admin, target])
    await db_session.commit()

    deactivate = admin_users.AdminUserUpdateRequest(active=False, name="  New Name  ")
    response = await admin_users.update_user(
        user_id=target.id,
        payload=deactivate,
        session=db_session,
        current_user=admin,
    )

    assert response.user.active is False
    assert response.user.name == "New Name"

    refreshed = await db_session.get(User, target.id)
    assert refreshed is not None
    await db_session.refresh(refreshed)
    assert refreshed.active is False
    assert refreshed.name == "New Name"

    assert any(
        event == "admin_user.updated"
        and details["user_id"] == str(target.id)
        and "active" in details["changed_fields"]
        for event, details in log_events
    )

    reactivate = admin_users.AdminUserUpdateRequest(active=True)
    result = await admin_users.update_user(
        user_id=target.id,
        payload=reactivate,
        session=db_session,
        current_user=admin,
    )

    assert result.user.active is True


@pytest.mark.asyncio
async def test_update_user_rejects_duplicate_username(db_session):
    admin = User(
        email="admin@example.com",
        username="admin",
        password_hash=hash_password("admin-pass-123"),
    )
    target = User(
        email="member@example.com",
        username="member",
        password_hash=hash_password("Password123!"),
    )
    other = User(
        email="someone@example.com",
        username="someone",
        password_hash=hash_password("Password123!"),
    )
    await _assign_role(db_session, admin, UserRole.ADMIN)
    await _assign_role(db_session, target, UserRole.MEMBER)
    await _assign_role(db_session, other, UserRole.MEMBER)
    db_session.add_all([admin, target, other])
    await db_session.commit()

    payload = admin_users.AdminUserUpdateRequest(username="Someone")

    with pytest.raises(HTTPException) as exc_info:
        await admin_users.update_user(
            user_id=target.id,
            payload=payload,
            session=db_session,
            current_user=admin,
        )

    assert exc_info.value.status_code == status.HTTP_409_CONFLICT


@pytest.mark.asyncio
async def test_update_user_prevents_admin_role_assignment(db_session):
    admin = User(
        email="admin@example.com",
        username="admin",
        password_hash=hash_password("admin-pass-123"),
    )
    target = User(
        email="member@example.com",
        username="member",
        password_hash=hash_password("Password123!"),
    )
    await _assign_role(db_session, admin, UserRole.ADMIN)
    await _assign_role(db_session, target, UserRole.MEMBER)
    db_session.add_all([admin, target])
    await db_session.commit()

    payload = admin_users.AdminUserUpdateRequest(role=UserRole.ADMIN)

    with pytest.raises(HTTPException) as exc_info:
        await admin_users.update_user(
            user_id=target.id,
            payload=payload,
            session=db_session,
            current_user=admin,
        )

    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.asyncio
async def test_update_user_requires_admin_privileges(db_session):
    actor = User(
        email="user@example.com",
        username="user",
        password_hash=hash_password("user-pass-123"),
    )
    target = User(
        email="member@example.com",
        username="member",
        password_hash=hash_password("Password123!"),
    )
    await _assign_role(db_session, actor, UserRole.MEMBER)
    await _assign_role(db_session, target, UserRole.MEMBER)
    db_session.add_all([actor, target])
    await db_session.commit()

    payload = admin_users.AdminUserUpdateRequest(active=False)

    with pytest.raises(HTTPException) as exc_info:
        await admin_users.update_user(
            user_id=target.id,
            payload=payload,
            session=db_session,
            current_user=actor,
        )

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.asyncio
async def test_update_user_updates_password(db_session):
    admin = User(
        email="admin@example.com",
        username="admin",
        password_hash=hash_password("admin-pass-123"),
    )
    target = User(
        email="member@example.com",
        username="member",
        password_hash=hash_password("Password123!"),
    )
    await _assign_role(db_session, admin, UserRole.ADMIN)
    await _assign_role(db_session, target, UserRole.MEMBER)
    db_session.add_all([admin, target])
    await db_session.commit()

    payload = admin_users.AdminUserUpdateRequest(password="NewSecurePass123")

    response = await admin_users.update_user(
        user_id=target.id,
        payload=payload,
        session=db_session,
        current_user=admin,
    )

    refreshed = await db_session.get(User, target.id)
    assert refreshed is not None
    await db_session.refresh(refreshed)
    assert verify_password(refreshed.password_hash, "NewSecurePass123")
    assert response.user.id == str(target.id)

