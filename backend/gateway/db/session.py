"""FastAPI dependency helpers for acquiring database sessions."""
from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from .base import create_session


async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield an :class:`AsyncSession` for request scoped dependencies."""

    session = create_session()
    try:
        yield session
    finally:
        await session.close()


__all__ = ["get_session"]
