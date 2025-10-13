"""Common FastAPI dependency helpers."""
from __future__ import annotations

from typing import AsyncIterator, Set

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

try:
    from gateway.db.base import create_session  # type: ignore
    from gateway.db.models import Role, User, UserRole  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - fallback when running from backend/
    from backend.gateway.db.base import create_session  # type: ignore
    from backend.gateway.db.models import Role, User, UserRole  # type: ignore

from .security import decode_access_token


async def get_session() -> AsyncIterator[AsyncSession]:
    """Provide an async SQLAlchemy session."""

    session = create_session()
    try:
        yield session
    finally:  # pragma: no cover - cleanup
        await session.close()


_bearer_scheme = HTTPBearer(auto_error=False)


async def _get_token_credentials(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, object]:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return decode_access_token(credentials.credentials)


def _normalise_role(role: UserRole | str) -> str:
    return role.value if isinstance(role, UserRole) else str(role)


async def get_current_user(
    payload: dict[str, object] = Depends(_get_token_credentials),
    db: AsyncSession = Depends(get_session),
) -> User:
    user_id = payload.get("sub")
    try:
        user_id_int = int(user_id)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    stmt = (
        select(User)
        .options(selectinload(User.roles).selectinload(Role.permissions))
        .where(User.id == user_id_int)
    )
    result = await db.execute(stmt)
    user = result.scalars().first()
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="User not found")
    if not user.active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Account is suspended")
    return user


class RequireRoles:
    """FastAPI dependency enforcing that the user possesses at least one role."""

    def __init__(self, *roles: UserRole | str) -> None:
        if not roles:
            raise ValueError("At least one role must be provided")
        self._required: Set[str] = {_normalise_role(role) for role in roles}

    async def __call__(self, current_user: User = Depends(get_current_user)) -> User:
        if any(role_slug in self._required for role_slug in current_user.role_slugs):
            return current_user
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Insufficient role")


class RequirePermissions:
    """FastAPI dependency enforcing that the user possesses permissions."""

    def __init__(self, *permissions: str) -> None:
        if not permissions:
            raise ValueError("At least one permission must be provided")
        self._permissions: Set[str] = set(permissions)

    async def __call__(self, current_user: User = Depends(get_current_user)) -> User:
        granted = set(current_user.permissions)
        if self._permissions.issubset(granted):
            return current_user
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")


__all__ = [
    "get_session",
    "get_current_user",
    "RequireRoles",
    "RequirePermissions",
]
