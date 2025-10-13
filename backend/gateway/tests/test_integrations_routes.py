from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


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


@pytest_asyncio.fixture
async def integrations_viewer_headers(db_session):
    user = await create_user(
        db_session,
        email=f"integrations-viewer-{uuid4()}@example.com",
        username=f"integrationsviewer-{uuid4().hex[:8]}",
        password="password",
        roles=[db_models.UserRole.VIEWER.value],
    )
    token, _ = create_test_access_token(subject=user.id, roles=[db_models.UserRole.VIEWER.value], scopes=["viewer"])
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def integrations_admin_headers(db_session):
    user = await create_user(
        db_session,
        email=f"integrations-admin-{uuid4()}@example.com",
        username=f"integrationsadmin-{uuid4().hex[:8]}",
        password="password",
        roles=[db_models.UserRole.ADMIN.value],
    )
    token, _ = create_test_access_token(subject=user.id, roles=[db_models.UserRole.ADMIN.value], scopes=["admin"])
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_integrations_require_viewer_scope(app, integrations_admin_headers):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/integrations/exchanges", headers=integrations_admin_headers)

    assert response.status_code == 403
    assert response.json()["detail"] == "Insufficient role"


@pytest.mark.asyncio
async def test_list_available_exchanges(app, integrations_viewer_headers):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/integrations/exchanges", headers=integrations_viewer_headers)
    assert response.status_code == 200
    payload = response.json()
    assert "exchanges" in payload
    assert isinstance(payload["exchanges"], list)
