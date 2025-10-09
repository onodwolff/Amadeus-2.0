"""FastAPI routes for managing encrypted API keys."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any, AsyncIterator, Dict, Iterable, List, Optional, Sequence

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.config import settings
from gateway.db.base import create_session
from gateway.db.models import ApiKey, User

from ..crypto import decrypt, encrypt, mask_key
from ..nautilus_service import svc
from .auth import get_current_user

LOGGER = logging.getLogger("gateway.api_keys")
router = APIRouter(prefix="/keys", tags=["api-keys"])


async def _anonymous_user() -> Optional[User]:
    return None


if settings.auth.enabled:
    _CURRENT_USER_DEP = Depends(get_current_user)
else:
    _CURRENT_USER_DEP = Depends(_anonymous_user)


async def get_session() -> AsyncIterator[AsyncSession]:
    session = create_session()
    try:
        yield session
    finally:
        await session.close()


_SCOPE_PATTERN = re.compile(r"^[a-z0-9:_-]{1,64}$")


class EncryptedKeySecret(BaseModel):
    algorithm: str = Field(..., pattern=r"^[A-Z0-9-]+$")
    ciphertext: str = Field(..., min_length=1)
    iv: str = Field(..., min_length=1)
    salt: str = Field(..., min_length=1)
    iterations: int = Field(..., gt=0)
    kdf: str = Field(..., pattern=r"^[A-Z0-9-]+$")
    hash: str = Field(..., pattern=r"^[A-Z0-9-]+$")

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class _KeyBase(BaseModel):
    label: Optional[str] = Field(default=None, max_length=120)
    venue: str
    scopes: List[str]

    @field_validator("label")
    @classmethod
    def _normalise_label(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None

    @field_validator("venue")
    @classmethod
    def _validate_venue(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Venue is required")
        return value.strip().upper()

    @field_validator("scopes", mode="before")
    @classmethod
    def _ensure_scope_list(cls, value: Iterable[Any]) -> Iterable[Any]:
        if value is None:
            return []
        if isinstance(value, (str, bytes)):
            return [value]
        return value

    @field_validator("scopes")
    @classmethod
    def _validate_scopes(cls, value: Iterable[Any]) -> List[str]:
        scopes: List[str] = []
        for scope in value:
            if not isinstance(scope, str):
                raise ValueError("Scopes must be strings")
            normalized = scope.strip().lower()
            if not normalized:
                continue
            if not _SCOPE_PATTERN.match(normalized):
                raise ValueError("Scope values must match [a-z0-9:_-]{1,64}")
            if normalized not in scopes:
                scopes.append(normalized)
        if not scopes:
            raise ValueError("At least one scope must be provided")
        return scopes

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class KeyCreateRequest(_KeyBase):
    key_id: str = Field(..., alias="keyId", min_length=1, max_length=128)
    api_key: str = Field(..., alias="apiKey", min_length=1, max_length=255)
    secret: EncryptedKeySecret
    passphrase_hash: str = Field(..., alias="passphraseHash", min_length=6, max_length=256)
    passphrase_hint: Optional[str] = Field(default=None, alias="passphraseHint", max_length=255)

    @field_validator("key_id", "api_key", "passphrase_hash")
    @classmethod
    def _strip(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Value cannot be empty")
        return cleaned

    @field_validator("passphrase_hint")
    @classmethod
    def _strip_hint(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None


class KeyUpdateRequest(_KeyBase):
    api_key: Optional[str] = Field(default=None, alias="apiKey", min_length=1, max_length=255)
    secret: Optional[EncryptedKeySecret] = None
    passphrase_hash: str = Field(..., alias="passphraseHash", min_length=6, max_length=256)
    passphrase_hint: Optional[str] = Field(default=None, alias="passphraseHint", max_length=255)

    @field_validator("api_key")
    @classmethod
    def _strip_optional(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None

    @field_validator("passphrase_hash")
    @classmethod
    def _strip_hash(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Passphrase hash cannot be empty")
        return cleaned

    @field_validator("passphrase_hint")
    @classmethod
    def _strip_hint(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None


class KeyDeleteRequest(BaseModel):
    passphrase_hash: str = Field(..., alias="passphraseHash", min_length=6, max_length=256)

    @field_validator("passphrase_hash")
    @classmethod
    def _strip_hash(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Passphrase hash cannot be empty")
        return cleaned

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class ApiKeyResource(BaseModel):
    key_id: str
    venue: str
    label: Optional[str] = None
    scopes: List[str]
    api_key_masked: str
    created_at: datetime
    last_used_at: Optional[datetime] = None
    fingerprint: Optional[str] = None
    passphrase_hint: Optional[str] = None

    model_config = ConfigDict(populate_by_name=True)


class ApiKeysResponse(BaseModel):
    keys: List[ApiKeyResource]


def _known_venues() -> set[str]:
    try:
        response = svc.list_available_exchanges()
    except Exception:  # pragma: no cover - defensive
        return set()
    exchanges = response.get("exchanges") or []
    codes = {str(entry.get("code", "")).upper() for entry in exchanges if entry.get("code")}
    return {code for code in codes if code}


async def _resolve_default_user_id(session: AsyncSession) -> int:
    result = await session.execute(select(User.id).order_by(User.id.asc()))
    user_id = result.scalars().first()
    if user_id is None:
        raise HTTPException(status_code=400, detail="No users available to associate API keys")
    return user_id


async def _resolve_request_user_id(
    session: AsyncSession,
    current_user: Optional[User],
) -> int:
    user_obj = current_user if isinstance(current_user, User) else None

    if settings.auth.enabled:
        if user_obj is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
        return int(user_obj.id)

    if user_obj is not None:
        return int(user_obj.id)

    return await _resolve_default_user_id(session)


def _encode_secret_payload(payload: Dict[str, Any]) -> bytes:
    serialized = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return encrypt(serialized, key=settings.encryption_key)


def _decode_secret_payload(secret_enc: bytes) -> Dict[str, Any]:
    try:
        plaintext = decrypt(secret_enc, key=settings.encryption_key)
    except Exception as exc:  # pragma: no cover - defensive
        LOGGER.exception("secret_decrypt_failed")
        raise HTTPException(status_code=500, detail="Stored credential payload could not be decrypted") from exc
    try:
        data = json.loads(plaintext.decode("utf-8"))
    except ValueError as exc:  # pragma: no cover - defensive
        LOGGER.exception("secret_decode_failed")
        raise HTTPException(status_code=500, detail="Stored credential payload is malformed") from exc
    if not isinstance(data, dict):  # pragma: no cover - defensive
        raise HTTPException(status_code=500, detail="Stored credential payload is invalid")
    return data


def _build_resource(record: ApiKey, secret_payload: Optional[Dict[str, Any]] = None) -> ApiKeyResource:
    payload = secret_payload or {}
    api_key = payload.get("api_key")
    fingerprint = None
    if isinstance(api_key, str) and api_key:
        fingerprint = api_key[-4:].rjust(4, "•")
    hint = payload.get("passphrase_hint") if isinstance(payload.get("passphrase_hint"), str) else None
    return ApiKeyResource(
        key_id=record.key_id,
        venue=record.venue,
        label=record.label,
        scopes=list(record.scopes or []),
        api_key_masked=record.api_key_masked,
        created_at=record.created_at,
        last_used_at=record.last_used_at,
        fingerprint=fingerprint,
        passphrase_hint=hint,
    )


async def _get_key(
    session: AsyncSession, key_id: str, *, user_id: Optional[int] = None
) -> ApiKey:
    stmt: Select[ApiKey] = select(ApiKey).where(ApiKey.key_id == key_id)
    if user_id is not None:
        stmt = stmt.where(ApiKey.user_id == user_id)
    result = await session.execute(stmt)
    record = result.scalars().first()
    if record is None:
        raise HTTPException(status_code=404, detail="API key not found")
    return record


def _validate_known_venue(venue: str) -> None:
    known = _known_venues()
    if known and venue not in known:
        raise HTTPException(status_code=400, detail=f"Unknown venue '{venue}'")


@router.get("", response_model=ApiKeysResponse)
async def list_api_keys(
    session: AsyncSession = Depends(get_session),
    current_user: Optional[User] = _CURRENT_USER_DEP,
) -> ApiKeysResponse:
    user_id = await _resolve_request_user_id(session, current_user)

    stmt: Select[ApiKey] = (
        select(ApiKey)
        .where(ApiKey.user_id == user_id)
        .order_by(ApiKey.created_at.asc())
    )
    result = await session.execute(stmt)
    records: Sequence[ApiKey] = result.scalars().all()
    items: List[ApiKeyResource] = []
    for record in records:
        secret_payload: Optional[Dict[str, Any]] = None
        try:
            secret_payload = _decode_secret_payload(record.secret_enc)
        except HTTPException:
            # Continue returning metadata even if secret is corrupted.
            secret_payload = None
        items.append(_build_resource(record, secret_payload))
    return ApiKeysResponse(keys=items)


@router.post("", response_model=ApiKeyResource, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    payload: KeyCreateRequest,
    session: AsyncSession = Depends(get_session),
    current_user: Optional[User] = _CURRENT_USER_DEP,
) -> ApiKeyResource:
    _validate_known_venue(payload.venue)

    secret_payload = {
        "api_key": payload.api_key,
        "api_secret": payload.secret.model_dump(),
        "passphrase_hash": payload.passphrase_hash,
        "passphrase_hint": payload.passphrase_hint,
    }
    secret_enc = _encode_secret_payload(secret_payload)

    user_id = await _resolve_request_user_id(session, current_user)

    record = ApiKey(
        user_id=user_id,
        venue=payload.venue,
        label=payload.label,
        key_id=payload.key_id,
        api_key_masked=mask_key(payload.api_key),
        secret_enc=secret_enc,
        scopes=payload.scopes,
    )

    session.add(record)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="API key identifier already exists") from exc

    await session.refresh(record)
    return _build_resource(record, secret_payload)


@router.put("/{key_id}", response_model=ApiKeyResource)
async def update_api_key(
    key_id: str,
    payload: KeyUpdateRequest,
    session: AsyncSession = Depends(get_session),
    current_user: Optional[User] = _CURRENT_USER_DEP,
) -> ApiKeyResource:
    user_id = await _resolve_request_user_id(session, current_user)

    record = await _get_key(session, key_id, user_id=user_id)
    secret_payload = _decode_secret_payload(record.secret_enc)

    stored_hash = secret_payload.get("passphrase_hash")
    if not isinstance(stored_hash, str) or stored_hash != payload.passphrase_hash:
        raise HTTPException(status_code=403, detail="Passphrase verification failed")

    _validate_known_venue(payload.venue)

    record.venue = payload.venue
    record.label = payload.label
    record.scopes = payload.scopes

    if payload.api_key:
        record.api_key_masked = mask_key(payload.api_key)
        secret_payload["api_key"] = payload.api_key
    if payload.secret is not None:
        secret_payload["api_secret"] = payload.secret.model_dump()
    secret_payload["passphrase_hash"] = payload.passphrase_hash
    secret_payload["passphrase_hint"] = payload.passphrase_hint

    record.secret_enc = _encode_secret_payload(secret_payload)

    await session.commit()
    await session.refresh(record)
    return _build_resource(record, secret_payload)


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_api_key(
    key_id: str,
    payload: KeyDeleteRequest,
    session: AsyncSession = Depends(get_session),
    current_user: Optional[User] = _CURRENT_USER_DEP,
) -> Response:
    user_id = await _resolve_request_user_id(session, current_user)

    record = await _get_key(session, key_id, user_id=user_id)
    secret_payload = _decode_secret_payload(record.secret_enc)
    stored_hash = secret_payload.get("passphrase_hash")
    if not isinstance(stored_hash, str) or stored_hash != payload.passphrase_hash:
        raise HTTPException(status_code=403, detail="Passphrase verification failed")

    await session.delete(record)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
