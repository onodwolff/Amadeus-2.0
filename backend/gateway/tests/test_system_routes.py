from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import Mock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.gateway.app.routes import system as system_routes
from backend.gateway.app.security import create_test_access_token
from backend.gateway.db import models as db_models
from backend.gateway.db.base import Base as GatewayBase

try:  # pragma: no cover - optional import when package layout allows
    from gateway.db import models as alt_db_models
    from gateway.db.base import Base as AltGatewayBase
except ModuleNotFoundError:  # pragma: no cover - running from backend package only
    alt_db_models = None
    AltGatewayBase = None

from .utils import create_user

# Ensure tables do not carry PostgreSQL schemas when using SQLite
GatewayBase.metadata.schema = None
for table in GatewayBase.metadata.tables.values():
    table.schema = None

db_models.Base.metadata.schema = None
for table in db_models.Base.metadata.tables.values():
    table.schema = None

if AltGatewayBase is not None:  # pragma: no cover - exercised in integration tests
    AltGatewayBase.metadata.schema = None
    for table in AltGatewayBase.metadata.tables.values():
        table.schema = None

if alt_db_models is not None:  # pragma: no cover - exercised in integration tests
    alt_db_models.Base.metadata.schema = None
    for table in alt_db_models.Base.metadata.tables.values():
        table.schema = None


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


@pytest_asyncio.fixture
async def system_viewer_headers(db_session):
    user = await create_user(
        db_session,
        email=f"system-viewer-{uuid4()}@example.com",
        username=f"systemviewer-{uuid4().hex[:8]}",
        password="password",
        roles=[db_models.UserRole.VIEWER.value],
    )
    token, _ = create_test_access_token(subject=user.id, roles=[db_models.UserRole.VIEWER.value], scopes=["viewer"])
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def system_admin_headers(db_session):
    user = await create_user(
        db_session,
        email=f"system-admin-{uuid4()}@example.com",
        username=f"systemadmin-{uuid4().hex[:8]}",
        password="password",
        roles=[db_models.UserRole.ADMIN.value],
    )
    token, _ = create_test_access_token(subject=user.id, roles=[db_models.UserRole.ADMIN.value], scopes=["admin"])
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_system_routes_reject_without_viewer_scope(app, system_admin_headers):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/system/health", headers=system_admin_headers)

    assert response.status_code == 403
    assert response.json()["detail"] == "Insufficient role"


@pytest.mark.asyncio
async def test_health_status_returns_payload(app, override_nautilus_service, system_viewer_headers):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/system/health", headers=system_viewer_headers)

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "env": "test",
        "adapters": {"connected": 2, "total": 3},
    }
    override_nautilus_service.health_status.assert_called_once_with()


@pytest.mark.asyncio
async def test_core_info_returns_payload(app, override_nautilus_service, system_viewer_headers):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/system/core/info", headers=system_viewer_headers)

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

