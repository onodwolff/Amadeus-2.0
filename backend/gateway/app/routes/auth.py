"""Authentication and sensitive account management endpoints."""
from __future__ import annotations

import hashlib
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import jwt
import pyotp
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    FieldValidationInfo,
    field_validator,
)
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.app.config import settings
from gateway.app.dependencies import get_session
from gateway.app.security import hash_password, verify_password
from gateway.db.models import AuthSession, EmailChangeRequest, User


_LOGIN_WINDOW_SECONDS = 60
_MAX_LOGIN_ATTEMPTS = 5
_login_attempts: Dict[str, List[float]] = {}
_bearer_scheme = HTTPBearer(auto_error=False)
_PASSWORD_COMPLEXITY_PATTERN = re.compile(r"(?=.*[A-Za-z])(?=.*\d)")

router = APIRouter(tags=["auth"])


class UserResource(BaseModel):
    """Serialized representation of the authenticated user."""

    id: str
    email: EmailStr
    active: bool
    is_admin: bool = Field(alias="isAdmin")
    email_verified: bool = Field(alias="emailVerified")
    mfa_enabled: bool = Field(alias="mfaEnabled")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    last_login_at: datetime | None = Field(default=None, alias="lastLoginAt")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class TokenResponse(BaseModel):
    """Access and refresh tokens returned to the client."""

    access_token: str = Field(alias="accessToken")
    refresh_token: str = Field(alias="refreshToken")
    token_type: str = Field(default="bearer", alias="tokenType")
    expires_in: int = Field(alias="expiresIn")
    user: UserResource

    model_config = ConfigDict(populate_by_name=True)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)
    totp_code: Optional[str] = Field(default=None, alias="totpCode", min_length=6, max_length=8)
    remember_me: bool = Field(default=False, alias="rememberMe")

    model_config = ConfigDict(populate_by_name=True)


class LogoutRequest(BaseModel):
    refresh_token: str = Field(alias="refreshToken")

    model_config = ConfigDict(populate_by_name=True)


class PasswordChangePayload(BaseModel):
    current_password: str = Field(..., alias="currentPassword", min_length=1)
    new_password: str = Field(..., alias="newPassword", min_length=8)

    model_config = ConfigDict(populate_by_name=True)


class EmailChangePayload(BaseModel):
    new_email: EmailStr = Field(..., alias="newEmail")
    password: str = Field(..., min_length=1)

    model_config = ConfigDict(populate_by_name=True)


class EmailChangeResponse(BaseModel):
    verification_token: str = Field(alias="verificationToken")

    model_config = ConfigDict(populate_by_name=True)


class EmailChangeConfirmPayload(BaseModel):
    token: str


class MfaSetupResponse(BaseModel):
    secret: str
    otpauth_url: str = Field(alias="otpauthUrl")

    model_config = ConfigDict(populate_by_name=True)


class MfaEnablePayload(BaseModel):
    code: str = Field(min_length=6, max_length=8)


class MfaDisablePayload(BaseModel):
    code: Optional[str] = Field(default=None, min_length=6, max_length=8)
    password: Optional[str] = Field(default=None, min_length=1)

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("password", mode="before")
    @classmethod
    def _check_input(
        cls, value: Optional[str], info: FieldValidationInfo
    ) -> Optional[str]:
        code = info.data.get("code")
        if (value is None or (isinstance(value, str) and not value.strip())) and not code:
            raise ValueError("Either password or code must be provided")
        return value


class SessionResource(BaseModel):
    id: int
    created_at: datetime = Field(alias="createdAt")
    expires_at: datetime = Field(alias="expiresAt")
    revoked_at: datetime | None = Field(default=None, alias="revokedAt")
    ip_address: str | None = Field(default=None, alias="ipAddress")
    user_agent: str | None = Field(default=None, alias="userAgent")
    active: bool

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class SessionsResponse(BaseModel):
    sessions: List[SessionResource]

    model_config = ConfigDict(populate_by_name=True)


class OperationStatus(BaseModel):
    detail: str

    model_config = ConfigDict(populate_by_name=True)


class SessionRevokePayload(BaseModel):
    password: str = Field(min_length=1)

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("password")
    @classmethod
    def _normalize_password(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("Password is required")
        return trimmed


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _enforce_login_rate_limit(key: str) -> None:
    now = time.monotonic()
    window = _login_attempts.get(key, [])
    window = [ts for ts in window if now - ts < _LOGIN_WINDOW_SECONDS]
    if len(window) >= _MAX_LOGIN_ATTEMPTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Please try again later.",
        )
    _login_attempts[key] = window


def _register_failed_login(key: str) -> None:
    now = time.monotonic()
    window = _login_attempts.setdefault(key, [])
    window.append(now)
    _login_attempts[key] = [ts for ts in window if now - ts < _LOGIN_WINDOW_SECONDS]


