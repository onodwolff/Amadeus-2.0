"""OpenID Connect discovery endpoint exposed for the SPA."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status

from ..config import settings
from ..security import get_local_jwk

router = APIRouter()

_DEFAULT_SCOPES_SUPPORTED: tuple[str, ...] = (
    "openid",
    "profile",
    "email",
    "offline_access",
)

_DEFAULT_RESPONSE_TYPES_SUPPORTED: tuple[str, ...] = ("code",)


def _normalise_url(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    return cleaned.rstrip("/") or cleaned


@router.get("/realms/{realm}/.well-known/openid-configuration")
async def openid_configuration(realm: str) -> dict[str, Any]:
    """Return OpenID Connect discovery metadata for the requested realm."""

    configured_issuer = _normalise_url(getattr(settings.auth, "idp_issuer", None))
    public_base = _normalise_url(settings.auth.public_base_url)
    issuer = configured_issuer or f"{public_base}/realms/{realm}"

    configured_authorization = _normalise_url(
        getattr(settings.auth, "idp_authorization_url", None)
    )
    authorization_endpoint = configured_authorization or f"{issuer}/protocol/openid-connect/auth"

    configured_token = _normalise_url(getattr(settings.auth, "idp_token_url", None))
    token_endpoint = configured_token or f"{issuer}/protocol/openid-connect/token"

    configured_jwks = _normalise_url(getattr(settings.auth, "idp_jwks_url", None))
    jwks_uri = configured_jwks or f"{issuer}/protocol/openid-connect/certs"

    return {
        "issuer": issuer,
        "authorization_endpoint": authorization_endpoint,
        "token_endpoint": token_endpoint,
        "jwks_uri": jwks_uri,
        "scopes_supported": list(_DEFAULT_SCOPES_SUPPORTED),
        "response_types_supported": list(_DEFAULT_RESPONSE_TYPES_SUPPORTED),
    }


@router.get("/realms/{realm}/protocol/openid-connect/certs")
async def openid_jwks(realm: str) -> dict[str, Any]:
    """Expose a JWKS document when using locally signed development tokens."""

    configured_jwks = _normalise_url(getattr(settings.auth, "idp_jwks_url", None))
    if configured_jwks or not settings.auth.allow_test_tokens:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="JWKS not configured")

    return {"keys": [get_local_jwk()]}


__all__ = ["router"]

