"""Common FastAPI dependency helpers."""
from __future__ import annotations

from typing import AsyncIterator, Iterable, Set, Tuple

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

from .bruteforce import BruteForceProtector
from .captcha import CaptchaVerifier
from .config import settings
from .email import EmailDispatcher
from .security import TokenData, validate_bearer_token
from .storage import build_cache


async def get_session() -> AsyncIterator[AsyncSession]:
    """Provide an async SQLAlchemy session."""

    session = create_session()
    try:
        yield session
    finally:  # pragma: no cover - cleanup
        await session.close()


_bearer_scheme = HTTPBearer(auto_error=False)


_email_dispatcher = EmailDispatcher()
_bruteforce_cache = build_cache(settings.redis_url)
_bruteforce_service = BruteForceProtector(
    cache=_bruteforce_cache,
    max_attempts=settings.auth.login_rate_limit_attempts,
    window_seconds=settings.auth.login_rate_limit_window_seconds,
    captcha_threshold=settings.auth.login_captcha_failure_threshold,
    captcha_ttl_seconds=settings.auth.login_captcha_failure_ttl_seconds,
    namespace=settings.auth.login_rate_limit_namespace,
)
_captcha_verifier = CaptchaVerifier(
    secret_key=settings.auth.captcha_secret_key,
    verification_url=settings.auth.captcha_verification_url,
    timeout_seconds=settings.auth.captcha_timeout_seconds,
    site_key=settings.auth.captcha_site_key,
    test_bypass_token=settings.auth.captcha_test_bypass_token,
)


def get_email_dispatcher() -> EmailDispatcher:
    """Return the configured e-mail dispatcher instance."""

    return _email_dispatcher


def get_bruteforce_service() -> BruteForceProtector:
    """Return the configured brute force protection helper."""

    return _bruteforce_service


def get_captcha_verifier() -> CaptchaVerifier:
    """Return the configured CAPTCHA verifier."""

    return _captcha_verifier


_ROLE_SLUGS = {role.value for role in UserRole}


def _normalise_scope(scope: str) -> str | None:
    """Return a lowercase trimmed representation of ``scope``."""

    cleaned = scope.strip()
    if not cleaned:
        return None
    return cleaned.lower()


def _classify_required_scopes(scopes: Iterable[str]) -> Tuple[set[str], set[str]]:
    """Split required scopes into role slugs and permission codes."""

    required_roles: set[str] = set()
    required_permissions: set[str] = set()
    for raw in scopes:
        normalised = _normalise_scope(raw)
        if not normalised:
            continue
        if normalised in _ROLE_SLUGS:
            required_roles.add(normalised)
        else:
            required_permissions.add(normalised)
    return required_roles, required_permissions


def _scope_grants_permission(scope: str, permission: str) -> bool:
    """Return ``True`` when the provided OAuth scope grants ``permission``."""

    normalised_scope = _normalise_scope(scope)
    if normalised_scope is None:
        return False
    target = permission.lower()
    if normalised_scope == target:
        return True
    transformed = normalised_scope.replace(":", ".").replace("/", ".")
    return transformed == target


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

    required_roles, required_permissions = _classify_required_scopes(security_scopes.scopes)
    if required_roles:
        user_roles = {role.slug for role in user.roles}
        if user_roles.isdisjoint(required_roles):
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Insufficient role")

    if required_permissions:
        user_permissions = {permission.lower() for permission in user.permissions}
        missing_permissions = required_permissions - user_permissions
        if missing_permissions:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

        token_scopes = [scope for scope in token.scopes if _normalise_scope(scope)]
        if token_scopes:
            missing_scopes = {
                permission
                for permission in required_permissions
                if not any(_scope_grants_permission(scope, permission) for scope in token_scopes)
            }
            if missing_scopes:
                raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Insufficient scope")

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
