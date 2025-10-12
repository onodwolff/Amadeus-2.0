"""Administrative user management routes."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.app.dependencies import get_session
from gateway.app.security import hash_password
from gateway.config import settings
from gateway.db.models import User, UserRole

from .auth import get_current_user


router = APIRouter(prefix="/users", tags=["users"])


async def _anonymous_user() -> User | None:
    """Return a sentinel user when authentication is disabled."""

    return None


_CURRENT_USER_DEP = (
    Depends(get_current_user) if settings.auth.enabled else Depends(_anonymous_user)
)


def _ensure_admin(current_user: User | None) -> None:
    """Allow access only to administrators when authentication is enabled."""

    if not settings.auth.enabled:
        return
    if current_user is None or not current_user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Not allowed")


class AdminUserResource(BaseModel):
    """Serialized representation of a user for administrative views."""

    id: str
    email: EmailStr
    username: str
    name: str | None = None
    role: str
    active: bool
    is_admin: bool = Field(alias="isAdmin")
    email_verified: bool = Field(alias="emailVerified")
    mfa_enabled: bool = Field(alias="mfaEnabled")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    model_config = ConfigDict(populate_by_name=True)


class AdminUserResponse(BaseModel):
    user: AdminUserResource


class AdminUsersResponse(BaseModel):
    users: list[AdminUserResource]


class AdminUserCreateRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    username: str | None = Field(default=None, min_length=3, max_length=64)
    name: str | None = Field(default=None, max_length=255)
    role: UserRole = Field(default=UserRole.MEMBER)
    active: bool = Field(default=True)

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    @field_validator("password")
    @classmethod
    def _normalize_password(cls, value: str) -> str:
        trimmed = value.strip()
        if len(trimmed) < 8:
            raise ValueError("Password must be at least 8 characters long")
        return trimmed

    @field_validator("username")
    @classmethod
    def _normalize_username(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("Username cannot be empty")
        return trimmed

    @field_validator("name")
    @classmethod
    def _normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None


def _serialize_user(user: User) -> AdminUserResource:
    return AdminUserResource(
        id=str(user.id),
        email=user.email,
        username=user.username,
        name=user.name,
        role=(user.role.value if getattr(user, "role", None) else UserRole.MEMBER.value),
        active=bool(getattr(user, "active", True)),
        is_admin=bool(user.is_admin),
        email_verified=bool(user.email_verified),
        mfa_enabled=bool(user.mfa_enabled),
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


async def _email_exists(session: AsyncSession, email: str) -> bool:
    stmt = select(User.id).where(func.lower(User.email) == email.lower())
    result = await session.execute(stmt)
    return result.scalars().first() is not None


async def _username_exists(session: AsyncSession, username: str) -> bool:
    stmt = select(User.id).where(func.lower(User.username) == username.lower())
    result = await session.execute(stmt)
    return result.scalars().first() is not None


async def _generate_username(session: AsyncSession, email: str) -> str:
    base = email.split("@", 1)[0].strip()
    if not base:
        base = "user"

    candidate = base
    suffix = 1
    while await _username_exists(session, candidate):
        candidate = f"{base}{suffix}"
        suffix += 1
    return candidate


@router.post("", response_model=AdminUserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: AdminUserCreateRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User | None = _CURRENT_USER_DEP,
) -> AdminUserResponse:
    _ensure_admin(current_user)

    email = str(payload.email).strip().lower()
    if await _email_exists(session, email):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Email is already associated with another account.",
        )

    if payload.role == UserRole.ADMIN:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Cannot assign admin role")

    if payload.username is None:
        username = await _generate_username(session, email)
    else:
        username = payload.username
        if await _username_exists(session, username):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail="Username is already associated with another account.",
            )

    user = User(
        email=email,
        username=username,
        name=payload.name,
        password_hash=hash_password(payload.password),
        role=payload.role,
        active=payload.active,
        is_admin=False,
        email_verified=False,
        mfa_enabled=False,
        mfa_secret=None,
        last_login_at=None,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)

    return AdminUserResponse(user=_serialize_user(user))


@router.get("", response_model=AdminUsersResponse)
async def list_users(
    session: AsyncSession = Depends(get_session),
    current_user: User | None = _CURRENT_USER_DEP,
) -> AdminUsersResponse:
    _ensure_admin(current_user)

    result = await session.execute(select(User).order_by(User.id.asc()))
    users = result.scalars().all()
    return AdminUsersResponse(users=[_serialize_user(user) for user in users])

