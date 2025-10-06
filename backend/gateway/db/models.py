"""SQLAlchemy ORM models describing the gateway persistent state."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

try:  # pragma: no cover - support running from backend/ directory
    from gateway.app.nautilus_engine_service import EngineMode
except ModuleNotFoundError:  # pragma: no cover - support running from backend/
    from backend.gateway.app.nautilus_engine_service import EngineMode  # type: ignore

from .base import Base


class Instrument(Base):
    __tablename__ = "instruments"

    instrument_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    venue: Mapped[str] = mapped_column(String(60), index=True)
    symbol: Mapped[str] = mapped_column(String(120), index=True)
    raw: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)


class Node(Base):
    __tablename__ = "nodes"

    node_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    mode: Mapped[EngineMode] = mapped_column(Enum(EngineMode), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    detail: Mapped[Optional[str]] = mapped_column(Text)
    metrics: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )

    lifecycle_events: Mapped[list["NodeLifecycle"]] = relationship(
        "NodeLifecycle", cascade="all, delete-orphan", back_populates="node"
    )
    logs: Mapped[list["NodeLog"]] = relationship(
        "NodeLog", cascade="all, delete-orphan", back_populates="node"
    )
    metrics_series: Mapped[list["NodeMetric"]] = relationship(
        "NodeMetric", cascade="all, delete-orphan", back_populates="node"
    )


class NodeLifecycle(Base):
    __tablename__ = "node_lifecycle"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    node_id: Mapped[str] = mapped_column(ForeignKey("nodes.node_id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, index=True)

    node: Mapped[Node] = relationship("Node", back_populates="lifecycle_events")


class NodeLog(Base):
    __tablename__ = "node_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    node_id: Mapped[str] = mapped_column(ForeignKey("nodes.node_id", ondelete="CASCADE"), index=True)
    level: Mapped[str] = mapped_column(String(16), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, index=True)

    node: Mapped[Node] = relationship("Node", back_populates="logs")


class NodeMetric(Base):
    __tablename__ = "node_metrics"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    node_id: Mapped[str] = mapped_column(ForeignKey("nodes.node_id", ondelete="CASCADE"), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, index=True)
    pnl: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    cpu_percent: Mapped[float] = mapped_column(Float, default=0.0)
    memory_mb: Mapped[float] = mapped_column(Float, default=0.0)

    node: Mapped[Node] = relationship("Node", back_populates="metrics_series")


class Order(Base):
    __tablename__ = "orders"

    order_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    client_order_id: Mapped[Optional[str]] = mapped_column(String(80), index=True)
    venue_order_id: Mapped[Optional[str]] = mapped_column(String(80), index=True)
    symbol: Mapped[str] = mapped_column(String(120), index=True)
    venue: Mapped[str] = mapped_column(String(60), index=True)
    side: Mapped[str] = mapped_column(String(16))
    type: Mapped[str] = mapped_column(String(16))
    quantity: Mapped[float] = mapped_column(Float)
    filled_quantity: Mapped[float] = mapped_column(Float, default=0.0)
    price: Mapped[Optional[float]] = mapped_column(Float)
    average_price: Mapped[Optional[float]] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(32))
    time_in_force: Mapped[Optional[str]] = mapped_column(String(16))
    expire_time: Mapped[Optional[str]] = mapped_column(String(64))
    instructions: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    node_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )

    executions: Mapped[list["Execution"]] = relationship(
        "Execution", cascade="all, delete-orphan", back_populates="order"
    )


class Execution(Base):
    __tablename__ = "executions"

    execution_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.order_id", ondelete="CASCADE"), index=True)
    symbol: Mapped[str] = mapped_column(String(120), index=True)
    venue: Mapped[str] = mapped_column(String(60), index=True)
    price: Mapped[float] = mapped_column(Float)
    quantity: Mapped[float] = mapped_column(Float)
    side: Mapped[str] = mapped_column(String(16))
    liquidity: Mapped[Optional[str]] = mapped_column(String(16))
    fees: Mapped[float] = mapped_column(Float, default=0.0)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, index=True)
    node_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)

    order: Mapped[Order] = relationship("Order", back_populates="executions")


class RiskAlertRecord(Base):
    __tablename__ = "risk_alerts"

    alert_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    category: Mapped[str] = mapped_column(String(32), index=True)
    severity: Mapped[str] = mapped_column(String(16), index=True)
    title: Mapped[str] = mapped_column(String(120))
    message: Mapped[str] = mapped_column(Text)
    node_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    context: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, index=True)


__all__ = [
    "Execution",
    "Instrument",
    "Node",
    "NodeLifecycle",
    "NodeLog",
    "NodeMetric",
    "Order",
    "RiskAlertRecord",
]
