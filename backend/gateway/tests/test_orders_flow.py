"""Tests for order persistence and engine state updates."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from backend.gateway.app.nautilus_engine_service import EngineEventBus
from backend.gateway.app.state_sync import EngineExecution, EngineOrder, EngineStateSync


class _StubOrderService:
    def __init__(self) -> None:
        self.payloads: list[dict] = []

    def create_order(self, payload: dict) -> dict:
        self.payloads.append(payload)
        now = datetime.now(timezone.utc).isoformat()
        return {
            "order": {
                "order_id": "ORD-001",
                "client_order_id": "CLIENT-1",
                "symbol": payload.get("symbol", "BTCUSDT"),
                "venue": payload.get("venue", "BINANCE"),
                "side": payload.get("side", "buy"),
                "type": payload.get("type", "limit"),
                "quantity": payload.get("quantity", 1.0),
                "price": payload.get("price", 30000.0),
                "status": "pending",
                "time_in_force": payload.get("time_in_force", "GTC"),
                "created_at": now,
                "updated_at": now,
            }
        }


@pytest.mark.asyncio
async def test_order_flow_persists_and_updates(db_session, session_factory, db_url, monkeypatch):
    """Creating an order should persist it and engine updates should change its status."""

    from backend.gateway.app.routes import orders

    stub_service = _StubOrderService()
    monkeypatch.setattr(orders, "svc", stub_service)

    create_payload = orders.OrderCreateRequest(
        symbol="ETHUSDT",
        venue="BINANCE",
        side="buy",
        type="limit",
        quantity=0.5,
        price=2500.0,
        time_in_force="GTC",
    )

    response = await orders.create_order(payload=create_payload, session=db_session)

    assert response.order.order_id == "ORD-001"
    assert response.order.status == "pending"

    verify_session = session_factory()
    try:
        result = await verify_session.execute(
            select(EngineOrder).where(EngineOrder.order_id == "ORD-001")
        )
        record = result.scalar_one()
        assert record.status == "pending"
        assert record.venue == "BINANCE"
    finally:
        await verify_session.close()

    # Simulate an execution event coming from the engine via the state sync worker.
    bus = EngineEventBus(loop=asyncio.get_event_loop())
    state_sync = EngineStateSync(bus=bus, database_url=db_url)
    try:
        await state_sync._handle_orders(  # type: ignore[attr-defined]
            "engine.orders",
            {
                "event": "update",
                "order": {
                    "order_id": "ORD-001",
                    "status": "filled",
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
                "execution": {
                    "execution_id": "EX-1",
                    "order_id": "ORD-001",
                    "symbol": "ETHUSDT",
                    "venue": "BINANCE",
                    "quantity": 0.5,
                    "price": 2500.0,
                    "side": "buy",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            },
        )
    finally:
        await state_sync.close()

    verify_session = session_factory()
    try:
        result = await verify_session.execute(
            select(EngineOrder).where(EngineOrder.order_id == "ORD-001")
        )
        record = result.scalar_one()
        assert record.status == "filled"

        executions = await verify_session.execute(
            select(EngineExecution).where(EngineExecution.order_id == "ORD-001")
        )
        execution_record = executions.scalar_one()
        assert execution_record.execution_id == "EX-1"
        assert execution_record.price == 2500.0
    finally:
        await verify_session.close()
