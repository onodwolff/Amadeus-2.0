import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from backend.gateway.app.nautilus_service import svc


@pytest.mark.asyncio
async def test_list_instruments_filters_by_venue(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/market/instruments")
        assert response.status_code == 200
        payload = response.json()
        assert payload["instruments"], "Expected instruments in response"
        venues = {item["venue"] for item in payload["instruments"]}
        assert "BINANCE" in venues

        filtered = await client.get("/market/instruments", params={"venue": "coinbase"})
        assert filtered.status_code == 200
        filtered_payload = filtered.json()
        assert filtered_payload["instruments"], "Expected filtered instruments"
        assert all(inst["venue"] == "COINBASE" for inst in filtered_payload["instruments"])


@pytest.mark.asyncio
async def test_watchlist_roundtrip(app):
    svc.update_watchlist([])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        initial = await client.get("/market/watchlist")
        assert initial.status_code == 200
        assert initial.json()["favorites"] == []

        update = await client.put(
            "/market/watchlist",
            json={"favorites": ["BINANCE:SPOT:BTCUSDT", "BINANCE:SPOT:BTCUSDT", "COINBASE:SPOT:ETHUSD"]},
        )
        assert update.status_code == 200
        assert update.json()["favorites"] == [
            "BINANCE:SPOT:BTCUSDT",
            "COINBASE:SPOT:ETHUSD",
        ]

        final = await client.get("/market/watchlist")
        assert final.status_code == 200
        assert final.json()["favorites"] == [
            "BINANCE:SPOT:BTCUSDT",
            "COINBASE:SPOT:ETHUSD",
        ]


@pytest.mark.asyncio
async def test_historical_bars_validation_and_payload(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        invalid = await client.get(
            "/market/instruments/BINANCE:SPOT:BTCUSDT/bars",
            params={"granularity": "fast"},
        )
        assert invalid.status_code == 422

        response = await client.get(
            "/market/instruments/BINANCE:SPOT:BTCUSDT/bars",
            params={"granularity": "1m", "limit": 5},
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
