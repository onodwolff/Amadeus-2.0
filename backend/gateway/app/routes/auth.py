"""Authentication API endpoints."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, Security, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import sys

try:  # pragma: no cover - prefer local backend package in tests
    from backend.gateway.db import base as db_base  # type: ignore
    from backend.gateway.db import models as db_models  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - production installs
    from gateway.db import base as db_base  # type: ignore
    from gateway.db import models as db_models  # type: ignore

AuthSession = db_models.AuthSession
Role = db_models.Role
User = db_models.User

if db_models.__name__.startswith("backend."):
    sys.modules.setdefault("gateway.db.models", db_models)
    sys.modules.setdefault("gateway.db.base", db_base)
    db_models.Base.metadata.schema = None
    for table in db_models.Base.metadata.tables.values():
        table.schema = None


def _ensure_test_schema() -> None:
    if not db_models.__name__.startswith("backend."):
        return
    if not User.__table__.schema and not Role.__table__.schema and not AuthSession.__table__.schema:
        return
    for table in (User.__table__, Role.__table__, AuthSession.__table__):
        table.schema = None

from ..config import settings
from ..dependencies import get_current_user, get_session
from ..security import (
    create_test_access_token,
    create_test_refresh_token,
    hash_refresh_token,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


class UserResource(BaseModel):
    id: int
    email: EmailStr
    username: str
    name: str | None = None
    roles: list[str]
    permissions: list[str]
    active: bool
    is_admin: bool = Field(alias="isAdmin")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    last_login_at: datetime | None = Field(default=None, alias="lastLoginAt")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class TokenResponse(BaseModel):
    access_token: str = Field(alias="accessToken")
    token_type: str = Field(default="bearer", alias="tokenType")
    expires_in: int = Field(alias="expiresIn")
    refresh_expires_at: datetime = Field(alias="refreshExpiresAt")
    user: UserResource

    model_config = ConfigDict(populate_by_name=True)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class OperationStatus(BaseModel):
    detail: str

    model_config = ConfigDict(populate_by_name=True)


def serialize_user(user: User) -> UserResource:
    return UserResource(
        id=user.id,
        email=user.email,
        username=user.username,
        name=user.name,
        roles=user.role_slugs,
        permissions=user.permissions,
        active=user.active,
        is_admin=user.is_admin,
        created_at=user.created_at,
        updated_at=user.updated_at,
        last_login_at=user.last_login_at,
    )


async def _fetch_user_by_email(db: AsyncSession, email: str) -> User | None:
    _ensure_test_schema()
    stmt = (
        select(User)
        .options(selectinload(User.roles).selectinload(Role.permissions))
        .where(func.lower(User.email) == email.lower())
    )
    result = await db.execute(stmt)
    return result.scalars().first()


async def _load_user(db: AsyncSession, user_id: int) -> User:
    _ensure_test_schema()
    stmt = (
        select(User)
        .options(selectinload(User.roles).selectinload(Role.permissions))
        .where(User.id == user_id)
    )
    result = await db.execute(stmt)
    user = result.scalars().first()
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


async def _issue_tokens(
    db: AsyncSession,
    *,
    user: User,
    response: Response,
    request: Request | None,
) -> TokenResponse:
    _ensure_test_schema()
    access_token, access_expires = create_test_access_token(
        subject=user.id,
        roles=user.role_slugs,
        scopes=user.permissions,
    )
    refresh_token, refresh_expires = create_test_refresh_token()

    session_record = AuthSession(
        user_id=user.id,
        refresh_token_hash=hash_refresh_token(refresh_token),
        user_agent=(request.headers.get("user-agent") if request else None),
        ip_address=(request.client.host if request and request.client else None),
        expires_at=refresh_expires,
    )
    db.add(session_record)
    await db.commit()

    refreshed_user = await _load_user(db, user.id)

    ttl_seconds = int(settings.auth.refresh_token_ttl_seconds)
    response.set_cookie(
        key="refreshToken",
        value=refresh_token,
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=ttl_seconds,
        expires=refresh_expires,
        path="/",
    )

    return TokenResponse(
        access_token=access_token,
        expires_in=int(settings.auth.access_token_ttl_seconds),
        refresh_expires_at=refresh_expires,
        user=serialize_user(refreshed_user),
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_session),
) -> TokenResponse:
    if not settings.auth.allow_test_tokens:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Local token issuance is disabled")
    email = str(payload.email).strip().lower()
    user = await _fetch_user_by_email(db, email)
    if user is None or not verify_password(user.password_hash, payload.password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user.active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Account is suspended")

    user.last_login_at = datetime.now(timezone.utc)
    await db.flush()

    return await _issue_tokens(db, user=user, response=response, request=request)


@router.post("/refresh", response_model=TokenResponse)
async def refresh_tokens(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_session),
) -> TokenResponse:
    if not settings.auth.allow_test_tokens:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Local token issuance is disabled")
    refresh_token = request.cookies.get("refreshToken")
    if not refresh_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Refresh token missing")

    _ensure_test_schema()
    token_hash = hash_refresh_token(refresh_token)
    stmt = (
        select(AuthSession)
        .where(AuthSession.refresh_token_hash == token_hash)
    )
    result = await db.execute(stmt)
    session_record = result.scalars().first()
    if session_record is None or session_record.revoked_at is not None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    expires_at = session_record.expires_at
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at is not None and expires_at <= datetime.now(timezone.utc):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Refresh token expired")

    user = await _load_user(db, session_record.user_id)
    if not user.active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Account is suspended")

    session_record.revoked_at = datetime.now(timezone.utc)
    await db.flush()

    return await _issue_tokens(db, user=user, response=response, request=request)


@router.post("/logout", response_model=OperationStatus)
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_session),
) -> OperationStatus:
    if not settings.auth.allow_test_tokens:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Local token issuance is disabled")
    refresh_token = request.cookies.get("refreshToken")
    if refresh_token:
        _ensure_test_schema()
        token_hash = hash_refresh_token(refresh_token)
        stmt = select(AuthSession).where(AuthSession.refresh_token_hash == token_hash)
        result = await db.execute(stmt)
        session_record = result.scalars().first()
        if session_record is not None:
            session_record.revoked_at = datetime.now(timezone.utc)
            await db.commit()

    response.delete_cookie(
        key="refreshToken",
        path="/",
        httponly=True,
        secure=True,
        samesite="strict",
    )
    return OperationStatus(detail="Logged out")


@router.get("/me", response_model=UserResource)
async def get_me(current_user: User = Security(get_current_user)) -> UserResource:
    return serialize_user(current_user)
