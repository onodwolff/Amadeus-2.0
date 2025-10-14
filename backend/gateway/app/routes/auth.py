"""Authentication API endpoints."""
from __future__ import annotations

import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping
import pyotp
from fastapi import APIRouter, Depends, HTTPException, Request, Response, Security, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import delete, func, select, update
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
UserMFABackupCode = db_models.UserMFABackupCode
UserTokenPurpose = db_models.UserTokenPurpose

if db_models.__name__.startswith("backend."):
    sys.modules.setdefault("gateway.db.models", db_models)
    sys.modules.setdefault("gateway.db.base", db_base)
    db_models.Base.metadata.schema = None
    for table in db_models.Base.metadata.tables.values():
        table.schema = None


def _ensure_test_schema() -> None:
    if not db_models.__name__.startswith("backend."):
        return
    if (
        not User.__table__.schema
        and not Role.__table__.schema
        and not AuthSession.__table__.schema
        and not UserMFABackupCode.__table__.schema
    ):
        return
    for table in (
        User.__table__,
        Role.__table__,
        AuthSession.__table__,
        UserMFABackupCode.__table__,
    ):
        table.schema = None

from ..audit import record_audit_event
from ..config import settings
from ..dependencies import get_current_user, get_email_dispatcher, get_session
from ..email import EmailDispatcher
from ..security import (
    create_test_access_token,
    create_test_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from ..token_service import TokenService

router = APIRouter(prefix="/auth", tags=["auth"])

logger = logging.getLogger(__name__)


class UserResource(BaseModel):
    id: int
    email: EmailStr
    username: str
    name: str | None = None
    roles: list[str]
    permissions: list[str]
    active: bool
    is_admin: bool = Field(alias="isAdmin")
    email_verified: bool = Field(alias="emailVerified")
    mfa_enabled: bool = Field(alias="mfaEnabled")
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


class ForgotPasswordRequest(BaseModel):
    email: EmailStr

    model_config = ConfigDict(populate_by_name=True)


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=16)
    new_password: str = Field(min_length=8, max_length=255, alias="newPassword")

    model_config = ConfigDict(populate_by_name=True)


class MfaSetupResponse(BaseModel):
    secret: str
    otpauth_url: str = Field(alias="otpauthUrl")

    model_config = ConfigDict(populate_by_name=True)


class MfaEnableRequest(BaseModel):
    code: str = Field(min_length=6, max_length=32)

    model_config = ConfigDict(populate_by_name=True)


class MfaEnableResponse(BaseModel):
    detail: str
    backup_codes: list[str] = Field(alias="backupCodes")

    model_config = ConfigDict(populate_by_name=True)


class MfaDisableRequest(BaseModel):
    password: str | None = None
    code: str | None = None

    model_config = ConfigDict(populate_by_name=True)


class MfaBackupCodesRequest(BaseModel):
    password: str | None = None
    code: str | None = None

    model_config = ConfigDict(populate_by_name=True)


class BackupCodesResponse(BaseModel):
    backup_codes: list[str] = Field(alias="backupCodes")
    detail: str | None = None

    model_config = ConfigDict(populate_by_name=True)


class MfaChallengeResponse(BaseModel):
    challenge_token: str = Field(alias="challengeToken")
    detail: str = Field(default="MFA verification required")
    methods: list[str] = Field(default_factory=lambda: ["totp", "backup_code"])
    ttl_seconds: int = Field(alias="ttlSeconds")

    model_config = ConfigDict(populate_by_name=True)


class MfaChallengeRequest(BaseModel):
    challenge_token: str = Field(min_length=16, alias="challengeToken")
    code: str = Field(min_length=6, max_length=32)
    remember_device: bool = Field(default=False, alias="rememberDevice")

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
        email_verified=user.email_verified,
        mfa_enabled=user.mfa_enabled,
        created_at=user.created_at,
        updated_at=user.updated_at,
        last_login_at=user.last_login_at,
    )


