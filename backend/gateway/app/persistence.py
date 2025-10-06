"""Gateway persistence helpers bridging services and the database layer."""
from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional, Awaitable

from .models import Execution, Instrument, Node, NodeLifecycle, NodeLog, NodeMetric, Order, RiskAlertRecord
from .storage import AsyncDatabase, DatabaseConfig, DatabaseNotAvailable

LOGGER = logging.getLogger("gateway.persistence")


def _parse_timestamp(value: Optional[str]) -> datetime:
    if not value:
        return datetime.now(tz=timezone.utc)
    candidate = value.strip()
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        LOGGER.debug("failed to parse timestamp", value=value)
        return datetime.now(tz=timezone.utc)


class NullStorage:
    """No-op storage backend used when the database is unavailable."""

    available: bool = False

    def record_instruments(self, instruments: Iterable[Dict[str, Any]]) -> None:
        return None

    def record_node(self, payload: Dict[str, Any]) -> None:
        return None

    def record_node_lifecycle(self, payload: Dict[str, Any]) -> None:
        return None

    def record_node_log(self, payload: Dict[str, Any]) -> None:
        return None

    def record_node_metric(self, payload: Dict[str, Any]) -> None:
        return None

    def record_order(self, payload: Dict[str, Any]) -> None:
        return None

    def record_execution(self, payload: Dict[str, Any]) -> None:
        return None

    def record_risk_alert(self, payload: Dict[str, Any]) -> None:
        return None


