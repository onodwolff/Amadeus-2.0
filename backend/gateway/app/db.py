"""Application level database helpers."""
from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from gateway.db.base import get_engine as _get_engine
from gateway.db.session import get_session as _get_session


def get_engine() -> AsyncEngine:
    """Return the shared application database engine."""

    return _get_engine()


async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield an :class:`AsyncSession` for FastAPI dependencies."""

    async for session in _get_session():
        yield session


__all__ = ["get_engine", "get_session"]
