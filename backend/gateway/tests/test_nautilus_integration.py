import asyncio

import pytest

from ..app.nautilus_engine_service import EngineEventBus, build_engine_service
from ..app.nautilus_service import NautilusService


@pytest.mark.asyncio
async def test_node_stream_emits_after_launch():
    loop = asyncio.get_event_loop()
    bus = EngineEventBus(loop=loop)
    engine = build_engine_service(bus=bus)
    service = NautilusService(engine=engine)

    node_stream = service.node_stream()
    task = asyncio.create_task(node_stream.__anext__())
    await asyncio.sleep(0)

    node = service.start_backtest(detail="integration-test")

    event = await asyncio.wait_for(task, timeout=1.0)
    assert event["node"]["id"] == node.id
    assert event["event"] in {"created", "running"}

    await node_stream.aclose()


@pytest.mark.asyncio
async def test_orders_stream_tracks_new_order():
    loop = asyncio.get_event_loop()
    bus = EngineEventBus(loop=loop)
    engine = build_engine_service(bus=bus)
    service = NautilusService(engine=engine)

    order_stream = service.orders_stream()

    async def wait_for(predicate):
        while True:
            payload = await order_stream.__anext__()
            if predicate(payload):
                return payload

    waiter = asyncio.create_task(wait_for(lambda payload: payload.get("event") == "created"))
    await asyncio.sleep(0)

    service.create_order(
        {
            "symbol": "BTCUSDT",
            "venue": "BINANCE",
            "side": "buy",
            "type": "limit",
            "quantity": 0.25,
            "price": 28000.0,
        }
    )

    payload = await asyncio.wait_for(waiter, timeout=1.0)
    assert payload["order"]["symbol"] == "BTCUSDT"
    assert payload["order"]["venue"] == "BINANCE"

    await order_stream.aclose()


def test_user_management_flow():
    loop = asyncio.get_event_loop()
    bus = EngineEventBus(loop=loop)
    engine = build_engine_service(bus=bus)
    service = NautilusService(engine=engine)

    listing = service.list_users()
    assert "users" in listing
    existing_count = len(listing["users"])
    assert existing_count >= 1

    created = service.create_user(
        {
            "name": "Quality Analyst",
            "email": "qa.user@example.com",
            "username": "qa.user",
            "password": "secure-pass-123",
            "role": "viewer",
        }
    )["user"]

    assert created["name"] == "Quality Analyst"
    assert created["email"] == "qa.user@example.com"
    assert created["username"] == "qa.user"
    assert created["active"] is True

    fetched = service.get_user(created["user_id"])["user"]
    assert fetched["user_id"] == created["user_id"]
    assert fetched["created_at"] == created["created_at"]

    updated = service.update_user(
        created["user_id"],
        {"name": "QA Lead", "active": False},
    )["user"]
    assert updated["name"] == "QA Lead"
    assert updated["active"] is False
    assert updated["updated_at"] != created["updated_at"]

    with pytest.raises(ValueError):
        service.create_user(
            {
                "name": "Duplicate QA",
                "email": created["email"],
                "username": "qa.duplicate",
                "password": "another-pass-123",
                "role": "viewer",
            }
        )


def test_engine_empty_payloads_are_not_overridden():
    engine = build_engine_service()
    service = NautilusService(engine=engine)

    engine.list_instruments = lambda venue=None: {"instruments": []}
    engine.get_historical_bars = lambda **kwargs: {"bars": []}

    def fail_list_instruments(**kwargs):
        raise AssertionError("mock list_instruments should not be used")

    def fail_get_historical_bars(**kwargs):
        raise AssertionError("mock get_historical_bars should not be used")

    service._mock.list_instruments = fail_list_instruments
    service._mock.get_historical_bars = fail_get_historical_bars

    assert service.list_instruments() == {"instruments": []}
    assert service.get_historical_bars(
        instrument_id="BTCUSDT",
        granularity="1m",
    ) == {"bars": []}
