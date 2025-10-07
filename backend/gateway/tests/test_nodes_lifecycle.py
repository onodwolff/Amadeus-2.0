"""Tests covering the node launch and stop lifecycle."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from backend.gateway.app.nautilus_engine_service import EngineEventBus, build_engine_service
from backend.gateway.app.nautilus_service import MockNautilusService


@dataclass
class _StubHandle:
    adapters: list[dict[str, str]]

    def __post_init__(self) -> None:
        self.thread = type("_T", (), {"name": "stub-thread"})()


@pytest.mark.asyncio
async def test_node_launch_and_stop_lifecycle(monkeypatch):
    """Mock node launches should transition through running and stopped states."""

    loop = asyncio.get_event_loop()
    bus = EngineEventBus(loop=loop)
    engine = build_engine_service(bus=bus)
    service = MockNautilusService(engine=engine)

    adapters = [{"name": "gateway", "status": "ok"}]
    handle = _StubHandle(adapters=adapters)

    monkeypatch.setattr(service._engine_service, "ensure_package", lambda: True)
    monkeypatch.setattr(service._engine_service, "launch_trading_node", lambda **_: handle)
    monkeypatch.setattr(service._engine_service, "stop_trading_node", lambda node_id: handle)
    monkeypatch.setattr(service._engine_service, "get_node_adapter_status", lambda node_id: adapters)

    engine_state = {"running": False}

    def _engine_active(self) -> bool:  # type: ignore[unused-argument]
        return engine_state["running"]

    monkeypatch.setattr(MockNautilusService, "_engine_active", _engine_active, raising=False)

    node = service.start_backtest(detail="test lifecycle")
    engine_state["running"] = True

    assert node.status == "running"
    detail = service.node_detail(node.id)
    statuses = [event["status"] for event in detail["lifecycle"]]
    assert statuses[0] == "created"
    assert "running" in statuses

    stopped = service.stop_node(node.id)
    engine_state["running"] = False

    assert stopped.status == "stopped"
    detail = service.node_detail(node.id)
    statuses = [event["status"] for event in detail["lifecycle"]]
    assert statuses.count("stopped") == 1
    assert statuses[-1] == "stopped"
