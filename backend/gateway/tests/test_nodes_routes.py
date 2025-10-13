from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import Mock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.gateway.app.nautilus_service import NodeHandle
from backend.gateway.app.routes import nodes as nodes_routes
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
    handle_backtest = NodeHandle(id="bt-11111111", mode="backtest", status="running")
    handle_live = NodeHandle(id="lv-22222222", mode="live", status="running")
    handle_sandbox = NodeHandle(id="sb-33333333", mode="sandbox", status="running")

    stub = SimpleNamespace(
        list_nodes=Mock(return_value=[handle_backtest]),
        start_backtest=Mock(return_value=handle_backtest),
        start_live=Mock(return_value=handle_live),
        start_sandbox=Mock(return_value=handle_sandbox),
        stop_node=Mock(return_value=handle_backtest),
        restart_node=Mock(return_value=handle_backtest),
        delete_node=Mock(return_value=None),
        node_detail=Mock(
            return_value={
                "node": {
                    "id": handle_backtest.id,
                    "mode": handle_backtest.mode,
                    "status": handle_backtest.status,
                },
                "config": {"type": "backtest"},
                "lifecycle": [
                    {
                        "timestamp": "2024-01-01T00:00:00Z",
                        "status": "running",
                        "message": "Node launched",
                    }
                ],
            }
        ),
        export_logs=Mock(return_value="log-entry"),
        stream_snapshot=Mock(
            return_value=
            {
                "logs": [
                    {
                        "id": "log-1",
                        "timestamp": "2024-01-01T00:00:00Z",
                        "level": "info",
                        "message": "Started",
                        "source": "system",
                    }
                ],
                "lifecycle": [],
            }
        ),
    )

    monkeypatch.setattr(nodes_routes, "svc", stub)
    return stub


@pytest_asyncio.fixture
async def trader_headers(db_session):
    user = await create_user(
        db_session,
        email=f"trader-{uuid4()}@example.com",
        username=f"trader-{uuid4().hex[:8]}",
        password="password",
        roles=[db_models.UserRole.MEMBER.value],
    )
    token, _ = create_test_access_token(subject=user.id, roles=[db_models.UserRole.MEMBER.value], scopes=["trader"])
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def viewer_headers(db_session):
    user = await create_user(
        db_session,
        email=f"viewer-{uuid4()}@example.com",
        username=f"viewer-{uuid4().hex[:8]}",
        password="password",
        roles=[db_models.UserRole.VIEWER.value],
    )
    token, _ = create_test_access_token(subject=user.id, roles=[db_models.UserRole.VIEWER.value], scopes=["viewer"])
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_list_nodes_rejects_without_trader_scope(app, viewer_headers):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/nodes", headers=viewer_headers)

    assert response.status_code == 403
    assert response.json()["detail"] == "Insufficient role"


@pytest.mark.asyncio
async def test_list_nodes_returns_handles(app, override_nautilus_service, trader_headers):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/nodes", headers=trader_headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["nodes"]
    override_nautilus_service.list_nodes.assert_called_once_with()


@pytest.mark.parametrize(
    "node_type,service_method",
    [
        ("backtest", "start_backtest"),
        ("live", "start_live"),
        ("sandbox", "start_sandbox"),
    ],
)
@pytest.mark.asyncio
async def test_launch_node_dispatches_to_correct_service(
    node_type: str,
    service_method: str,
    app,
    override_nautilus_service,
    trader_headers,
):
    payload = {
        "type": node_type,
        "strategy": {
            "id": "strategy-id",
            "name": "Strategy",
            "parameters": [{"key": "symbol", "value": "BTCUSDT"}],
        },
        "adapters": [
            {
                "venue": "BINANCE",
                "alias": "Primary",
                "keyId": "key-1",
                "enableData": True,
                "enableTrading": True,
                "sandbox": node_type == "sandbox",
            }
        ],
        "constraints": {
            "maxRuntimeMinutes": None,
            "maxDrawdownPercent": None,
            "autoStopOnError": True,
            "concurrencyLimit": None,
        },
        "dataSources": [],
        "keyReferences": [],
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post("/nodes/launch", json=payload, headers=trader_headers)

    assert response.status_code == 201
    getattr(override_nautilus_service, service_method).assert_called_once()


@pytest.mark.asyncio
async def test_launch_node_rejects_unknown_type(app, override_nautilus_service, trader_headers):
    payload = {
        "type": "unknown",
        "strategy": {
            "id": "strategy-id",
            "name": "Strategy",
            "parameters": [{"key": "symbol", "value": "BTCUSDT"}],
        },
        "adapters": [],
        "constraints": {
            "maxRuntimeMinutes": None,
            "maxDrawdownPercent": None,
            "autoStopOnError": True,
            "concurrencyLimit": None,
        },
        "dataSources": [],
        "keyReferences": [],
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post("/nodes/launch", json=payload, headers=trader_headers)

    assert response.status_code == 400
    override_nautilus_service.start_backtest.assert_not_called()
    override_nautilus_service.start_live.assert_not_called()
    override_nautilus_service.start_sandbox.assert_not_called()


@pytest.mark.asyncio
async def test_stop_node_invokes_service(app, override_nautilus_service, trader_headers):
    node_id = "bt-11111111"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(f"/nodes/{node_id}/stop", headers=trader_headers)

    assert response.status_code == 200
    override_nautilus_service.stop_node.assert_called_once_with(node_id)


@pytest.mark.asyncio
async def test_restart_node_invokes_service(app, override_nautilus_service, trader_headers):
    node_id = "bt-11111111"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(f"/nodes/{node_id}/restart", headers=trader_headers)

    assert response.status_code == 200
    override_nautilus_service.restart_node.assert_called_once_with(node_id)


@pytest.mark.asyncio
async def test_delete_node_returns_no_content(app, override_nautilus_service, trader_headers):
    node_id = "bt-11111111"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(f"/nodes/{node_id}/delete", headers=trader_headers)

    assert response.status_code == 204
    override_nautilus_service.delete_node.assert_called_once_with(node_id)


@pytest.mark.asyncio
async def test_get_node_detail_uses_service(app, override_nautilus_service, trader_headers):
    node_id = "bt-11111111"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get(f"/nodes/{node_id}", headers=trader_headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["node"]["id"] == node_id
    override_nautilus_service.node_detail.assert_called_once_with(node_id)


@pytest.mark.asyncio
async def test_export_logs_returns_plain_text(app, override_nautilus_service, trader_headers):
    node_id = "bt-11111111"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get(f"/nodes/{node_id}/logs", headers=trader_headers)

    assert response.status_code == 200
    assert response.text == "log-entry"
    override_nautilus_service.export_logs.assert_called_once_with(node_id)


@pytest.mark.asyncio
async def test_get_node_logs_streams_snapshot(app, override_nautilus_service, trader_headers):
    node_id = "bt-11111111"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get(f"/nodes/{node_id}/logs/entries", headers=trader_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["logs"]
    override_nautilus_service.stream_snapshot.assert_called_once_with(node_id)