async def _record_auth_event(
    db: AsyncSession,
    request: Request,
    *,
    action: str,
    result: str,
    actor_user_id: int | None = None,
    target_user_id: int | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> None:
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    await record_audit_event(
        db,
        action=action,
        result=result,
        actor_user_id=actor_user_id,
        target_user_id=target_user_id,
        ip_address=ip_address,
        user_agent=user_agent,
        metadata=dict(metadata or {}),
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


def _build_totp(secret: str) -> pyotp.TOTP:
    return pyotp.TOTP(secret)


def _generate_totp_secret() -> str:
    return pyotp.random_base32()


def _build_otpauth_url(user: User, secret: str) -> str:
    label = user.email or user.username
    issuer = "Amadeus"
    return _build_totp(secret).provisioning_uri(name=label, issuer_name=issuer)


def _clean_mfa_code(code: str) -> str:
    return "".join(ch for ch in code.strip() if ch.isalnum())


def _verify_totp_code(user: User, code: str) -> bool:
    if not user.mfa_secret:
        return False
    cleaned = _clean_mfa_code(code)
    if len(cleaned) < 6:
        return False
    totp = _build_totp(user.mfa_secret)
    return bool(totp.verify(cleaned, valid_window=1))


_BACKUP_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _generate_backup_code() -> str:
    return "".join(secrets.choice(_BACKUP_CODE_ALPHABET) for _ in range(10))


async def _rotate_backup_codes(db: AsyncSession, user: User, *, count: int = 10) -> list[str]:
    _ensure_test_schema()
    await db.execute(
        delete(UserMFABackupCode).where(UserMFABackupCode.user_id == user.id)
    )
    codes = [_generate_backup_code() for _ in range(count)]
    for code in codes:
        db.add(
            UserMFABackupCode(
                user_id=user.id,
                code_hash=hash_password(code),
            )
        )
    await db.flush()
    return codes


async def _consume_backup_code(db: AsyncSession, user: User, code: str) -> bool:
    _ensure_test_schema()
    stmt = (
        select(UserMFABackupCode)
        .where(UserMFABackupCode.user_id == user.id)
        .where(UserMFABackupCode.used_at.is_(None))
    )
    result = await db.execute(stmt)
    cleaned = _clean_mfa_code(code)
    now = datetime.now(timezone.utc)
    for record in result.scalars():
        if verify_password(record.code_hash, cleaned):
            record.used_at = now
            await db.flush()
            return True
    return False


async def clear_backup_codes(db: AsyncSession, user: User) -> None:
    _ensure_test_schema()
    await db.execute(
        delete(UserMFABackupCode).where(UserMFABackupCode.user_id == user.id)
    )


async def _validate_mfa_factor(db: AsyncSession, user: User, code: str) -> str | None:
    cleaned = _clean_mfa_code(code)
    if not cleaned:
        return None
    if _verify_totp_code(user, cleaned):
        return "totp"
    if await _consume_backup_code(db, user, cleaned):
        return "backup_code"
    return None


async def _issue_tokens(
    db: AsyncSession,
    *,
    user: User,
    response: Response,
    request: Request | None,
    parent_session: AuthSession | None = None,
    mfa_verified_at: datetime | None = None,
    mfa_method: str | None = None,
    remember_device: bool = False,
) -> TokenResponse:
    _ensure_test_schema()
    access_token, access_expires = create_test_access_token(
        subject=user.id,
        roles=user.role_slugs,
        scopes=user.permissions,
    )
    refresh_token, refresh_expires = create_test_refresh_token()

    if parent_session is not None:
        family_id = parent_session.family_id
        parent_session_id = parent_session.id
        if mfa_verified_at is None:
            mfa_verified_at = parent_session.mfa_verified_at
        if mfa_method is None:
            mfa_method = parent_session.mfa_method
        remember_device = parent_session.mfa_remember_device
    else:
        family_id = str(uuid.uuid4())
        parent_session_id = None
        if mfa_verified_at is None:
            mfa_verified_at = datetime.now(timezone.utc)
        if mfa_method is None:
            mfa_method = "password"

    session_record = AuthSession(
        user_id=user.id,
        refresh_token_hash=hash_refresh_token(refresh_token),
        family_id=family_id,
        parent_session_id=parent_session_id,
        user_agent=(request.headers.get("user-agent") if request else None),
        ip_address=(request.client.host if request and request.client else None),
        expires_at=refresh_expires,
        mfa_verified_at=mfa_verified_at,
        mfa_method=mfa_method,
        mfa_remember_device=remember_device,
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


async def _revoke_session_family(db: AsyncSession, family_id: str) -> int:
    now = datetime.now(timezone.utc)
    result = await db.execute(
        update(AuthSession)
        .where(AuthSession.family_id == family_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    return result.rowcount or 0


async def revoke_user_sessions(db: AsyncSession, user: User) -> int:
    _ensure_test_schema()
    now = datetime.now(timezone.utc)
    result = await db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    return result.rowcount or 0


@router.post("/forgot-password", response_model=OperationStatus)
async def forgot_password(
    payload: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_session),
    email_dispatcher: EmailDispatcher = Depends(get_email_dispatcher),
) -> OperationStatus:
    email = str(payload.email).strip().lower()
    user = await _fetch_user_by_email(db, email)

    detail = "If the account exists, password reset instructions have been sent."
    if user is None or not user.active:
        return OperationStatus(detail=detail)

    token_service = TokenService(db)
    record, token = await token_service.issue(
        user=user,
        purpose=UserTokenPurpose.PASSWORD_RESET,
        ttl_seconds=settings.auth.password_reset_token_ttl_seconds,
    )
    await db.commit()
    await db.refresh(record)

    await email_dispatcher.send_password_reset_email(
        email=user.email,
        token=token,
        expires_at=record.expires_at,
    )
    return OperationStatus(detail=detail)


@router.post("/reset-password", response_model=OperationStatus)
async def reset_password(
    payload: ResetPasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> OperationStatus:
    token_service = TokenService(db)
    record = await token_service.consume(
        token=payload.token,
        purpose=UserTokenPurpose.PASSWORD_RESET,
    )
    if record is None:
        await _record_auth_event(
            db,
            request,
            action="auth.reset_password",
            result="failure",
            metadata={"reason": "invalid_or_expired_token"},
        )
        await db.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid or expired token")

    user = record.user
    if user is None:
        user = await _load_user(db, record.user_id)

    user.password_hash = hash_password(payload.new_password)
    await db.flush()
    await _record_auth_event(
        db,
        request,
        action="auth.reset_password",
        result="success",
        actor_user_id=user.id,
        target_user_id=user.id,
    )
    await db.commit()
    return OperationStatus(detail="Password updated")


@router.get("/verify-email", response_model=OperationStatus)
async def verify_email(
    token: str,
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> OperationStatus:
    token_service = TokenService(db)
    record = await token_service.consume(
        token=token,
        purpose=UserTokenPurpose.EMAIL_VERIFICATION,
    )
    if record is None:
        await _record_auth_event(
            db,
            request,
            action="auth.verify_email",
            result="failure",
            metadata={"reason": "invalid_or_expired_token"},
        )
        await db.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid or expired token")

    user = record.user
    if user is None:
        user = await _load_user(db, record.user_id)

    if not user.email_verified:
        user.email_verified = True
    await db.flush()
    await _record_auth_event(
        db,
        request,
        action="auth.verify_email",
        result="success",
        actor_user_id=user.id,
        target_user_id=user.id,
    )
    await db.commit()
    return OperationStatus(detail="Email verified")


@router.post(
    "/login",
    response_model=TokenResponse,
    responses={status.HTTP_202_ACCEPTED: {"model": MfaChallengeResponse}},
)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_session),
) -> TokenResponse:
    if not settings.auth.allow_test_tokens:
        await _record_auth_event(
            db,
            request,
            action="auth.login",
            result="failure",
            metadata={"reason": "token_issuance_disabled"},
        )
        await db.commit()
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Local token issuance is disabled")
    email = str(payload.email).strip().lower()
    user = await _fetch_user_by_email(db, email)
    if user is None or not verify_password(user.password_hash, payload.password):
        await _record_auth_event(
            db,
            request,
            action="auth.login",
            result="failure",
            metadata={"reason": "invalid_credentials", "email": email},
        )
        await db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user.active:
        await _record_auth_event(
            db,
            request,
            action="auth.login",
            result="failure",
            actor_user_id=user.id,
            target_user_id=user.id,
            metadata={"reason": "account_suspended"},
        )
        await db.commit()
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Account is suspended")

    if user.mfa_enabled:
        token_service = TokenService(db)
        record, challenge_token = await token_service.issue(
            user=user,
            purpose=UserTokenPurpose.MFA_CHALLENGE,
            ttl_seconds=settings.auth.mfa_challenge_token_ttl_seconds,
        )
        await _record_auth_event(
            db,
            request,
            action="auth.login",
            result="success",
            actor_user_id=user.id,
            target_user_id=user.id,
            metadata={"mfa_required": True},
        )
        await db.commit()
        await db.refresh(record)
        challenge = MfaChallengeResponse(
            challenge_token=challenge_token,
            ttl_seconds=int(settings.auth.mfa_challenge_token_ttl_seconds),
        )
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content=challenge.model_dump(by_alias=True),
        )

    user.last_login_at = datetime.now(timezone.utc)
    await db.flush()
    await _record_auth_event(
        db,
        request,
        action="auth.login",
        result="success",
        actor_user_id=user.id,
        target_user_id=user.id,
        metadata={"mfa_required": False, "mfa_method": "password"},
    )

    return await _issue_tokens(
        db,
        user=user,
        response=response,
        request=request,
        mfa_method="password",
    )


@router.post("/login/mfa", response_model=TokenResponse)
async def complete_login_mfa(
    payload: MfaChallengeRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_session),
) -> TokenResponse:
    if not settings.auth.allow_test_tokens:
        await _record_auth_event(
            db,
            request,
            action="auth.login_mfa",
            result="failure",
            metadata={"reason": "token_issuance_disabled"},
        )
        await db.commit()
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Local token issuance is disabled",
        )

    token_service = TokenService(db)
    record = await token_service.consume(
        token=payload.challenge_token,
        purpose=UserTokenPurpose.MFA_CHALLENGE,
    )
    if record is None:
        await _record_auth_event(
            db,
            request,
            action="auth.login_mfa",
            result="failure",
            metadata={"reason": "invalid_or_expired_challenge"},
        )
        await db.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid or expired challenge")

    user = record.user or await _load_user(db, record.user_id)
    if not user.active:
        await _record_auth_event(
            db,
            request,
            action="auth.login_mfa",
            result="failure",
            actor_user_id=user.id,
            target_user_id=user.id,
            metadata={"reason": "account_suspended"},
        )
        await db.commit()
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Account is suspended")

    method = await _validate_mfa_factor(db, user, payload.code)
    if method is None:
        await _record_auth_event(
            db,
            request,
            action="auth.login_mfa",
            result="failure",
            actor_user_id=user.id,
            target_user_id=user.id,
            metadata={"reason": "invalid_verification_code"},
        )
        await db.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid verification code")

    now = datetime.now(timezone.utc)
    user.last_login_at = now
    await db.flush()
    await _record_auth_event(
        db,
        request,
        action="auth.login_mfa",
        result="success",
        actor_user_id=user.id,
        target_user_id=user.id,
        metadata={"mfa_method": method, "remember_device": payload.remember_device},
    )

    return await _issue_tokens(
        db,
        user=user,
        response=response,
        request=request,
        mfa_verified_at=now,
        mfa_method=method,
        remember_device=payload.remember_device,
    )


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
    if session_record is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    if session_record.revoked_at is not None:
        revoked_count = await _revoke_session_family(db, session_record.family_id)
        await db.commit()
        logger.warning(
            "Refresh token reuse detected; revoked %s sessions in family %s",
            revoked_count,
            session_record.family_id,
        )
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    expires_at = session_record.expires_at
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at is not None and expires_at <= datetime.now(timezone.utc):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Refresh token expired")

    user = await _load_user(db, session_record.user_id)
    if not user.active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Account is suspended")
    if user.mfa_enabled and session_record.mfa_verified_at is None:
        await _revoke_session_family(db, session_record.family_id)
        await db.commit()
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="MFA verification required")

    session_record.revoked_at = datetime.now(timezone.utc)

    return await _issue_tokens(
        db,
        user=user,
        response=response,
        request=request,
        parent_session=session_record,
    )


