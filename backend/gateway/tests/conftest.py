"""Common test fixtures for gateway unit tests."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator, Callable, Iterator
from datetime import timezone
from typing import Any
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.elements import TextClause

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from backend.gateway.app.main import create_app
from backend.gateway.app.dependencies import get_email_dispatcher, get_session
from backend.gateway.app.email import EmailDispatcher
from backend.gateway.config import settings

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

class SQLiteJSONB(sa.JSON):
    def __init__(self, *args, **kwargs):
        kwargs.pop("astext_type", None)
        super().__init__(**kwargs)


postgresql.JSONB = SQLiteJSONB  # type: ignore[attr-defined]


class InMemoryEmailDispatcher(EmailDispatcher):
    def __init__(self) -> None:
        super().__init__()
        self.outbox: list[dict[str, Any]] = []

    async def send_password_reset_email(
        self,
        *,
        email: str,
        token: str,
        expires_at,
    ) -> None:
        normalized = expires_at if getattr(expires_at, "tzinfo", None) else expires_at.replace(tzinfo=timezone.utc)
        self.outbox.append(
            {
                "type": "password_reset",
                "email": email,
                "token": token,
                "expires_at": normalized,
                "url": self.password_reset_url(token),
            }
        )

    async def send_email_verification(
        self,
        *,
        email: str,
        token: str,
        expires_at,
    ) -> None:
        normalized = expires_at if getattr(expires_at, "tzinfo", None) else expires_at.replace(tzinfo=timezone.utc)
        self.outbox.append(
            {
                "type": "email_verification",
                "email": email,
                "token": token,
                "expires_at": normalized,
                "url": self.email_verification_url(token),
            }
        )


def _patch_jsonb(metadata: sa.MetaData) -> None:
    for table in metadata.tables.values():
        for column in table.columns:
            if column.type.__class__.__name__ == 'JSONB':
                column.type = SQLiteJSONB()


from backend.gateway.app.state_sync import Base as EngineBase
from backend.gateway.db import models as db_models
from backend.gateway.db.base import (
    Base as GatewayBase,
    create_engine,
    create_session,
    dispose_engine,
)


def _normalise_defaults(metadata: sa.MetaData) -> None:
    for table in metadata.tables.values():
        for column in table.columns:
            default = column.server_default
            if default is None:
                continue
            clause = getattr(default, "arg", None)
            if isinstance(clause, TextClause):
                text_value = clause.text
                if "::jsonb[]" in text_value:
                    default.arg = sa.text(text_value.replace("::jsonb[]", ""))
                elif "::jsonb" in text_value:
                    default.arg = sa.text(text_value.replace("::jsonb", ""))


_normalise_defaults(db_models.Base.metadata)
_normalise_defaults(EngineBase.metadata)
_patch_jsonb(db_models.Base.metadata)
_patch_jsonb(EngineBase.metadata)
_patch_jsonb(GatewayBase.metadata)


GatewayBase.metadata.schema = None
for table in GatewayBase.metadata.tables.values():
    table.schema = None

EngineBase.metadata.schema = None
for table in EngineBase.metadata.tables.values():
    table.schema = None

db_models.Base.metadata.schema = None
for table in db_models.Base.metadata.tables.values():
    table.schema = None

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
        "slug": db_models.UserRole.MANAGER.value,
        "name": "Manager",
        "description": "Operational management capabilities for trading teams.",
    },
    {
        "slug": db_models.UserRole.TRADER.value,
        "name": "Trader",
        "description": "Trading-focused access for launching and monitoring nodes.",
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
    db_models.UserRole.MANAGER.value: {
        "gateway.users.manage",
        "gateway.users.view",
    },
    db_models.UserRole.TRADER.value: {
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


async def _seed_access_control(session: AsyncSession) -> None:
    permissions_result = await session.execute(sa.select(db_models.Permission))
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

    roles_result = await session.execute(sa.select(db_models.Role))
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
    role_permission_rows = []
    for slug, permission_codes in _DEFAULT_ROLE_PERMISSIONS.items():
        role = roles[slug]
        for code in sorted(permission_codes):
            role_permission_rows.append(
                {"role_id": role.id, "permission_id": permissions[code].id}
            )
    if role_permission_rows:
        await session.execute(
            sa.insert(db_models.role_permissions_table), role_permission_rows
        )


@pytest.fixture(scope="session")
def event_loop() -> Iterator[asyncio.AbstractEventLoop]:
    """Provide a dedicated event loop for async pytest tests."""

    loop = asyncio.new_event_loop()
    try:
        yield loop
    finally:
        loop.close()


@pytest.fixture(scope="session")
def db_url(tmp_path_factory: pytest.TempPathFactory) -> str:
    """Return a SQLite database URL located in a temporary directory."""

    db_path = tmp_path_factory.mktemp("gateway-db") / "test.sqlite3"
    return f"sqlite+aiosqlite:///{db_path}"


@pytest_asyncio.fixture(scope="session")
async def db_engine(db_url: str) -> AsyncIterator[AsyncEngine]:
    """Initialise the global async engine used by gateway tests."""

    engine = create_engine(db_url, echo=False, future=True)
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


@pytest_asyncio.fixture(autouse=True)
async def clean_database(db_engine: AsyncEngine) -> AsyncIterator[None]:
    """Clean up all persisted state after each test case."""

    yield

    async with db_engine.begin() as connection:
        for table in reversed(EngineBase.metadata.sorted_tables):
            await connection.execute(table.delete())
        for table in reversed(GatewayBase.metadata.sorted_tables):
            await connection.execute(table.delete())

    session = create_session()
    try:
        async with session.begin():
            await _seed_access_control(session)
    finally:
        await session.close()


@pytest_asyncio.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Yield an :class:`AsyncSession` bound to the test database."""

    session = create_session()
    try:
        yield session
    finally:
        await session.close()


@pytest.fixture
def session_factory(db_engine: AsyncEngine) -> Callable[[], AsyncSession]:
    """Provide a helper to create fresh async sessions on demand."""

    def factory() -> AsyncSession:
        return create_session()

    return factory




@pytest.fixture
def app(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch):
    """Create a FastAPI test application with database overrides."""

    monkeypatch.setattr(settings.auth, "enabled", True)
    application = create_app()
    email_dispatcher = InMemoryEmailDispatcher()

    async def _override_session():
        yield db_session

    def _override_email_dispatcher() -> EmailDispatcher:
        return email_dispatcher

    application.dependency_overrides[get_session] = _override_session
    application.dependency_overrides[get_email_dispatcher] = _override_email_dispatcher
    application.state.email_dispatcher = email_dispatcher
    return application


@pytest.fixture
def email_outbox(app) -> list[dict[str, Any]]:
    dispatcher: InMemoryEmailDispatcher = app.state.email_dispatcher
    dispatcher.outbox.clear()
    return dispatcher.outbox