def _clear_login_attempts(key: str) -> None:
    _login_attempts.pop(key, None)


def _hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _serialize_user(user: User) -> UserResource:
    return UserResource(
        id=str(user.id),
        email=user.email,
        active=bool(getattr(user, "active", True)),
        is_admin=user.is_admin,
        email_verified=user.email_verified,
        mfa_enabled=user.mfa_enabled,
        created_at=user.created_at,
        updated_at=user.updated_at,
        last_login_at=user.last_login_at,
    )


def _create_access_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "is_admin": user.is_admin,
        "email_verified": user.email_verified,
        "iat": int(now.timestamp()),
        "exp": int(
            (now + timedelta(seconds=settings.auth.access_token_ttl_seconds)).timestamp()
        ),
    }
    return jwt.encode(payload, settings.auth.jwt_secret, algorithm="HS256")


async def _store_refresh_session(
    *,
    db: AsyncSession,
    user: User,
    refresh_token: str,
    remember_me: bool,
    request: Request,
) -> AuthSession:
    ttl = settings.auth.refresh_token_ttl_seconds
    if remember_me:
        ttl = int(ttl * 1.5)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl)
    session_record = AuthSession(
        user_id=user.id,
        refresh_token_hash=_hash_refresh_token(refresh_token),
        user_agent=(request.headers.get("user-agent") or "")[:255] or None,
        ip_address=(request.client.host if request.client else None),
        expires_at=expires_at,
    )
    db.add(session_record)
    await db.flush()
    return session_record


async def _get_user_by_email(db: AsyncSession, email: str) -> Optional[User]:
    stmt = select(User).where(func.lower(User.email) == email.lower())
    result = await db.execute(stmt)
    return result.scalars().first()


async def _ensure_email_available(
    db: AsyncSession, *, email: str, exclude_user_id: Optional[int] = None
) -> None:
    stmt = select(User.id).where(func.lower(User.email) == email.lower())
    if exclude_user_id is not None:
        stmt = stmt.where(User.id != exclude_user_id)
    result = await db.execute(stmt)
    if result.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email is already associated with another account.",
        )


async def _decode_token(credentials: HTTPAuthorizationCredentials | None) -> dict[str, object]:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    token = credentials.credentials
    try:
        return jwt.decode(token, settings.auth.jwt_secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError as exc:  # pragma: no cover - runtime check
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Token expired") from exc
    except jwt.InvalidTokenError as exc:  # pragma: no cover - runtime check
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: AsyncSession = Depends(get_session),
) -> User:
    payload = await _decode_token(credentials)
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    try:
        user_id_int = int(user_id)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc

    stmt = select(User).where(User.id == user_id_int)
    result = await db.execute(stmt)
    user = result.scalars().first()
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="User no longer exists")
    if not getattr(user, "active", True):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="Account is suspended"
        )
    return user


@router.post("/auth/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> TokenResponse:
    email = _normalize_email(str(payload.email))
    rate_key = f"{request.client.host if request.client else 'unknown'}:{email}"
    _enforce_login_rate_limit(rate_key)

    user = await _get_user_by_email(db, email)
    if user is None or not verify_password(user.password_hash, payload.password):
        _register_failed_login(rate_key)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    if not getattr(user, "active", True):
        _register_failed_login(rate_key)
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Account is suspended")

    if user.mfa_enabled:
        if not payload.totp_code:
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                detail="MFA code required",
            )
        if not user.mfa_secret:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="MFA misconfigured")
        totp = pyotp.TOTP(user.mfa_secret)
        if not totp.verify(payload.totp_code, valid_window=1):
            _register_failed_login(rate_key)
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid MFA code")

    _clear_login_attempts(rate_key)

    access_token = _create_access_token(user)
    refresh_token = secrets.token_urlsafe(48)
    await _store_refresh_session(
        db=db,
        user=user,
        refresh_token=refresh_token,
        remember_me=payload.remember_me,
        request=request,
    )
    user.last_login_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(user)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.auth.access_token_ttl_seconds,
        user=_serialize_user(user),
    )