@router.post("/me/mfa/setup", response_model=MfaSetupResponse)
async def setup_mfa(
    current_user: User = Security(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> MfaSetupResponse:
    if current_user.mfa_enabled:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Two-factor authentication is already enabled")

    secret = _generate_totp_secret()
    current_user.mfa_secret = secret
    await db.flush()
    await db.commit()
    return MfaSetupResponse(secret=secret, otpauth_url=_build_otpauth_url(current_user, secret))


@router.post("/me/mfa/enable", response_model=MfaEnableResponse)
async def enable_mfa(
    payload: MfaEnableRequest,
    request: Request,
    current_user: User = Security(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> MfaEnableResponse:
    secret = current_user.mfa_secret
    if secret is None:
        secret = _generate_totp_secret()
        current_user.mfa_secret = secret

    if not _verify_totp_code(current_user, payload.code):
        await _record_auth_event(
            db,
            request,
            action="auth.mfa_enable",
            result="failure",
            actor_user_id=current_user.id,
            target_user_id=current_user.id,
            metadata={"reason": "invalid_verification_code"},
        )
        await db.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid verification code")

    current_user.mfa_enabled = True
    backup_codes = await _rotate_backup_codes(db, current_user)
    await db.flush()
    await _record_auth_event(
        db,
        request,
        action="auth.mfa_enable",
        result="success",
        actor_user_id=current_user.id,
        target_user_id=current_user.id,
        metadata={"backup_codes": len(backup_codes)},
    )
    await db.commit()
    return MfaEnableResponse(
        detail="Two-factor authentication enabled",
        backup_codes=backup_codes,
    )


@router.delete("/me/mfa", response_model=OperationStatus)
async def disable_mfa(
    payload: MfaDisableRequest,
    request: Request,
    current_user: User = Security(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> OperationStatus:
    if not current_user.mfa_enabled:
        await _record_auth_event(
            db,
            request,
            action="auth.mfa_disable",
            result="failure",
            actor_user_id=current_user.id,
            target_user_id=current_user.id,
            metadata={"reason": "already_disabled"},
        )
        await db.commit()
        return OperationStatus(detail="Two-factor authentication is already disabled")

    verified = False
    if payload.code:
        method = await _validate_mfa_factor(db, current_user, payload.code)
        verified = method is not None
    if not verified and payload.password:
        verified = verify_password(current_user.password_hash, payload.password)

    if not verified:
        await _record_auth_event(
            db,
            request,
            action="auth.mfa_disable",
            result="failure",
            actor_user_id=current_user.id,
            target_user_id=current_user.id,
            metadata={"reason": "verification_required"},
        )
        await db.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Verification required to disable MFA")

    current_user.mfa_enabled = False
    current_user.mfa_secret = None
    await clear_backup_codes(db, current_user)
    revoked = await revoke_user_sessions(db, current_user)
    await db.flush()
    await _record_auth_event(
        db,
        request,
        action="auth.mfa_disable",
        result="success",
        actor_user_id=current_user.id,
        target_user_id=current_user.id,
        metadata={"revoked_sessions": revoked},
    )
    await db.commit()
    return OperationStatus(detail="Two-factor authentication disabled")


@router.post("/me/mfa/backup-codes", response_model=BackupCodesResponse)
async def regenerate_backup_codes(
    payload: MfaBackupCodesRequest,
    current_user: User = Security(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> BackupCodesResponse:
    if not current_user.mfa_enabled:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Two-factor authentication is not enabled")

    verified = False
    if payload.code:
        method = await _validate_mfa_factor(db, current_user, payload.code)
        verified = method is not None
    if not verified and payload.password:
        verified = verify_password(current_user.password_hash, payload.password)

    if not verified:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Verification required to regenerate backup codes")

    backup_codes = await _rotate_backup_codes(db, current_user)
    await db.flush()
    await db.commit()
    return BackupCodesResponse(
        detail="Backup codes regenerated",
        backup_codes=backup_codes,
    )


@router.post("/logout", response_model=OperationStatus)
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_session),
) -> OperationStatus:
    if not settings.auth.allow_test_tokens:
        await _record_auth_event(
            db,
            request,
            action="auth.logout",
            result="failure",
            metadata={"reason": "token_issuance_disabled"},
        )
        await db.commit()
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Local token issuance is disabled")
    refresh_token = request.cookies.get("refreshToken")
    if refresh_token:
        _ensure_test_schema()
        token_hash = hash_refresh_token(refresh_token)
        stmt = select(AuthSession).where(AuthSession.refresh_token_hash == token_hash)
        result = await db.execute(stmt)
        session_record = result.scalars().first()
        if session_record is not None:
            revoked_count = await _revoke_session_family(db, session_record.family_id)
            await _record_auth_event(
                db,
                request,
                action="auth.logout",
                result="success",
                actor_user_id=session_record.user_id,
                target_user_id=session_record.user_id,
                metadata={"revoked_sessions": revoked_count},
            )
            await db.commit()
            logger.info(
                "Logout revoked %s sessions in family %s",
                revoked_count,
                session_record.family_id,
            )
        else:
            await _record_auth_event(
                db,
                request,
                action="auth.logout",
                result="failure",
                metadata={"reason": "session_not_found"},
            )
            await db.commit()
    else:
        await _record_auth_event(
            db,
            request,
            action="auth.logout",
            result="failure",
            metadata={"reason": "refresh_token_missing"},
        )
        await db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Refresh token missing")

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
