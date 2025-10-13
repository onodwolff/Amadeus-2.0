"""Routes for managing user API keys and secrets."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, Security, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..crypto import decrypt, encrypt, mask_key
from ..dependencies import get_current_user, get_session

try:  # pragma: no cover - prefer local backend imports during tests
    from backend.gateway.db.models import ApiKey, User, UserRole  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - production installs
    from gateway.db.models import ApiKey, User, UserRole  # type: ignore


router = APIRouter(prefix="/keys", tags=["api-keys"])


class EncryptedSecret(BaseModel):
    algorithm: str = Field(min_length=1)
    ciphertext: str = Field(min_length=1)
    iv: str = Field(min_length=1)
    salt: str = Field(min_length=1)
    iterations: int = Field(ge=1, default=100_000)
    kdf: str = Field(min_length=1)
    hash: str = Field(min_length=1)

    model_config = ConfigDict(populate_by_name=True)


class ApiKeyResource(BaseModel):
    key_id: str
    venue: str
    label: str | None = None
    scopes: list[str] = Field(default_factory=list)
    api_key_masked: str
    created_at: datetime
    last_used_at: datetime | None = None
    passphrase_hint: str | None = None

    model_config = ConfigDict(from_attributes=True)


class ApiKeysResponse(BaseModel):
    keys: list[ApiKeyResource] = Field(default_factory=list)

    model_config = ConfigDict(populate_by_name=True)


class KeyCreateRequest(BaseModel):
    key_id: str = Field(alias="keyId", min_length=1)
    venue: str = Field(min_length=1)
    api_key: str = Field(alias="apiKey", min_length=1)
    scopes: list[str] = Field(default_factory=list)
    secret: EncryptedSecret
    passphrase_hash: str = Field(alias="passphraseHash", min_length=1)
    label: str | None = None
    passphrase_hint: str | None = Field(default=None, alias="passphraseHint")

    model_config = ConfigDict(populate_by_name=True)


class KeyUpdateRequest(BaseModel):
    venue: str = Field(min_length=1)
    scopes: list[str] = Field(default_factory=list)
    passphrase_hash: str = Field(alias="passphraseHash", min_length=1)
    label: str | None = None
    api_key: str | None = Field(default=None, alias="apiKey")
    secret: EncryptedSecret | None = None
    passphrase_hint: str | None = Field(default=None, alias="passphraseHint")

    model_config = ConfigDict(populate_by_name=True)


class KeyDeleteRequest(BaseModel):
    passphrase_hash: str = Field(alias="passphraseHash", min_length=1)

    model_config = ConfigDict(populate_by_name=True)


def _normalise_label(label: str | None) -> str | None:
    if label is None:
        return None
    cleaned = label.strip()
    return cleaned or None


def _normalise_scopes(scopes: list[str]) -> list[str]:
    seen: dict[str, None] = {}
    result: list[str] = []
    for scope in scopes:
        cleaned = scope.strip()
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen[key] = None
        result.append(cleaned)
    return result


def _decode_secret(secret_enc: bytes) -> dict[str, Any] | None:
    if not secret_enc:
        return None
    try:
        plaintext = decrypt(secret_enc, key=settings.security.encryption_key_bytes)
    except Exception:
        return None
    try:
        payload = json.loads(plaintext.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _encode_secret(payload: dict[str, Any]) -> bytes:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return encrypt(data, key=settings.security.encryption_key_bytes)


def _serialize(record: ApiKey) -> ApiKeyResource:
    secret_payload = _decode_secret(record.secret_enc) or {}
    return ApiKeyResource(
        key_id=record.key_id,
        venue=record.venue,
        label=record.label,
        scopes=list(record.scopes or []),
        api_key_masked=record.api_key_masked,
        created_at=record.created_at,
        last_used_at=record.last_used_at,
        passphrase_hint=secret_payload.get("passphrase_hint"),
    )


async def _get_owned_key(db: AsyncSession, key_id: str, user_id: int) -> ApiKey:
    stmt = select(ApiKey).where(ApiKey.key_id == key_id, ApiKey.user_id == user_id)
    result = await db.execute(stmt)
    record = result.scalars().first()
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="API key not found")
    return record


def _verify_passphrase(secret_payload: dict[str, Any], provided_hash: str) -> None:
    if not provided_hash:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Invalid passphrase")
    stored_hash = secret_payload.get("passphrase_hash")
    if not isinstance(stored_hash, str) or stored_hash.lower() != provided_hash.lower():
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Invalid passphrase")


@router.get("", response_model=ApiKeysResponse)
async def list_keys(
    current_user: User = Security(
        get_current_user,
        scopes=[UserRole.ADMIN.value, UserRole.MANAGER.value, UserRole.MEMBER.value],
    ),
    db: AsyncSession = Depends(get_session),
) -> ApiKeysResponse:
    stmt = (
        select(ApiKey)
        .where(ApiKey.user_id == current_user.id)
        .order_by(ApiKey.created_at.desc())
    )
    result = await db.execute(stmt)
    records = result.scalars().all()
    return ApiKeysResponse(keys=[_serialize(record) for record in records])


@router.post("", response_model=ApiKeyResource, status_code=status.HTTP_201_CREATED)
async def create_key(
    payload: KeyCreateRequest,
    current_user: User = Security(
        get_current_user,
        scopes=[UserRole.ADMIN.value, UserRole.MANAGER.value, UserRole.MEMBER.value],
    ),
    db: AsyncSession = Depends(get_session),
) -> ApiKeyResource:
    key_id = payload.key_id.strip()
    if not key_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Key identifier cannot be empty")

    venue = payload.venue.strip()
    if not venue:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Venue cannot be empty")

    api_key = payload.api_key.strip()
    if not api_key:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="API key cannot be empty")

    stmt = select(ApiKey).where(ApiKey.key_id == key_id)
    existing = await db.execute(stmt)
    if existing.scalars().first() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Key identifier already exists")

    secret_payload: dict[str, Any] = {
        "api_key": api_key,
        "api_secret": payload.secret.model_dump(by_alias=True),
        "passphrase_hash": payload.passphrase_hash.strip(),
    }
    if payload.passphrase_hint is not None:
        secret_payload["passphrase_hint"] = payload.passphrase_hint

    record = ApiKey(
        user_id=current_user.id,
        key_id=key_id,
        venue=venue,
        label=_normalise_label(payload.label),
        api_key_masked=mask_key(api_key),
        secret_enc=_encode_secret(secret_payload),
        scopes=_normalise_scopes(payload.scopes),
    )

    db.add(record)
    await db.commit()
    await db.refresh(record)
    return _serialize(record)


@router.put("/{key_id}", response_model=ApiKeyResource)
async def update_key(
    key_id: str,
    payload: KeyUpdateRequest,
    current_user: User = Security(
        get_current_user,
        scopes=[UserRole.ADMIN.value, UserRole.MANAGER.value, UserRole.MEMBER.value],
    ),
    db: AsyncSession = Depends(get_session),
) -> ApiKeyResource:
    record = await _get_owned_key(db, key_id, current_user.id)
    secret_payload = _decode_secret(record.secret_enc)
    if secret_payload is None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Stored secret is invalid")

    _verify_passphrase(secret_payload, payload.passphrase_hash.strip())

    venue = payload.venue.strip()
    if not venue:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Venue cannot be empty")

    if payload.api_key is not None:
        updated_api_key = payload.api_key.strip()
        if not updated_api_key:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="API key cannot be empty")
        secret_payload["api_key"] = updated_api_key
        record.api_key_masked = mask_key(updated_api_key)

    if payload.secret is not None:
        secret_payload["api_secret"] = payload.secret.model_dump(by_alias=True)

    if payload.passphrase_hint is not None:
        secret_payload["passphrase_hint"] = payload.passphrase_hint

    record.venue = venue
    record.label = _normalise_label(payload.label)
    record.scopes = _normalise_scopes(payload.scopes)
    record.secret_enc = _encode_secret(secret_payload)

    await db.commit()
    await db.refresh(record)
    return _serialize(record)


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_key(
    key_id: str,
    payload: KeyDeleteRequest,
    current_user: User = Security(
        get_current_user,
        scopes=[UserRole.ADMIN.value, UserRole.MANAGER.value, UserRole.MEMBER.value],
    ),
    db: AsyncSession = Depends(get_session),
) -> Response:
    record = await _get_owned_key(db, key_id, current_user.id)
    secret_payload = _decode_secret(record.secret_enc)
    if secret_payload is None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Stored secret is invalid")

    _verify_passphrase(secret_payload, payload.passphrase_hash.strip())

    await db.delete(record)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
