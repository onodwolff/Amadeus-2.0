from __future__ import annotations

import base64
import hashlib

import jwt
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.gateway.app.security import create_test_access_token
from backend.gateway.config import settings


@pytest_asyncio.fixture(autouse=True)
def configure_oidc(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        settings.auth,
        "idp_issuer",
        "https://idp.example.com/realms/amadeus",
    )
    monkeypatch.setattr(
        settings.auth,
        "idp_authorization_url",
        "https://idp.example.com/realms/amadeus/protocol/openid-connect/auth",
    )
    monkeypatch.setattr(
        settings.auth,
        "idp_token_url",
        "https://idp.example.com/realms/amadeus/protocol/openid-connect/token",
    )
    monkeypatch.setattr(
        settings.auth,
        "idp_jwks_url",
        "https://idp.example.com/realms/amadeus/protocol/openid-connect/certs",
    )
    monkeypatch.setattr(settings.auth, "dev_oidc_fallback", None)


@pytest.mark.asyncio
async def test_oidc_well_known_configuration(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/realms/amadeus/.well-known/openid-configuration")

    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "issuer": "https://idp.example.com/realms/amadeus",
        "authorization_endpoint": "https://idp.example.com/realms/amadeus/protocol/openid-connect/auth",
        "token_endpoint": "https://idp.example.com/realms/amadeus/protocol/openid-connect/token",
        "jwks_uri": "https://idp.example.com/realms/amadeus/protocol/openid-connect/certs",
        "scopes_supported": ["openid", "profile", "email", "offline_access"],
        "response_types_supported": ["code"],
    }


@pytest.mark.asyncio
async def test_oidc_well_known_configuration_returns_not_found_when_fallback_disabled(
    app, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings.auth, "idp_authorization_url", None)
    monkeypatch.setattr(settings.auth, "idp_token_url", None)
    monkeypatch.setattr(settings.auth, "dev_oidc_fallback", False)
    monkeypatch.setattr(settings, "env", "prod")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/realms/amadeus/.well-known/openid-configuration")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_oidc_jwks_document_exposes_local_secret(app, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings.auth, "idp_jwks_url", None)
    monkeypatch.setattr(settings.auth, "dev_oidc_fallback", True)
    monkeypatch.setattr(settings, "env", "prod")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/realms/amadeus/protocol/openid-connect/certs")

    assert response.status_code == 200
    payload = response.json()
    secret = settings.auth.jwt_secret.encode("utf-8")
    expected_k = base64.urlsafe_b64encode(secret).rstrip(b"=").decode("ascii")
    expected_kid = hashlib.sha256(secret).hexdigest()[:32]
    assert payload == {
        "keys": [
            {
                "kty": "oct",
                "use": "sig",
                "alg": "HS256",
                "kid": expected_kid,
                "k": expected_k,
            }
        ]
    }


@pytest.mark.asyncio
async def test_oidc_jwks_document_disabled_when_external_idp_configured(
    app, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings.auth, "idp_jwks_url", "https://idp.example.com/jwks")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/realms/amadeus/protocol/openid-connect/certs")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_oidc_authorization_redirects_to_configured_idp(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get(
            "/realms/amadeus/protocol/openid-connect/auth",
            params={"client_id": "amadeus-ui", "scope": "openid"},
        )

    assert response.status_code == 307
    assert response.headers["location"] == (
        "https://idp.example.com/realms/amadeus/protocol/openid-connect/auth"
        "?client_id=amadeus-ui&scope=openid"
    )


@pytest.mark.asyncio
async def test_oidc_authorization_returns_not_found_when_unconfigured(
    app, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings.auth, "idp_authorization_url", None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/realms/amadeus/protocol/openid-connect/auth")

    assert response.status_code == 404


def test_create_test_access_token_includes_local_kid(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings.auth, "jwt_secret", "super-secret-key")
    token, _ = create_test_access_token(subject="user")
    header = jwt.get_unverified_header(token)
    expected_kid = hashlib.sha256("super-secret-key".encode("utf-8")).hexdigest()[:32]
    assert header["kid"] == expected_kid


@pytest.mark.asyncio
async def test_oidc_well_known_configuration_dev_fallback(app, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings.auth, "idp_authorization_url", None)
    monkeypatch.setattr(settings.auth, "idp_token_url", None)
    monkeypatch.setattr(settings.auth, "idp_jwks_url", None)
    monkeypatch.setattr(settings.auth, "dev_oidc_fallback", None)
    monkeypatch.setattr(settings, "env", "dev")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/realms/amadeus/.well-known/openid-configuration")

    assert response.status_code == 200
    payload = response.json()
    public_base = settings.auth.public_base_url.rstrip("/")
    expected_issuer = f"{public_base}/realms/amadeus"
    assert payload == {
        "issuer": expected_issuer,
        "authorization_endpoint": f"{expected_issuer}/protocol/openid-connect/auth",
        "token_endpoint": f"{expected_issuer}/protocol/openid-connect/token",
        "jwks_uri": f"{expected_issuer}/protocol/openid-connect/certs",
        "scopes_supported": ["openid", "profile", "email", "offline_access"],
        "response_types_supported": ["code"],
    }


@pytest.mark.asyncio
async def test_oidc_well_known_configuration_forced_fallback_in_prod(
    app, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings.auth, "idp_authorization_url", None)
    monkeypatch.setattr(settings.auth, "idp_token_url", None)
    monkeypatch.setattr(settings.auth, "idp_jwks_url", None)
    monkeypatch.setattr(settings.auth, "dev_oidc_fallback", True)
    monkeypatch.setattr(settings, "env", "prod")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/realms/amadeus/.well-known/openid-configuration")

    assert response.status_code == 200
    payload = response.json()
    public_base = settings.auth.public_base_url.rstrip("/")
    expected_issuer = f"{public_base}/realms/amadeus"
    assert payload == {
        "issuer": expected_issuer,
        "authorization_endpoint": f"{expected_issuer}/protocol/openid-connect/auth",
        "token_endpoint": f"{expected_issuer}/protocol/openid-connect/token",
        "jwks_uri": f"{expected_issuer}/protocol/openid-connect/certs",
        "scopes_supported": ["openid", "profile", "email", "offline_access"],
        "response_types_supported": ["code"],
    }


@pytest.mark.asyncio
async def test_oidc_jwks_dev_fallback_ignores_test_token_flag(
    app, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings.auth, "idp_jwks_url", None)
    monkeypatch.setattr(settings.auth, "allow_test_tokens", False)
    monkeypatch.setattr(settings.auth, "dev_oidc_fallback", None)
    monkeypatch.setattr(settings, "env", "dev")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/realms/amadeus/protocol/openid-connect/certs")

    assert response.status_code == 200
    payload = response.json()
    secret = settings.auth.jwt_secret.encode("utf-8")
    expected_k = base64.urlsafe_b64encode(secret).rstrip(b"=").decode("ascii")
    expected_kid = hashlib.sha256(secret).hexdigest()[:32]
    assert payload == {
        "keys": [
            {
                "kty": "oct",
                "use": "sig",
                "alg": "HS256",
                "kid": expected_kid,
                "k": expected_k,
            }
        ]
    }

