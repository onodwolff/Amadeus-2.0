"""Security helpers and token utilities for the gateway API."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Final, Iterable, Sequence

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHash, VerifyMismatchError
from fastapi import HTTPException, status
from jwt import InvalidTokenError

from .config import settings
from .jwks import JWKSClient, JWKSFetchError, JWKSKeyNotFoundError

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


@dataclass(frozen=True)
class TokenData:
    """Validated token payload enriched with useful metadata."""

    subject: str
    issuer: str
    audience: tuple[str, ...]
    expires_at: datetime
    roles: tuple[str, ...]
    scopes: tuple[str, ...]
    claims: dict[str, Any]


class TokenValidator:
    """Validate bearer tokens issued by an external identity provider."""

    def __init__(self) -> None:
        self._config = settings.auth
        self._jwks_client: JWKSClient | None = None
        if self._config.uses_identity_provider and self._config.idp_jwks_url:
            self._jwks_client = JWKSClient(
                self._config.idp_jwks_url,
                cache_ttl_seconds=self._config.idp_cache_ttl_seconds,
            )
        self._allowed_algorithms: tuple[str, ...] = tuple(self._config.idp_algorithms or ["RS256"])

    def _extract_header_requirements(self, token: str) -> tuple[str, str]:
        try:
            header = jwt.get_unverified_header(token)
        except InvalidTokenError as exc:
            raise _jwt_error("Invalid token header") from exc

        kid = header.get("kid")
        if not isinstance(kid, str) or not kid:
            raise _jwt_error("Token missing key identifier")

        algorithm = header.get("alg")
        if not isinstance(algorithm, str):
            raise _jwt_error("Token missing signing algorithm")
        algorithm = algorithm.upper()
        if algorithm not in self._allowed_algorithms:
            raise _jwt_error("Unsupported signing algorithm")
        return kid, algorithm

    def _decode_with_jwk(self, token: str, jwk_entry: dict[str, Any], algorithm: str) -> dict[str, Any]:
        try:
            key = jwt.algorithms.get_default_algorithms()[algorithm].from_jwk(json.dumps(jwk_entry))
        except Exception as exc:  # pragma: no cover - defensive
            raise _jwt_error("Failed to construct verification key") from exc

        options = {
            "require": ["sub", "exp"],
            "verify_aud": bool(self._config.idp_audiences),
            "verify_iss": bool(self._config.idp_issuer),
        }

        try:
            payload = jwt.decode(
                token,
                key,
                algorithms=[algorithm],
                audience=list(self._config.idp_audiences) or None,
                issuer=self._config.idp_issuer,
                options=options,
            )
        except jwt.ExpiredSignatureError as exc:
            raise _jwt_error("Token expired") from exc
        except jwt.InvalidAudienceError as exc:
            raise _jwt_error("Invalid audience") from exc
        except jwt.InvalidIssuerError as exc:
            raise _jwt_error("Invalid issuer") from exc
        except InvalidTokenError as exc:
            raise _jwt_error("Invalid token") from exc

        return payload

    def _decode_with_idp(self, token: str) -> dict[str, Any]:
        if self._jwks_client is None:
            raise _jwt_error("Identity provider is not configured")

        kid, algorithm = self._extract_header_requirements(token)

        try:
            jwk_entry = self._jwks_client.get_signing_key(kid)
        except JWKSKeyNotFoundError as exc:
            raise _jwt_error("Unknown signing key") from exc
        except JWKSFetchError as exc:
            raise _jwt_error("Unable to fetch signing keys") from exc

        return self._decode_with_jwk(token, jwk_entry, algorithm)

    async def _decode_with_idp_async(self, token: str) -> dict[str, Any]:
        if self._jwks_client is None:
            raise _jwt_error("Identity provider is not configured")

        kid, algorithm = self._extract_header_requirements(token)

        try:
            jwk_entry = await self._jwks_client.get_signing_key_async(kid)
        except JWKSKeyNotFoundError as exc:
            raise _jwt_error("Unknown signing key") from exc
        except JWKSFetchError as exc:
            raise _jwt_error("Unable to fetch signing keys") from exc

        return self._decode_with_jwk(token, jwk_entry, algorithm)

    def _decode_with_local_secret(self, token: str) -> dict[str, Any]:
        try:
            payload = jwt.decode(
                token,
                self._config.jwt_secret,
                algorithms=["HS256"],
                options={"require": ["sub", "exp"], "verify_aud": False, "verify_iss": False},
            )
        except jwt.ExpiredSignatureError as exc:
            raise _jwt_error("Token expired") from exc
        except InvalidTokenError as exc:
            raise _jwt_error("Invalid token") from exc
        return payload

    @staticmethod
    def _extract_roles(claims: dict[str, Any]) -> tuple[str, ...]:
        roles: list[str] = []
        realm_access = claims.get("realm_access")
        if isinstance(realm_access, dict):
            raw_roles = realm_access.get("roles")
            if isinstance(raw_roles, Iterable) and not isinstance(raw_roles, (str, bytes)):
                for item in raw_roles:
                    if isinstance(item, str):
                        cleaned = item.strip()
                        if cleaned and cleaned not in roles:
                            roles.append(cleaned)
        return tuple(roles)

    @staticmethod
    def _extract_scopes(claims: dict[str, Any]) -> tuple[str, ...]:
        scope_claim = claims.get("scope")
        if isinstance(scope_claim, str):
            scopes = []
            seen: set[str] = set()
            for scope in scope_claim.split():
                cleaned = scope.strip()
                if not cleaned or cleaned in seen:
                    continue
                seen.add(cleaned)
                scopes.append(cleaned)
            return tuple(scopes)
        return ()

    def _normalise_payload(self, payload: dict[str, Any]) -> TokenData:
        subject = payload.get("sub")
        if not isinstance(subject, str) or not subject.strip():
            raise _jwt_error("Token subject is missing")

        issuer = payload.get("iss")
        if not isinstance(issuer, str):
            issuer = ""

        exp_claim = payload.get("exp")
        if isinstance(exp_claim, str) and exp_claim.isdigit():
            exp_claim = int(exp_claim)
        if not isinstance(exp_claim, (int, float)):
            raise _jwt_error("Token expiration is invalid")
        expires_at = datetime.fromtimestamp(int(exp_claim), tz=timezone.utc)

        audience_claim = payload.get("aud")
        audience: tuple[str, ...]
        if isinstance(audience_claim, str):
            audience = (audience_claim,)
        elif isinstance(audience_claim, Iterable):
            cleaned: list[str] = []
            for item in audience_claim:
                if isinstance(item, str):
                    candidate = item.strip()
                    if candidate and candidate not in cleaned:
                        cleaned.append(candidate)
            audience = tuple(cleaned)
        else:
            audience = ()

        roles = self._extract_roles(payload)
        scopes = self._extract_scopes(payload)

        return TokenData(
            subject=subject,
            issuer=issuer,
            audience=audience,
            expires_at=expires_at,
            roles=roles,
            scopes=scopes,
            claims=dict(payload),
        )

    def validate(self, token: str) -> TokenData:
        """Validate ``token`` and return the enriched payload."""

        if self._config.uses_identity_provider:
            payload = self._decode_with_idp(token)
        elif self._config.allow_test_tokens:
            payload = self._decode_with_local_secret(token)
        else:
            raise _jwt_error("Identity provider validation is not configured")
        return self._normalise_payload(payload)

    async def validate_async(self, token: str) -> TokenData:
        """Async variant of :meth:`validate` that avoids blocking the event loop."""

        if self._config.uses_identity_provider:
            payload = await self._decode_with_idp_async(token)
        elif self._config.allow_test_tokens:
            payload = self._decode_with_local_secret(token)
        else:
            raise _jwt_error("Identity provider validation is not configured")
        return self._normalise_payload(payload)


_VALIDATOR: TokenValidator | None = None


def _get_validator() -> TokenValidator:
    global _VALIDATOR
    if _VALIDATOR is None:
        _VALIDATOR = TokenValidator()
    return _VALIDATOR


def validate_bearer_token(token: str) -> TokenData:
    """Validate and decode an incoming bearer token."""

    validator = _get_validator()
    return validator.validate(token)


async def validate_bearer_token_async(token: str) -> TokenData:
    """Async helper mirroring :func:`validate_bearer_token` for non-blocking usage."""

    validator = _get_validator()
    return await validator.validate_async(token)


def get_local_jwk() -> dict[str, str]:
    """Return a JSON Web Key describing the locally signed test tokens."""

    secret = settings.auth.jwt_secret.encode("utf-8")
    kid = hashlib.sha256(secret).hexdigest()[:32]
    key_material = base64.urlsafe_b64encode(secret).rstrip(b"=").decode("ascii")
    return {
        "kty": "oct",
        "use": "sig",
        "alg": "HS256",
        "kid": kid,
        "k": key_material,
    }


def create_test_access_token(
    *,
    subject: int | str,
    expires_in: int | None = None,
    roles: Sequence[str] | None = None,
    scopes: Sequence[str] | None = None,
) -> tuple[str, datetime]:
    """Issue a short lived access token for testing purposes.

    The gateway now expects access tokens to be minted by an external identity
    provider. This helper remains to unblock automated tests and local
    development flows. The resulting JWT is signed with the legacy shared
    secret and should never be used in production.
    """

    now = datetime.now(timezone.utc)
    ttl = expires_in or settings.auth.access_token_ttl_seconds
    exp = now + timedelta(seconds=ttl)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    if roles:
        unique_roles = []
        seen: set[str] = set()
        for role in roles:
            cleaned = role.strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            unique_roles.append(cleaned)
        if unique_roles:
            payload["realm_access"] = {"roles": unique_roles}
    if scopes:
        unique_scopes = []
        seen_scopes: set[str] = set()
        for scope in scopes:
            cleaned_scope = scope.strip()
            if not cleaned_scope or cleaned_scope in seen_scopes:
                continue
            seen_scopes.add(cleaned_scope)
            unique_scopes.append(cleaned_scope)
        if unique_scopes:
            payload["scope"] = " ".join(unique_scopes)

    jwk = get_local_jwk()
    token = jwt.encode(
        payload,
        settings.auth.jwt_secret,
        algorithm="HS256",
        headers={"kid": jwk["kid"]},
    )
    return token, exp


def create_test_refresh_token(*, expires_in: int | None = None) -> tuple[str, datetime]:
    """Generate a refresh token for testing flows."""

    ttl = expires_in or settings.auth.refresh_token_ttl_seconds
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl)
    return secrets.token_urlsafe(48), expires_at


def hash_refresh_token(token: str) -> str:
    """Hash refresh tokens before persistence to the database."""

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


__all__ = [
    "TokenData",
    "TokenValidator",
    "create_test_access_token",
    "create_test_refresh_token",
    "get_local_jwk",
    "hash_password",
    "hash_refresh_token",
    "validate_bearer_token_async",
    "validate_bearer_token",
    "verify_password",
]
