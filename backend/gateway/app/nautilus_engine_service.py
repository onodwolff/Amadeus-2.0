"""Gateway integration helpers for the NautilusTrader engine.

This module centralises the wiring required for the gateway to interact with
an underlying NautilusTrader deployment.  It provides a small event bus used by
the HTTP handlers and WebSocket producers to exchange telemetry without
coupling them to the concrete engine implementation.  When the actual
``nautilus_trader`` package is importable we expose a couple of convenience
helpers for loading configuration and bootstrapping nodes, while keeping the
mock/simulated implementations available for tests.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from enum import Enum
import threading
from typing import Any, AsyncIterator, Dict, Optional

try:  # pragma: no cover - optional dependency during unit tests
    import nautilus_trader as _nt  # type: ignore
except Exception:  # pragma: no cover - optional dependency during unit tests
    _nt = None


class EngineMode(str, Enum):
    """Supported runtime modes for Nautilus nodes."""

    BACKTEST = "backtest"
    LIVE = "live"


@dataclass(frozen=True)
class EngineNodeLaunch:
    """Payload describing a requested node launch."""

    mode: EngineMode
    detail: str
    config: Dict[str, Any]


class EngineEventBus:
    """Thread-safe asynchronous pub/sub helper for gateway telemetry."""

    def __init__(self, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        self._external_loop = loop
        if loop is None:
            self._loop = asyncio.new_event_loop()
            self._loop_thread = threading.Thread(
                target=self._loop_runner,
                name="nautilus-gateway-bus",
                daemon=True,
            )
            self._loop_thread.start()
        else:
            self._loop = loop
            self._loop_thread = None

        self._subscriptions: Dict[str, set[asyncio.Queue]] = {}
        self._lock = threading.RLock()

    def _loop_runner(self) -> None:  # pragma: no cover - infrastructure helper
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        return self._loop

    @property
    def external(self) -> bool:
        return self._external_loop is not None

    def publish(self, topic: str, payload: Dict[str, Any]) -> None:
        """Publish *payload* to all subscribers listening on *topic*."""

        with self._lock:
            queues = list(self._subscriptions.get(topic, set()))

        for queue in queues:
            try:
                running_loop = asyncio.get_running_loop()
            except RuntimeError:
                running_loop = None

            if running_loop is self._loop:
                queue.put_nowait(payload)
            elif self._loop.is_running():
                asyncio.run_coroutine_threadsafe(queue.put(payload), self._loop)
            else:  # pragma: no cover - loop bootstrap path
                queue.put_nowait(payload)

    @contextlib.asynccontextmanager
    async def subscribe(self, topic: str) -> AsyncIterator["EngineSubscription"]:
        """Return an asynchronous subscription to *topic*."""

        queue: asyncio.Queue = asyncio.Queue()
        subscription = EngineSubscription(self, topic, queue)

        with self._lock:
            self._subscriptions.setdefault(topic, set()).add(queue)

        try:
            yield subscription
        finally:
            with self._lock:
                queues = self._subscriptions.get(topic)
                if queues is not None:
                    queues.discard(queue)
                    if not queues:
                        self._subscriptions.pop(topic, None)

    async def drain(self) -> None:
        """Stop the internally managed event loop (mainly for tests)."""

        if self._external_loop is not None:
            return

        if self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._loop_thread is not None and self._loop_thread.is_alive():
            self._loop_thread.join(timeout=1.0)


class EngineSubscription:
    """Asynchronous iterator returned by :class:`EngineEventBus`."""

    def __init__(
        self,
        bus: EngineEventBus,
        topic: str,
        queue: asyncio.Queue,
    ) -> None:
        self._bus = bus
        self._topic = topic
        self._queue = queue

    def __aiter__(self) -> "EngineSubscription":
        return self

    async def __anext__(self) -> Dict[str, Any]:
        payload = await self._queue.get()
        if payload is None:  # pragma: no cover - defensive guard
            raise StopAsyncIteration
        return payload

    async def get(self) -> Dict[str, Any]:
        """Explicit awaitable helper returning the next payload."""

        return await self.__anext__()

    def queue(self) -> asyncio.Queue:
        return self._queue


class NautilusEngineService:
    """Minimal wrapper around NautilusTrader engine primitives."""

    def __init__(self, bus: Optional[EngineEventBus] = None) -> None:
        self._bus = bus or EngineEventBus()
        self._nt = _nt

    @property
    def bus(self) -> EngineEventBus:
        return self._bus

    @property
    def nautilus(self):  # type: ignore[override]
        """Return the imported ``nautilus_trader`` module if available."""

        if self._nt is None:
            raise RuntimeError(
                "nautilus_trader is not installed. Install the package in the gateway "
                "environment or provide the vendor bundle."
            )
        return self._nt

    def ensure_package(self) -> bool:
        """Return whether the Nautilus package is available."""

        return self._nt is not None

    def publish(self, topic: str, payload: Dict[str, Any]) -> None:
        self._bus.publish(topic, payload)

    async def subscribe(self, topic: str) -> AsyncIterator[EngineSubscription]:
        async with self._bus.subscribe(topic) as subscription:
            yield subscription


def build_engine_service(bus: Optional[EngineEventBus] = None) -> NautilusEngineService:
    """Factory helper used across the gateway to construct the engine wrapper."""

    return NautilusEngineService(bus=bus)

