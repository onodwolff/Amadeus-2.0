"""Administrative user management routes."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm.attributes import set_committed_value
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.app.dependencies import get_session
from gateway.app.logging import get_logger
from gateway.app.security import hash_password
from gateway.config import settings
from gateway.db.models import User, UserRole

from .auth import get_current_user


router = APIRouter(prefix="/users", tags=["users"])

logger = get_logger("gateway.admin.users")


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


class AdminUserUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = None
    username: str | None = Field(default=None, min_length=3, max_length=64)
    role: UserRole | None = None
    active: bool | None = None
    password: str | None = Field(default=None, min_length=8)

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    @field_validator("password")
    @classmethod
    def _normalize_password(cls, value: str | None) -> str | None:
        if value is None:
            return None
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

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: EmailStr | None) -> EmailStr | None:
        if value is None:
            return None
        return EmailStr(str(value).strip().lower())


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


async def _email_in_use_by_other(
    session: AsyncSession, email: str, user_id: int
) -> bool:
    stmt = (
        select(User.id)
        .where(func.lower(User.email) == email.lower())
        .where(User.id != user_id)
    )
    result = await session.execute(stmt)
    return result.scalars().first() is not None


async def _username_in_use_by_other(
    session: AsyncSession, username: str, user_id: int
) -> bool:
    stmt = (
        select(User.id)
        .where(func.lower(User.username) == username.lower())
        .where(User.id != user_id)
    )
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

    actor_id = (
        str(current_user.id)
        if current_user is not None and getattr(current_user, "id", None) is not None
        else None
    )
    logger.info(
        "admin_user.created",
        actor_id=actor_id,
        actor_email=getattr(current_user, "email", None),
        user_id=str(user.id),
        user_email=user.email,
        user_username=user.username,
        user_role=user.role.value if getattr(user, "role", None) else UserRole.MEMBER.value,
    )

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


@router.put("/{user_id}", response_model=AdminUserResponse)
async def update_user(
    user_id: int,
    payload: AdminUserUpdateRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User | None = _CURRENT_USER_DEP,
) -> AdminUserResponse:
    _ensure_admin(current_user)

    user = await session.get(User, user_id, populate_existing=True)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="User not found")

    changed_fields: set[str] = set()

    if payload.active is not None and payload.active != user.active:
        user.active = payload.active
        changed_fields.add("active")

    if payload.name is not None and payload.name != user.name:
        user.name = payload.name
        changed_fields.add("name")

    if payload.email is not None:
        normalized_email = str(payload.email)
        if normalized_email != user.email:
            if await _email_in_use_by_other(session, normalized_email, user.id):
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    detail="Email is already associated with another account.",
                )
            user.email = normalized_email
            changed_fields.add("email")

    if payload.username is not None and payload.username != user.username:
        if await _username_in_use_by_other(session, payload.username, user.id):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail="Username is already associated with another account.",
            )
        user.username = payload.username
        changed_fields.add("username")

    if payload.role is not None and payload.role != user.role:
        if payload.role == UserRole.ADMIN:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, detail="Cannot assign admin role"
            )
        if user.is_admin:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, detail="Cannot modify administrator role"
            )
        user.role = payload.role
        changed_fields.add("role")

    if payload.password is not None:
        user.password_hash = hash_password(payload.password)
        changed_fields.add("password")

    resource = _serialize_user(user)

    if changed_fields:
        user.updated_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(user)
        for instance in session.identity_map.values():
            if isinstance(instance, User) and instance.id == user.id:
                set_committed_value(instance, "active", user.active)
                set_committed_value(instance, "name", user.name)
                set_committed_value(instance, "email", user.email)
                set_committed_value(instance, "username", user.username)
                set_committed_value(instance, "role", user.role)
                set_committed_value(instance, "password_hash", user.password_hash)
                set_committed_value(instance, "updated_at", user.updated_at)
        resource = _serialize_user(user)
        actor_id = (
            str(current_user.id)
            if current_user is not None and getattr(current_user, "id", None) is not None
            else None
        )
        logger.info(
            "admin_user.updated",
            actor_id=actor_id,
            actor_email=getattr(current_user, "email", None),
            user_id=str(user.id),
            user_email=user.email,
            user_username=user.username,
            changed_fields=sorted(changed_fields),
        )

    return AdminUserResponse(user=resource)
