"""Security helpers and token utilities for the gateway API."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Final, Tuple

try:
    import jwt  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - fallback lightweight JWT implementation
    class _ExpiredSignatureError(Exception):
        """Raised when the embedded expiration timestamp is in the past."""

    class _InvalidTokenError(Exception):
        """Raised when a token cannot be decoded or validated."""

    def _b64encode(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("utf-8")

    def _b64decode(data: str) -> bytes:
        padding = "=" * (-len(data) % 4)
        return base64.urlsafe_b64decode(data + padding)

    def _encode(payload: dict[str, Any], secret: str, algorithm: str = "HS256") -> str:
        header = {"alg": algorithm, "typ": "JWT"}
        segments: list[str] = []
        for component in (header, payload):
            raw = json.dumps(component, separators=(",", ":"), sort_keys=True).encode("utf-8")
            segments.append(_b64encode(raw))
        signing_input = ".".join(segments).encode("utf-8")
        signature = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
        segments.append(_b64encode(signature))
        return ".".join(segments)

    def _decode(token: str, secret: str, algorithms: list[str] | None = None) -> dict[str, Any]:
        try:
            header_b64, payload_b64, signature_b64 = token.split(".")
        except ValueError as exc:  # pragma: no cover - invalid format
            raise _InvalidTokenError("Token format invalid") from exc
        signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
        signature = _b64decode(signature_b64)
        expected = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            raise _InvalidTokenError("Signature mismatch")
        payload = json.loads(_b64decode(payload_b64))
        exp = payload.get("exp")
        if exp is not None and int(exp) < int(time.time()):
            raise _ExpiredSignatureError("Token expired")
        return payload

    jwt = SimpleNamespace(  # type: ignore[assignment]
        encode=_encode,
        decode=_decode,
        ExpiredSignatureError=_ExpiredSignatureError,
        InvalidTokenError=_InvalidTokenError,
    )

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHash, VerifyMismatchError
from fastapi import HTTPException, status

from .config import settings

_PASSWORD_HASHER: Final[PasswordHasher] = PasswordHasher()


def hash_password(password: str) -> str:
    """Hash a password using Argon2id."""

    return _PASSWORD_HASHER.hash(password)


def verify_password(stored_hash: str, candidate: str) -> bool:
    """Verify a plaintext password against the stored hash."""

    try:
        return _PASSWORD_HASHER.verify(stored_hash, candidate)
    except VerifyMismatchError:
        return False
    except InvalidHash:
        legacy = hashlib.sha256(candidate.encode("utf-8")).hexdigest()
        return hmac.compare_digest(stored_hash, legacy)


def _jwt_error(detail: str) -> HTTPException:
    """Return a standardised HTTP 401 response for JWT errors."""

    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail=detail)


def create_access_token(*, subject: int, expires_in: int | None = None) -> Tuple[str, datetime]:
    """Create a signed JWT access token for the supplied subject."""

    now = datetime.now(timezone.utc)
    ttl = expires_in or settings.auth.access_token_ttl_seconds
    exp = now + timedelta(seconds=ttl)
    payload = {
        "sub": str(subject),
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    token = jwt.encode(payload, settings.auth.jwt_secret, algorithm="HS256")
    return token, exp


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and validate an incoming JWT access token."""

    try:
        payload = jwt.decode(token, settings.auth.jwt_secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError as exc:  # pragma: no cover - runtime guard
        raise _jwt_error("Token expired") from exc
    except jwt.InvalidTokenError as exc:  # pragma: no cover - runtime guard
        raise _jwt_error("Invalid token") from exc

    token_type = payload.get("type")
    if token_type != "access":
        raise _jwt_error("Invalid token")

    return payload


def create_refresh_token(*, expires_in: int | None = None) -> Tuple[str, datetime]:
    """Generate a refresh token and return it with its expiration timestamp."""

    ttl = expires_in or settings.auth.refresh_token_ttl_seconds
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl)
    return secrets.token_urlsafe(48), expires_at


def hash_refresh_token(token: str) -> str:
    """Hash refresh tokens before persistence to the database."""

    return hashlib.sha256(token.encode("utf-8")).hexdigest()