@router.post("/auth/logout", response_model=OperationStatus)
async def logout(
    payload: LogoutRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> OperationStatus:
    token_hash = _hash_refresh_token(payload.refresh_token)
    stmt = (
        select(AuthSession)
        .where(AuthSession.refresh_token_hash == token_hash)
        .where(AuthSession.user_id == current_user.id)
    )
    result = await db.execute(stmt)
    session_record = result.scalars().first()
    if session_record:
        session_record.revoked_at = datetime.now(timezone.utc)
        await db.commit()
    return OperationStatus(detail="Logged out")


@router.get("/me", response_model=UserResource)
async def get_me(current_user: User = Depends(get_current_user)) -> UserResource:
    return _serialize_user(current_user)


@router.patch("/me/password", response_model=OperationStatus)
async def change_password(
    payload: PasswordChangePayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> OperationStatus:
    if not verify_password(current_user.password_hash, payload.current_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")

    current_user.password_hash = hash_password(payload.new_password)
    current_user.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return OperationStatus(detail="Password updated")


@router.patch("/me/email", response_model=EmailChangeResponse)
async def request_email_change(
    payload: EmailChangePayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> EmailChangeResponse:
    if not verify_password(current_user.password_hash, payload.password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")

    new_email = _normalize_email(str(payload.new_email))
    if new_email == current_user.email.lower():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="New email matches existing email")

    await _ensure_email_available(db, email=new_email, exclude_user_id=current_user.id)

    token = secrets.token_urlsafe(32)
    token_hash = _hash_refresh_token(token)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=24)

    await db.execute(delete(EmailChangeRequest).where(EmailChangeRequest.user_id == current_user.id))
    db.add(
        EmailChangeRequest(
            user_id=current_user.id,
            new_email=new_email,
            token_hash=token_hash,
            expires_at=expires_at,
        )
    )
    await db.commit()
    return EmailChangeResponse(verification_token=token)


@router.post("/me/email/confirm", response_model=UserResource)
async def confirm_email_change(
    payload: EmailChangeConfirmPayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> UserResource:
    token_hash = _hash_refresh_token(payload.token)
    stmt = (
        select(EmailChangeRequest)
        .where(EmailChangeRequest.user_id == current_user.id)
        .where(EmailChangeRequest.token_hash == token_hash)
    )
    result = await db.execute(stmt)
    request_record = result.scalars().first()
    if request_record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Email change token is invalid")
    if request_record.confirmed_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Email change token already used")
    if request_record.expires_at <= datetime.now(timezone.utc):
        raise HTTPException(status.HTTP_410_GONE, detail="Email change token expired")

    await _ensure_email_available(db, email=request_record.new_email, exclude_user_id=current_user.id)

    current_user.email = request_record.new_email
    current_user.email_verified = True
    current_user.updated_at = datetime.now(timezone.utc)
    request_record.confirmed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(current_user)
    return _serialize_user(current_user)


@router.post("/me/mfa/setup", response_model=MfaSetupResponse)
async def setup_mfa(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> MfaSetupResponse:
    secret = pyotp.random_base32()
    current_user.mfa_secret = secret
    current_user.mfa_enabled = False
    await db.commit()

    totp = pyotp.TOTP(secret)
    otpauth_url = totp.provisioning_uri(name=current_user.email, issuer_name="Amadeus Gateway")
    return MfaSetupResponse(secret=secret, otpauth_url=otpauth_url)


@router.post("/me/mfa/enable", response_model=OperationStatus)
async def enable_mfa(
    payload: MfaEnablePayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> OperationStatus:
    if not current_user.mfa_secret:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="MFA has not been initialised")

    totp = pyotp.TOTP(current_user.mfa_secret)
    if not totp.verify(payload.code, valid_window=1):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid MFA code")

    current_user.mfa_enabled = True
    current_user.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return OperationStatus(detail="MFA enabled")


@router.delete("/me/mfa", response_model=OperationStatus)
async def disable_mfa(
    payload: MfaDisablePayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> OperationStatus:
    if current_user.mfa_secret is None:
        return OperationStatus(detail="MFA already disabled")

    if payload.password:
        if not verify_password(current_user.password_hash, payload.password):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Password verification failed")
    elif payload.code:
        totp = pyotp.TOTP(current_user.mfa_secret)
        if not totp.verify(payload.code, valid_window=1):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid MFA code")

    current_user.mfa_enabled = False
    current_user.mfa_secret = None
    current_user.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return OperationStatus(detail="MFA disabled")


@router.get("/me/sessions", response_model=SessionsResponse)
async def list_sessions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> SessionsResponse:
    stmt = (
        select(AuthSession)
        .where(AuthSession.user_id == current_user.id)
        .order_by(AuthSession.created_at.desc())
    )
    result = await db.execute(stmt)
    sessions = result.scalars().all()
    now = datetime.now(timezone.utc)
    resources = [
        SessionResource(
            id=session_record.id,
            created_at=session_record.created_at,
            expires_at=session_record.expires_at,
            revoked_at=session_record.revoked_at,
            ip_address=session_record.ip_address,
            user_agent=session_record.user_agent,
            active=session_record.revoked_at is None and session_record.expires_at > now,
        )
        for session_record in sessions
    ]
    return SessionsResponse(sessions=resources)


@router.post("/me/sessions/revoke_all", response_model=OperationStatus)
async def revoke_all_sessions(
    payload: SessionRevokePayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> OperationStatus:
    if not verify_password(current_user.password_hash, payload.password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Password verification failed")

    now = datetime.now(timezone.utc)
    await db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == current_user.id)
        .where(AuthSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    await db.commit()
    return OperationStatus(detail="All sessions revoked")
