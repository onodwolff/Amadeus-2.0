from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from httpx import ASGITransport, AsyncClient

from backend.gateway.app.routes import system as system_routes


@pytest.fixture(autouse=True)
def override_nautilus_service(monkeypatch: pytest.MonkeyPatch):
    health_payload = {
        "status": "ok",
        "env": "test",
        "adapters": {"connected": 2, "total": 3},
    }

    core_payload = {
        "nautilus_version": "1.2.3",
        "available": True,
        "adapters": {
            "connected": 2,
            "total": 3,
            "items": [
                {
                    "name": "primary",
                    "identifier": "binance",
                    "state": "connected",
                }
            ],
        },
    }

    stub = SimpleNamespace(
        health_status=Mock(return_value=health_payload),
        core_info=Mock(return_value=core_payload),
    )

    monkeypatch.setattr(system_routes, "svc", stub)
    return stub


@pytest.mark.asyncio
async def test_health_status_returns_payload(app, override_nautilus_service):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/system/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "env": "test",
        "adapters": {"connected": 2, "total": 3},
    }
    override_nautilus_service.health_status.assert_called_once_with()


@pytest.mark.asyncio
async def test_core_info_returns_payload(app, override_nautilus_service):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/system/core/info")

    assert response.status_code == 200
    assert response.json() == {
        "nautilus_version": "1.2.3",
        "available": True,
        "adapters": {
            "connected": 2,
            "total": 3,
            "items": [
                {
                    "name": "primary",
                    "identifier": "binance",
                    "state": "connected",
                }
            ],
        },
    }
    override_nautilus_service.core_info.assert_called_once_with()

