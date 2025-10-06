"""Engine event state synchronisation helpers."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Awaitable, Callable, Dict, Iterable, Optional

from sqlalchemy import Boolean, DateTime, Float, String, Text, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

try:  # pragma: no cover - optional dependency
    from sqlalchemy.dialects.postgresql import JSONB, insert
except Exception:  # pragma: no cover - fallback for tests without PG dialect
    from sqlalchemy import JSON as JSONB  # type: ignore
    from sqlalchemy import insert  # type: ignore

try:  # pragma: no cover - optional dependency
    import redis.asyncio as redis
except Exception:  # pragma: no cover - optional dependency
    redis = None

from .nautilus_engine_service import EngineEventBus

LOGGER = logging.getLogger("gateway.state_sync")


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):  # pragma: no cover - defensive guard
        return None


def _to_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value or None
    try:
        return str(value)
    except Exception:  # pragma: no cover - defensive guard
        return None


def _parse_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if not value:
        return datetime.now(tz=timezone.utc)
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return datetime.now(tz=timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime,)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    raise TypeError(f"Object of type {type(value)!r} is not JSON serialisable")


class Base(DeclarativeBase):
    """Declarative base used for engine state tables."""


class EngineOrder(Base):
    """Snapshot of an order emitted by the engine."""

    __tablename__ = "engine_orders"

    order_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    client_order_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    venue_order_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    node_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    symbol: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    venue: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    side: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    quantity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    filled_quantity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    average_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    time_in_force: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    expire_time: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    instructions: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    raw: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class EngineExecution(Base):
    """Execution information linked to an order."""

    __tablename__ = "engine_executions"

    execution_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    node_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    symbol: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    venue: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    side: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    liquidity: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    quantity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    fees: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    raw: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class EnginePosition(Base):
    """Current position snapshot keyed by ``position_id``."""

    __tablename__ = "engine_positions"

    position_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    node_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    account_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    account_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    venue: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    symbol: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    quantity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    average_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    mark_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    unrealized_pnl: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    realized_pnl: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    margin_used: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    raw: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class EngineBalance(Base):
    """Account balance snapshot keyed by node/account/asset."""

    __tablename__ = "engine_balances"

    node_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    asset: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    venue: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    currency: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    total: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    available: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    locked: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    raw: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class EngineEquityHistory(Base):
    """Historical equity samples per node."""

    __tablename__ = "engine_equity_history"

    node_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    equity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pnl: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    raw: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class EngineRiskAlert(Base):
    """Risk alerts emitted by the engine risk module."""

    __tablename__ = "engine_risk_alerts"

    alert_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    node_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    category: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    severity: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    acknowledged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    context: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    raw: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class EngineStateSync:
    """Synchronise engine telemetry into a relational store."""

    def __init__(
        self,
        bus: EngineEventBus,
        database_url: str,
        *,
        redis_url: str | None = None,
    ) -> None:
        self._bus = bus
        self._engine: AsyncEngine = create_async_engine(database_url, future=True)
        self._session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self._engine,
            expire_on_commit=False,
        )
        self._redis_url = redis_url
        self._redis: Optional["redis.Redis[bytes]"] = None
        self._tasks: list[asyncio.Task[None]] = []
        self._startup_future: Optional[asyncio.Future[None]] = None
        self._started = asyncio.Event()

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------
    def start(self) -> None:
        """Start background consumers for state synchronisation."""

        if self._startup_future is not None:
            return

        async def bootstrap() -> None:
            try:
                async with self._engine.begin() as connection:
                    await connection.run_sync(Base.metadata.create_all)
            except Exception as exc:  # pragma: no cover - defensive guard
                LOGGER.warning("state_sync_initialisation_failed", exc_info=exc)
                return

            if self._redis_url and redis is not None:
                try:
                    self._redis = redis.from_url(self._redis_url)
                except Exception:  # pragma: no cover - optional dependency
                    LOGGER.warning("state_sync_redis_initialisation_failed", exc_info=True)
                    self._redis = None

            self._tasks = [
                asyncio.create_task(self._consume("engine.orders", self._handle_orders), name="state-sync-orders"),
                asyncio.create_task(self._consume("engine.executions", self._handle_executions), name="state-sync-executions"),
                asyncio.create_task(self._consume("engine.portfolio", self._handle_portfolio), name="state-sync-portfolio"),
                asyncio.create_task(self._consume("engine.risk.alerts", self._handle_risk_alerts), name="state-sync-risk"),
            ]
            self._started.set()

        loop = self._bus.loop
        self._startup_future = asyncio.run_coroutine_threadsafe(bootstrap(), loop)

    async def close(self) -> None:
        """Cancel consumers and dispose the underlying resources."""

        if self._startup_future is not None:
            await asyncio.wrap_future(self._startup_future)

        if self._tasks:
            for task in list(self._tasks):
                task.cancel()
            await asyncio.gather(*self._tasks, return_exceptions=True)
            self._tasks.clear()

        if self._redis is not None:
            try:
                await self._redis.close()
            except Exception:  # pragma: no cover - optional dependency
                LOGGER.debug("state_sync_redis_close_failed", exc_info=True)
            self._redis = None

        await self._engine.dispose()

    # ------------------------------------------------------------------
    # Core consumers
    # ------------------------------------------------------------------
    async def _consume(
        self,
        topic: str,
        handler: Callable[[str, Dict[str, Any]], Awaitable[None]],
    ) -> None:
        try:
            async with self._bus.subscribe(topic) as subscription:
                async for payload in subscription:
                    try:
                        await handler(topic, payload)
                    except asyncio.CancelledError:  # pragma: no cover - cancellation path
                        raise
                    except Exception:
                        LOGGER.exception("state_sync_handler_failed", extra={"topic": topic})
        except asyncio.CancelledError:  # pragma: no cover - cancellation path
            raise
        except Exception:
            LOGGER.exception("state_sync_subscription_failed", extra={"topic": topic})

    async def _handle_orders(self, topic: str, payload: Dict[str, Any]) -> None:
        await self._mirror_to_redis(topic, payload)
        async with self._session_factory() as session:
            try:
                event = (payload.get("event") or "").lower()
                orders: list[Dict[str, Any]] = []
                executions: Iterable[Dict[str, Any]] = []

                if event == "snapshot":
                    orders.extend(payload.get("orders") or [])
                    executions = payload.get("executions") or []
                if "order" in payload:
                    orders.append(payload["order"])
                if event != "snapshot" and payload.get("orders"):
                    orders.extend(payload.get("orders") or [])
                if "execution" in payload:
                    executions = list(executions) + [payload["execution"]]

                for order in orders:
                    await self._upsert_order(session, order)

                for execution in executions:
                    await self._record_execution(session, execution)

                await session.commit()
            except Exception:
                await session.rollback()
                LOGGER.exception("state_sync_orders_failed")

    async def _handle_executions(self, topic: str, payload: Dict[str, Any]) -> None:
        await self._mirror_to_redis(topic, payload)
        async with self._session_factory() as session:
            try:
                executions = payload.get("executions")
                if executions is None:
                    executions = [payload.get("execution")]
                for execution in executions or []:
                    await self._record_execution(session, execution)

                order = payload.get("order") or {}
                order_id = _to_str(order.get("order_id") or payload.get("order_id"))
                status = _to_str(order.get("status") or payload.get("status"))
                if order_id and status:
                    await session.execute(
                        update(EngineOrder)
                        .where(EngineOrder.order_id == order_id)
                        .values(status=status, updated_at=_parse_timestamp(order.get("updated_at") or datetime.utcnow()))
                    )
                await session.commit()
            except Exception:
                await session.rollback()
                LOGGER.exception("state_sync_executions_failed")

    async def _handle_portfolio(self, topic: str, payload: Dict[str, Any]) -> None:
        await self._mirror_to_redis(topic, payload)
        async with self._session_factory() as session:
            try:
                portfolio = payload.get("portfolio") or payload
                balances = portfolio.get("balances") or payload.get("balances") or []
                positions = portfolio.get("positions") or payload.get("positions") or []
                timestamp = _parse_timestamp(portfolio.get("timestamp") or payload.get("timestamp"))

                equity_value = _to_float(portfolio.get("equity_value"))
                node_id = None

                for balance in balances:
                    node_id = node_id or _to_str(balance.get("node_id"))
                    await self._upsert_balance(session, balance)

                for position in positions:
                    node_id = node_id or _to_str(position.get("node_id"))
                    await self._upsert_position(session, position)

                if node_id and equity_value is not None:
                    pnl_value = portfolio.get("pnl")
                    if pnl_value is None:
                        realized = sum(_to_float(p.get("realized_pnl")) or 0.0 for p in positions)
                        unrealized = sum(_to_float(p.get("unrealized_pnl")) or 0.0 for p in positions)
                        pnl_value = realized + unrealized
                    await self._append_equity_sample(
                        session,
                        node_id,
                        timestamp,
                        equity_value,
                        _to_float(pnl_value),
                        portfolio,
                    )

                await session.commit()
            except Exception:
                await session.rollback()
                LOGGER.exception("state_sync_portfolio_failed")

    async def _handle_risk_alerts(self, topic: str, payload: Dict[str, Any]) -> None:
        await self._mirror_to_redis(topic, payload)
        alert = payload.get("alert") or payload
        async with self._session_factory() as session:
            try:
                await self._upsert_risk_alert(session, alert)
                await session.commit()
            except Exception:
                await session.rollback()
                LOGGER.exception("state_sync_risk_alert_failed")

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------
    async def _upsert_order(self, session: AsyncSession, order: Dict[str, Any]) -> None:
        order_id = _to_str(order.get("order_id") or order.get("id"))
        if not order_id:
            LOGGER.debug("state_sync_order_missing_id", extra={"order": order})
            return

        payload = {
            "order_id": order_id,
            "client_order_id": _to_str(order.get("client_order_id")),
            "venue_order_id": _to_str(order.get("venue_order_id")),
            "node_id": _to_str(order.get("node_id")),
            "symbol": _to_str(order.get("symbol")),
            "venue": _to_str(order.get("venue")),
            "side": _to_str(order.get("side")),
            "type": _to_str(order.get("type") or order.get("order_type")),
            "status": _to_str(order.get("status")) or "unknown",
            "quantity": _to_float(order.get("quantity") or order.get("qty")),
            "filled_quantity": _to_float(order.get("filled_quantity") or order.get("filledQty")),
            "price": _to_float(order.get("price")),
            "average_price": _to_float(order.get("average_price") or order.get("avg_price")),
            "time_in_force": _to_str(order.get("time_in_force") or order.get("tif")),
            "expire_time": _to_str(order.get("expire_time")),
            "instructions": order.get("instructions"),
            "raw": order,
            "created_at": _parse_timestamp(order.get("created_at")),
            "updated_at": _parse_timestamp(order.get("updated_at")),
        }

        statement = insert(EngineOrder).values(**payload)
        update_columns = {
            key: statement.excluded[key]
            for key in payload.keys()
            if key not in {"order_id", "created_at"}
        }
        await session.execute(statement.on_conflict_do_update(index_elements=[EngineOrder.order_id], set_=update_columns))

    async def _record_execution(self, session: AsyncSession, execution: Dict[str, Any]) -> None:
        if not execution:
            return
        execution_id = _to_str(execution.get("execution_id") or execution.get("id") or execution.get("trade_id"))
        if not execution_id:
            LOGGER.debug("state_sync_execution_missing_id", extra={"execution": execution})
            return
        payload = {
            "execution_id": execution_id,
            "order_id": _to_str(execution.get("order_id")),
            "node_id": _to_str(execution.get("node_id")),
            "symbol": _to_str(execution.get("symbol")),
            "venue": _to_str(execution.get("venue")),
            "side": _to_str(execution.get("side")),
            "liquidity": _to_str(execution.get("liquidity")),
            "price": _to_float(execution.get("price")),
            "quantity": _to_float(execution.get("quantity") or execution.get("qty")),
            "fees": _to_float(execution.get("fees") or execution.get("fee")),
            "timestamp": _parse_timestamp(execution.get("timestamp") or execution.get("ts")),
            "raw": execution,
        }
        statement = insert(EngineExecution).values(**payload)
        await session.execute(statement.on_conflict_do_nothing(index_elements=[EngineExecution.execution_id]))

    async def _upsert_position(self, session: AsyncSession, position: Dict[str, Any]) -> None:
        identifier = _to_str(position.get("position_id"))
        if not identifier:
            node = _to_str(position.get("node_id")) or "unknown"
            symbol = _to_str(position.get("symbol")) or "unknown"
            identifier = f"{node}:{symbol}"
        payload = {
            "position_id": identifier,
            "node_id": _to_str(position.get("node_id")),
            "account_id": _to_str(position.get("account_id")),
            "account_name": _to_str(position.get("account_name")),
            "venue": _to_str(position.get("venue")),
            "symbol": _to_str(position.get("symbol")),
            "quantity": _to_float(position.get("quantity") or position.get("qty")),
            "average_price": _to_float(position.get("average_price") or position.get("avg_price")),
            "mark_price": _to_float(position.get("mark_price")),
            "unrealized_pnl": _to_float(position.get("unrealized_pnl")),
            "realized_pnl": _to_float(position.get("realized_pnl")),
            "margin_used": _to_float(position.get("margin_used")),
            "updated_at": _parse_timestamp(position.get("updated_at")),
            "raw": position,
        }
        statement = insert(EnginePosition).values(**payload)
        update_columns = {
            key: statement.excluded[key]
            for key in payload.keys()
            if key not in {"position_id"}
        }
        await session.execute(statement.on_conflict_do_update(index_elements=[EnginePosition.position_id], set_=update_columns))

    async def _upsert_balance(self, session: AsyncSession, balance: Dict[str, Any]) -> None:
        node_id = _to_str(balance.get("node_id")) or "unknown"
        account_id = _to_str(balance.get("account_id") or balance.get("account")) or "default"
        asset = _to_str(balance.get("currency") or balance.get("asset")) or "asset"
        payload = {
            "node_id": node_id,
            "account_id": account_id,
            "asset": asset,
            "account_name": _to_str(balance.get("account_name")),
            "venue": _to_str(balance.get("venue")),
            "currency": _to_str(balance.get("currency")),
            "total": _to_float(balance.get("total")),
            "available": _to_float(balance.get("available") or balance.get("free")),
            "locked": _to_float(balance.get("locked")),
            "updated_at": _parse_timestamp(balance.get("updated_at")),
            "raw": balance,
        }
        statement = insert(EngineBalance).values(**payload)
        update_columns = {
            key: statement.excluded[key]
            for key in payload.keys()
            if key not in {"node_id", "account_id", "asset"}
        }
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=[EngineBalance.node_id, EngineBalance.account_id, EngineBalance.asset],
                set_=update_columns,
            )
        )

    async def _append_equity_sample(
        self,
        session: AsyncSession,
        node_id: str,
        timestamp: datetime,
        equity: Optional[float],
        pnl: Optional[float],
        raw: Dict[str, Any],
    ) -> None:
        payload = {
            "node_id": node_id,
            "timestamp": timestamp,
            "equity": equity,
            "pnl": pnl,
            "raw": raw,
        }
        statement = insert(EngineEquityHistory).values(**payload)
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=[EngineEquityHistory.node_id, EngineEquityHistory.timestamp],
                set_={
                    "equity": statement.excluded.equity,
                    "pnl": statement.excluded.pnl,
                    "raw": statement.excluded.raw,
                },
            )
        )

    async def _upsert_risk_alert(self, session: AsyncSession, alert: Dict[str, Any]) -> None:
        alert_id = _to_str(alert.get("alert_id") or alert.get("id"))
        if not alert_id:
            LOGGER.debug("state_sync_alert_missing_id", extra={"alert": alert})
            return
        payload = {
            "alert_id": alert_id,
            "node_id": _to_str(alert.get("node_id")),
            "category": _to_str(alert.get("category")),
            "severity": _to_str(alert.get("severity")),
            "title": _to_str(alert.get("title")),
            "message": _to_str(alert.get("message")),
            "acknowledged": bool(alert.get("acknowledged", False)),
            "timestamp": _parse_timestamp(alert.get("timestamp")),
            "context": alert.get("context"),
            "raw": alert,
        }
        statement = insert(EngineRiskAlert).values(**payload)
        update_columns = {
            key: statement.excluded[key]
            for key in payload.keys()
            if key not in {"alert_id"}
        }
        await session.execute(statement.on_conflict_do_update(index_elements=[EngineRiskAlert.alert_id], set_=update_columns))

    # ------------------------------------------------------------------
    # Redis mirroring
    # ------------------------------------------------------------------
    async def _mirror_to_redis(self, topic: str, payload: Dict[str, Any]) -> None:
        if self._redis is None:
            return
        try:
            message = json.dumps(payload, default=_json_default)
            await self._redis.publish(topic, message)
        except Exception:  # pragma: no cover - optional dependency
            LOGGER.debug("state_sync_redis_publish_failed", exc_info=True)


__all__ = [
    "EngineStateSync",
]
