"""Common FastAPI dependency helpers."""
from __future__ import annotations

from typing import AsyncIterator, Iterable, Set

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer, SecurityScopes
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

try:
    from gateway.db.base import create_session  # type: ignore
    from gateway.db.models import Role, User, UserRole, user_roles_table  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - fallback when running from backend/
    from backend.gateway.db.base import create_session  # type: ignore
    from backend.gateway.db.models import Role, User, UserRole, user_roles_table  # type: ignore

from .security import TokenData, validate_bearer_token


async def get_session() -> AsyncIterator[AsyncSession]:
    """Provide an async SQLAlchemy session."""

    session = create_session()
    try:
        yield session
    finally:  # pragma: no cover - cleanup
        await session.close()


_bearer_scheme = HTTPBearer(auto_error=False)


async def _get_token_data(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> TokenData:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return validate_bearer_token(credentials.credentials)


def _normalise_role(role: UserRole | str) -> str:
    return role.value if isinstance(role, UserRole) else str(role)


def _normalise_role(role: UserRole | str) -> str:
    return role.value if isinstance(role, UserRole) else str(role)


def _resolve_identity(token: TokenData) -> tuple[int | None, str | None, str | None]:
    subject = token.subject.strip()
    user_id: int | None = None
    email: str | None = None
    username: str | None = None

    if subject.isdigit():
        user_id = int(subject)
    else:
        candidate = subject.split(":")[-1]
        if candidate.isdigit():
            user_id = int(candidate)

    raw_email = token.claims.get("email")
    if isinstance(raw_email, str):
        cleaned_email = raw_email.strip().lower()
        email = cleaned_email or None

    raw_username = token.claims.get("preferred_username")
    if isinstance(raw_username, str):
        candidate_username = raw_username.strip().lower()
        username = candidate_username or None

    return user_id, email, username


async def get_current_user(
    security_scopes: SecurityScopes,
    token: TokenData = Depends(_get_token_data),
    db: AsyncSession = Depends(get_session),
) -> User:
    bind = db.bind
    if bind is not None and bind.dialect.name == "sqlite":
        metadata = User.metadata
        if metadata.schema or any(table.schema for table in metadata.tables.values()):
            metadata.schema = None
            for table in metadata.tables.values():
                table.schema = None

    user_id, email, username = _resolve_identity(token)

    stmt = select(User).options(selectinload(User.roles).selectinload(Role.permissions))
    if user_id is not None:
        stmt = stmt.where(User.id == user_id)
    elif email is not None:
        stmt = stmt.where(func.lower(User.email) == email)
    elif username is not None:
        stmt = stmt.where(func.lower(User.username) == username)
    else:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    result = await db.execute(stmt)
    user = result.scalars().first()
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="User not found")
    if not user.active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Account is suspended")

    required_scopes = set(security_scopes.scopes)
    if required_scopes:
        granted_roles = set(token.roles)
        granted_roles.update(token.scopes)
        granted_roles.update(role.slug for role in user.roles)
        if required_scopes.isdisjoint(granted_roles):
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Insufficient role")

    setattr(user, "token_data", token)
    return user


def RequireRoles(*roles: UserRole | str) -> callable:
    """Ensure the current user carries at least one of the supplied roles."""

    if not roles:
        raise ValueError("At least one role must be provided")
    required = {_normalise_role(role) for role in roles}

    async def dependency(
        current_user: User = Security(get_current_user, scopes=list(required)),
    ) -> User:
        return current_user

    return dependency


def RequirePermissions(*permissions: str, roles: Iterable[UserRole | str] | None = None) -> callable:
    """Enforce that the authenticated user possesses specific permissions."""

    if not permissions:
        raise ValueError("At least one permission must be provided")
    required_permissions: Set[str] = set(permissions)
    required_roles = [
        _normalise_role(role)
        for role in (roles or [])
    ]

    async def dependency(
        current_user: User = Security(get_current_user, scopes=required_roles),
    ) -> User:
        granted = set(current_user.permissions)
        if required_permissions.issubset(granted):
            return current_user
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    return dependency


__all__ = [
    "get_session",
    "get_current_user",
    "RequireRoles",
    "RequirePermissions",
]
