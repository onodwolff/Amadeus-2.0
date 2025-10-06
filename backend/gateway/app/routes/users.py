"""FastAPI routes for managing user account settings."""
from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone
from typing import AsyncIterator

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHash, VerifyMismatchError
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.base import create_session
from gateway.db.models import User


router = APIRouter(prefix="/settings", tags=["settings"])
_password_hasher = PasswordHasher()


async def get_session() -> AsyncIterator[AsyncSession]:
    """Provide an async database session dependency."""

    session = create_session()
    try:
        yield session
    finally:  # pragma: no cover - cleanup
        await session.close()


class AccountResource(BaseModel):
    """Serialized account profile returned to clients."""

    id: str
    name: str | None = None
    email: str
    username: str
    role: str
    active: bool = True
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(populate_by_name=True)


class AccountResponse(BaseModel):
    account: AccountResource


class AccountUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = None
    username: str | None = Field(default=None, min_length=3, max_length=64)

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("Name cannot be empty")
        return trimmed

    @field_validator("email")
    @classmethod
    def _validate_email(cls, value: EmailStr | None) -> EmailStr | None:
        if value is None:
            return None
        return EmailStr(str(value).strip().lower())

    @field_validator("username")
    @classmethod
    def _validate_username(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("Login cannot be empty")
        return trimmed


class PasswordUpdateRequest(BaseModel):
    current_password: str = Field(..., alias="currentPassword", min_length=1)
    new_password: str = Field(..., alias="newPassword", min_length=8)

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


def _serialize_account(user: User) -> AccountResource:
    return AccountResource(
        id=str(user.id),
        name=user.name,
        email=user.email,
        username=user.username,
        role=user.role.value if getattr(user, "role", None) else "member",
        active=True,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


async def _load_primary_user(session: AsyncSession) -> User:
    result = await session.execute(select(User).order_by(User.id.asc()).limit(1))
    user = result.scalars().first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No user account configured")
    return user


def _hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def _verify_password(stored_hash: str, candidate: str) -> bool:
    try:
        return _password_hasher.verify(stored_hash, candidate)
    except VerifyMismatchError:
        return False
    except InvalidHash:
        legacy = hashlib.sha256(candidate.encode("utf-8")).hexdigest()
        return hmac.compare_digest(stored_hash, legacy)


@router.get("/account", response_model=AccountResponse)
async def get_account_settings(session: AsyncSession = Depends(get_session)) -> AccountResponse:
    user = await _load_primary_user(session)
    return AccountResponse(account=_serialize_account(user))


@router.put("/account", response_model=AccountResponse)
async def update_account_settings(
    payload: AccountUpdateRequest,
    session: AsyncSession = Depends(get_session),
) -> AccountResponse:
    user = await _load_primary_user(session)

    changed = False

    if payload.name is not None and payload.name != user.name:
        user.name = payload.name
        changed = True

    if payload.email is not None and payload.email != user.email:
        normalized_email = str(payload.email)
        duplicate_email_stmt = (
            select(User.id)
            .where(func.lower(User.email) == normalized_email.lower())
            .where(User.id != user.id)
        )
        duplicate_email = await session.execute(duplicate_email_stmt)
        if duplicate_email.scalars().first():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email is already in use")
        user.email = normalized_email
        changed = True

    if payload.username is not None and payload.username != user.username:
        normalized_username = payload.username
        duplicate_username_stmt = (
            select(User.id)
            .where(func.lower(User.username) == normalized_username.lower())
            .where(User.id != user.id)
        )
        duplicate_username = await session.execute(duplicate_username_stmt)
        if duplicate_username.scalars().first():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Login is already taken")
        user.username = normalized_username
        changed = True

    if changed:
        user.updated_at = datetime.now(timezone.utc)
        await session.commit()

    await session.refresh(user)

    return AccountResponse(account=_serialize_account(user))


@router.put("/password", response_model=AccountResponse)
async def update_password(
    payload: PasswordUpdateRequest,
    session: AsyncSession = Depends(get_session),
) -> AccountResponse:
    user = await _load_primary_user(session)

    if not _verify_password(user.pwd_hash, payload.current_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")

    user.pwd_hash = _hash_password(payload.new_password)
    user.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(user)

    return AccountResponse(account=_serialize_account(user))

