"""Common test fixtures for gateway unit tests."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.elements import TextClause

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

class SQLiteJSONB(sa.JSON):
    def __init__(self, *args, **kwargs):
        kwargs.pop("astext_type", None)
        super().__init__(**kwargs)


postgresql.JSONB = SQLiteJSONB  # type: ignore[attr-defined]

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
