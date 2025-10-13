from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from backend.gateway.app.nautilus_service import svc
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
async def market_viewer_headers(db_session):
    user = await create_user(
        db_session,
        email=f"market-viewer-{uuid4()}@example.com",
        username=f"marketviewer-{uuid4().hex[:8]}",
        password="password",
        roles=[db_models.UserRole.VIEWER.value],
    )
    token, _ = create_test_access_token(subject=user.id, roles=[db_models.UserRole.VIEWER.value], scopes=["viewer"])
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def market_trader_headers(db_session):
    user = await create_user(
        db_session,
        email=f"market-trader-{uuid4()}@example.com",
        username=f"markettrader-{uuid4().hex[:8]}",
        password="password",
        roles=[db_models.UserRole.MEMBER.value],
    )
    token, _ = create_test_access_token(subject=user.id, roles=[db_models.UserRole.MEMBER.value], scopes=["trader"])
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_update_watchlist_requires_trader_scope(app, market_viewer_headers):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.put(
            "/market/watchlist",
            json={"favorites": ["BINANCE:SPOT:BTCUSDT"]},
            headers=market_viewer_headers,
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "Insufficient role"


@pytest.mark.asyncio
async def test_list_instruments_filters_by_venue(app, market_viewer_headers):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/market/instruments", headers=market_viewer_headers)
        assert response.status_code == 200
        payload = response.json()
        assert payload["instruments"], "Expected instruments in response"
        venues = {item["venue"] for item in payload["instruments"]}
        assert "BINANCE" in venues

        filtered = await client.get("/market/instruments", params={"venue": "coinbase"}, headers=market_viewer_headers)
        assert filtered.status_code == 200
        filtered_payload = filtered.json()
        assert filtered_payload["instruments"], "Expected filtered instruments"
        assert all(inst["venue"] == "COINBASE" for inst in filtered_payload["instruments"])


@pytest.mark.asyncio
async def test_watchlist_roundtrip(app, market_trader_headers):
    svc.update_watchlist([])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        initial = await client.get("/market/watchlist", headers=market_trader_headers)
        assert initial.status_code == 200
        assert initial.json()["favorites"] == []

        update = await client.put(
            "/market/watchlist",
            json={"favorites": ["BINANCE:SPOT:BTCUSDT", "BINANCE:SPOT:BTCUSDT", "COINBASE:SPOT:ETHUSD"]},
            headers=market_trader_headers,
        )
        assert update.status_code == 200
        assert update.json()["favorites"] == [
            "BINANCE:SPOT:BTCUSDT",
            "COINBASE:SPOT:ETHUSD",
        ]

        final = await client.get("/market/watchlist", headers=market_trader_headers)
        assert final.status_code == 200
        assert final.json()["favorites"] == [
            "BINANCE:SPOT:BTCUSDT",
            "COINBASE:SPOT:ETHUSD",
        ]


@pytest.mark.asyncio
async def test_historical_bars_validation_and_payload(app, market_viewer_headers):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        invalid = await client.get(
            "/market/instruments/BINANCE:SPOT:BTCUSDT/bars",
            params={"granularity": "fast"},
            headers=market_viewer_headers,
        )
        assert invalid.status_code == 422

        response = await client.get(
            "/market/instruments/BINANCE:SPOT:BTCUSDT/bars",
            params={"granularity": "1m", "limit": 5},
            headers=market_viewer_headers,
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["instrument_id"] == "BINANCE:SPOT:BTCUSDT"
        assert payload["granularity"] == "1m"
        assert len(payload["bars"]) == 5
        for bar in payload["bars"]:
            assert set(bar) == {"timestamp", "open", "high", "low", "close", "volume"}


@pytest.mark.parametrize(
    "endpoint,topic",
    [
        ("/ws/market/depth", "market.depth"),
        ("/ws/market/trades", "market.trades"),
        ("/ws/market/ticks", "market.ticks"),
    ],
)
def test_market_websocket_streams(app, endpoint, topic):
    client = TestClient(app)
    with client.websocket_connect(endpoint) as websocket:
        message = {"event": "ping", "source": topic}
        svc.bus.publish(topic, message)
        assert websocket.receive_json() == message

    instrument_id = "BINANCE:SPOT:BTCUSDT"
    with client.websocket_connect(f"{endpoint}?instrument_id={instrument_id}") as websocket:
        payload = {"instrument_id": instrument_id, "price": 123.45}
        svc.bus.publish(f"{topic}.{instrument_id}", payload)
        assert websocket.receive_json() == payload
