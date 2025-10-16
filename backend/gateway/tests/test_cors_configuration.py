"""Tests for CORS configuration in development environment."""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_dev_cors_allows_local_spa_origin(app):
    """Ensure the dev CORS settings expose expected headers for the SPA."""

    origin = "http://localhost:4200"

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.options(
            "/api/system/health",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )

    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == origin
    assert response.headers.get("access-control-allow-credentials") == "true"

    allow_methods = response.headers.get("access-control-allow-methods")
    assert allow_methods is not None
    allowed = {method.strip() for method in allow_methods.split(",")}
    assert allowed == {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}

    assert response.headers.get("access-control-allow-headers") == "authorization"
