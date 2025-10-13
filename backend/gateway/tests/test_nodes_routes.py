from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from httpx import ASGITransport, AsyncClient

from backend.gateway.app.nautilus_service import NodeHandle
from backend.gateway.app.routes import nodes as nodes_routes


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


@pytest.mark.asyncio
async def test_list_nodes_returns_handles(app, override_nautilus_service):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/nodes")
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
        response = await client.post("/nodes/launch", json=payload)

    assert response.status_code == 201
    getattr(override_nautilus_service, service_method).assert_called_once()


@pytest.mark.asyncio
async def test_launch_node_rejects_unknown_type(app, override_nautilus_service):
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
        response = await client.post("/nodes/launch", json=payload)

    assert response.status_code == 400
    override_nautilus_service.start_backtest.assert_not_called()
    override_nautilus_service.start_live.assert_not_called()
    override_nautilus_service.start_sandbox.assert_not_called()


@pytest.mark.asyncio
async def test_stop_node_invokes_service(app, override_nautilus_service):
    node_id = "bt-11111111"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(f"/nodes/{node_id}/stop")

    assert response.status_code == 200
    override_nautilus_service.stop_node.assert_called_once_with(node_id)


@pytest.mark.asyncio
async def test_restart_node_invokes_service(app, override_nautilus_service):
    node_id = "bt-11111111"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(f"/nodes/{node_id}/restart")

    assert response.status_code == 200
    override_nautilus_service.restart_node.assert_called_once_with(node_id)


@pytest.mark.asyncio
async def test_delete_node_returns_no_content(app, override_nautilus_service):
    node_id = "bt-11111111"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(f"/nodes/{node_id}/delete")

    assert response.status_code == 204
    override_nautilus_service.delete_node.assert_called_once_with(node_id)


@pytest.mark.asyncio
async def test_get_node_detail_uses_service(app, override_nautilus_service):
    node_id = "bt-11111111"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get(f"/nodes/{node_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["node"]["id"] == node_id
    override_nautilus_service.node_detail.assert_called_once_with(node_id)


@pytest.mark.asyncio
async def test_export_logs_returns_plain_text(app, override_nautilus_service):
    node_id = "bt-11111111"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get(f"/nodes/{node_id}/logs")

    assert response.status_code == 200
    assert response.text == "log-entry"
    override_nautilus_service.export_logs.assert_called_once_with(node_id)


@pytest.mark.asyncio
async def test_get_node_logs_streams_snapshot(app, override_nautilus_service):
    node_id = "bt-11111111"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get(f"/nodes/{node_id}/logs/entries")

    assert response.status_code == 200
    data = response.json()
    assert data["logs"]
    override_nautilus_service.stream_snapshot.assert_called_once_with(node_id)
