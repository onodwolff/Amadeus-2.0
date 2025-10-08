"""Database base classes and engine/session helpers."""
from __future__ import annotations

from typing import Any

from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    metadata = metadata


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_engine(database_url: str, **kwargs: Any) -> AsyncEngine:
    """Create (if needed) and cache a global async SQLAlchemy engine."""

    global _engine

    if _engine is None:
        _engine = create_async_engine(database_url, **kwargs)

    return _engine


def init_session_factory(*, expire_on_commit: bool = False) -> async_sessionmaker[AsyncSession]:
    """Initialise the async session factory bound to the cached engine."""

    global _session_factory

    if _session_factory is None:
        if _engine is None:  # pragma: no cover - defensive check
            raise RuntimeError("Database engine has not been initialised")
        _session_factory = async_sessionmaker(
            _engine,
            expire_on_commit=expire_on_commit,
        )

    return _session_factory


def create_engine(database_url: str, **kwargs: Any) -> AsyncEngine:
    """Backwards compatible helper that initialises engine and session factory."""

    engine = init_engine(database_url, **kwargs)
    init_session_factory(expire_on_commit=False)
    return engine


def get_engine() -> AsyncEngine:
    """Return the configured async engine."""

    if _engine is None:  # pragma: no cover - defensive check
        raise RuntimeError("Database engine has not been initialised")
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the async session factory bound to the engine."""

    if _session_factory is None:  # pragma: no cover - defensive check
        raise RuntimeError("Database session factory has not been initialised")
    return _session_factory


def create_session(**kwargs: Any) -> AsyncSession:
    """Instantiate a new :class:`AsyncSession`."""

    factory = get_session_factory()
    return factory(**kwargs)


async def dispose_engine() -> None:
    """Dispose of the cached engine and session factory."""

    global _engine, _session_factory

    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


__all__ = [
    "AsyncEngine",
    "AsyncSession",
    "Base",
    "create_engine",
    "create_session",
    "dispose_engine",
    "get_engine",
    "get_session_factory",
    "init_engine",
    "init_session_factory",
    "metadata",
]
