from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

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
        "idp_token_url",
        "https://idp.example.com/realms/amadeus/protocol/openid-connect/token",
    )
    monkeypatch.setattr(
        settings.auth,
        "idp_jwks_url",
        "https://idp.example.com/realms/amadeus/protocol/openid-connect/certs",
    )


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

