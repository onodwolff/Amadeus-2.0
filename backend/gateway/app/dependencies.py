"""Common FastAPI dependency helpers."""
from __future__ import annotations

from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.base import create_session


async def get_session() -> AsyncIterator[AsyncSession]:
    """Provide an async SQLAlchemy session."""

    session = create_session()
    try:
        yield session
    finally:  # pragma: no cover - cleanup
        await session.close()