class GatewayStorage(NullStorage):
    """Threaded adapter exposing synchronous helpers backed by ``AsyncDatabase``."""

    def __init__(self, database: AsyncDatabase) -> None:
        self._database = database
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, name="gateway-storage", daemon=True)
        self._thread.start()
        self.available = False

    def _run_loop(self) -> None:  # pragma: no cover - infrastructure helper
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def initialise(self) -> bool:
        try:
            asyncio.run_coroutine_threadsafe(self._database.create_all(), self._loop).result(timeout=10.0)
        except (DatabaseNotAvailable, Exception) as exc:
            LOGGER.warning("database initialisation failed", exc_info=exc)
            return False
        self.available = True
        return True

    def shutdown(self) -> None:
        if self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def _submit(self, operation: Awaitable[None]) -> None:
        if not self.available:
            return
        try:
            asyncio.run_coroutine_threadsafe(operation, self._loop).result(timeout=10.0)
        except Exception as exc:  # pragma: no cover - defensive logging
            LOGGER.warning("storage operation failed", exc_info=exc)

    async def _upsert_instruments(self, instruments: Iterable[Dict[str, Any]]) -> None:
        async with self._database.session() as session:
            for instrument in instruments:
                instrument_id = instrument.get("instrument_id") or instrument.get("id")
                if not instrument_id:
                    continue
                venue = instrument.get("venue") or "UNKNOWN"
                symbol = instrument.get("symbol") or instrument_id
                record = await session.get(Instrument, instrument_id)
                if record is None:
                    record = Instrument(
                        instrument_id=instrument_id,
                        venue=venue,
                        symbol=symbol,
                        raw=dict(instrument),
                    )
                    session.add(record)
                else:
                    record.venue = venue
                    record.symbol = symbol
                    record.raw = dict(instrument)

    async def _upsert_node(self, payload: Dict[str, Any]) -> None:
        async with self._database.session() as session:
            node_id = payload["node_id"]
            record = await session.get(Node, node_id)
            if record is None:
                record = Node(
                    node_id=node_id,
                    mode=payload.get("mode"),
                    status=payload.get("status", "created"),
                    detail=payload.get("detail"),
                    metrics=payload.get("metrics") or {},
                    created_at=_parse_timestamp(payload.get("created_at")),
                    updated_at=_parse_timestamp(payload.get("updated_at")),
                )
                session.add(record)
            else:
                record.mode = payload.get("mode", record.mode)
                record.status = payload.get("status", record.status)
                record.detail = payload.get("detail", record.detail)
                record.metrics = payload.get("metrics", record.metrics)
                record.updated_at = _parse_timestamp(payload.get("updated_at"))

    async def _insert_lifecycle(self, payload: Dict[str, Any]) -> None:
        async with self._database.session() as session:
            entry = NodeLifecycle(
                node_id=payload["node_id"],
                status=payload.get("status", "unknown"),
                message=payload.get("message", ""),
                timestamp=_parse_timestamp(payload.get("timestamp")),
            )
            session.add(entry)

    async def _insert_log(self, payload: Dict[str, Any]) -> None:
        async with self._database.session() as session:
            entry = NodeLog(
                node_id=payload["node_id"],
                level=payload.get("level", "info"),
                message=payload.get("message", ""),
                source=payload.get("source", "gateway"),
                timestamp=_parse_timestamp(payload.get("timestamp")),
            )
            session.add(entry)

    async def _insert_metric(self, payload: Dict[str, Any]) -> None:
        async with self._database.session() as session:
            entry = NodeMetric(
                node_id=payload["node_id"],
                timestamp=_parse_timestamp(payload.get("timestamp")),
                pnl=float(payload.get("pnl") or payload.get("metrics", {}).get("pnl", 0.0)),
                latency_ms=float(payload.get("latency_ms") or payload.get("metrics", {}).get("latency_ms", 0.0)),
                cpu_percent=float(payload.get("cpu_percent") or payload.get("metrics", {}).get("cpu_percent", 0.0)),
                memory_mb=float(payload.get("memory_mb") or payload.get("metrics", {}).get("memory_mb", 0.0)),
            )
            session.add(entry)

    async def _upsert_order(self, payload: Dict[str, Any]) -> None:
        async with self._database.session() as session:
            order_id = payload["order_id"]
            record = await session.get(Order, order_id)
            if record is None:
                record = Order(order_id=order_id)
                session.add(record)
            record.client_order_id = payload.get("client_order_id")
            record.venue_order_id = payload.get("venue_order_id")
            record.symbol = payload.get("symbol", "")
            record.venue = payload.get("venue", "")
            record.side = payload.get("side", "")
            record.type = payload.get("type", "")
            record.quantity = float(payload.get("quantity") or 0.0)
            record.filled_quantity = float(payload.get("filled_quantity") or 0.0)
            record.price = payload.get("price")
            record.average_price = payload.get("average_price")
            record.status = payload.get("status", record.status)
            record.time_in_force = payload.get("time_in_force")
            record.expire_time = payload.get("expire_time")
            record.instructions = payload.get("instructions") or {}
            record.node_id = payload.get("node_id")
            record.created_at = _parse_timestamp(payload.get("created_at"))
            record.updated_at = _parse_timestamp(payload.get("updated_at"))

    async def _insert_execution(self, payload: Dict[str, Any]) -> None:
        async with self._database.session() as session:
            execution = Execution(
                execution_id=payload["execution_id"],
                order_id=payload.get("order_id"),
                symbol=payload.get("symbol", ""),
                venue=payload.get("venue", ""),
                price=float(payload.get("price") or 0.0),
                quantity=float(payload.get("quantity") or 0.0),
                side=payload.get("side", ""),
                liquidity=payload.get("liquidity"),
                fees=float(payload.get("fees") or 0.0),
                timestamp=_parse_timestamp(payload.get("timestamp")),
                node_id=payload.get("node_id"),
            )
            session.add(execution)

    async def _upsert_risk_alert(self, payload: Dict[str, Any]) -> None:
        async with self._database.session() as session:
            alert_id = payload["alert_id"]
            record = await session.get(RiskAlertRecord, alert_id)
            if record is None:
                record = RiskAlertRecord(alert_id=alert_id)
                session.add(record)
            record.category = payload.get("category", record.category)
            record.severity = payload.get("severity", record.severity)
            record.title = payload.get("title", record.title)
            record.message = payload.get("message", record.message)
            record.node_id = payload.get("node_id")
            record.acknowledged = bool(payload.get("acknowledged", record.acknowledged))
            record.context = payload.get("context", record.context)
            record.timestamp = _parse_timestamp(payload.get("timestamp"))

    def record_instruments(self, instruments: Iterable[Dict[str, Any]]) -> None:  # type: ignore[override]
        self._submit(self._upsert_instruments(instruments))

    def record_node(self, payload: Dict[str, Any]) -> None:  # type: ignore[override]
        self._submit(self._upsert_node(payload))

    def record_node_lifecycle(self, payload: Dict[str, Any]) -> None:  # type: ignore[override]
        self._submit(self._insert_lifecycle(payload))

    def record_node_log(self, payload: Dict[str, Any]) -> None:  # type: ignore[override]
        self._submit(self._insert_log(payload))

    def record_node_metric(self, payload: Dict[str, Any]) -> None:  # type: ignore[override]
        self._submit(self._insert_metric(payload))

    def record_order(self, payload: Dict[str, Any]) -> None:  # type: ignore[override]
        self._submit(self._upsert_order(payload))

    def record_execution(self, payload: Dict[str, Any]) -> None:  # type: ignore[override]
        self._submit(self._insert_execution(payload))

    def record_risk_alert(self, payload: Dict[str, Any]) -> None:  # type: ignore[override]
        self._submit(self._upsert_risk_alert(payload))


def build_storage(database_url: str) -> NullStorage:
    config = DatabaseConfig(url=database_url)
    database = AsyncDatabase(config)
    storage = GatewayStorage(database)
    if storage.initialise():
        return storage
    return NullStorage()

