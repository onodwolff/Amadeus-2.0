"""SQLAlchemy ORM models for the gateway data store."""
from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import String, TypeDecorator

from .base import Base


class UserRole(str, enum.Enum):
    """Role associated with a user account."""

    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class NodeMode(str, enum.Enum):
    """Runtime mode of a node."""

    BACKTEST = "backtest"
    SANDBOX = "sandbox"
    LIVE = "live"


class NodeStatus(str, enum.Enum):
    """Lifecycle status of a node."""

    CREATED = "created"
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"


class ConfigSource(str, enum.Enum):
    """Source of a configuration payload."""

    UPLOAD = "upload"
    TEMPLATE = "template"
    UI = "ui"


class ConfigFormat(str, enum.Enum):
    """Encoding format of configuration content."""

    YAML = "yaml"
    JSON = "json"


class PositionMode(str, enum.Enum):
    """Position accounting mode."""

    NET = "net"
    HEDGE = "hedge"


class OrderStatus(str, enum.Enum):
    """Status of an order."""

    NEW = "new"
    PENDING = "pending"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"
    EXPIRED = "expired"
    FAILED = "failed"


JSON_EMPTY_OBJECT = text("'{}'::jsonb")
JSON_EMPTY_ARRAY = text("'[]'::jsonb")


class CaseInsensitiveText(TypeDecorator):
    """Case-insensitive text compatible with SQLite and PostgreSQL CITEXT."""

    impl = String
    cache_ok = True

    def __init__(self, length: int = 320) -> None:
        super().__init__(length)
        self.length = length

    def load_dialect_impl(self, dialect):  # type: ignore[override]
        if dialect.name == "postgresql":
            return dialect.type_descriptor(CITEXT())
        return dialect.type_descriptor(String(self.length))


class User(Base):
    """Registered user of the platform."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(CaseInsensitiveText(), unique=True, nullable=False)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(255))
    password_hash: Mapped[str] = mapped_column("pwd_hash", String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role"),
        nullable=False,
        default=UserRole.MEMBER,
        server_default=UserRole.MEMBER.value,
    )
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    mfa_secret: Mapped[Optional[str]] = mapped_column(Text)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        server_onupdate=func.now(),
    )

    api_keys: Mapped[List["ApiKey"]] = relationship(
        "ApiKey", back_populates="user", cascade="all, delete-orphan"
    )
    nodes: Mapped[List["Node"]] = relationship(
        "Node", back_populates="user", cascade="all, delete-orphan"
    )
    risk_limits: Mapped[List["RiskLimit"]] = relationship(
        "RiskLimit", back_populates="user", cascade="all, delete-orphan"
    )
    watchlists: Mapped[List["Watchlist"]] = relationship(
        "Watchlist", back_populates="user", cascade="all, delete-orphan"
    )
    sessions: Mapped[List["AuthSession"]] = relationship(
        "AuthSession", back_populates="user", cascade="all, delete-orphan"
    )
    pending_email_change: Mapped[Optional["EmailChangeRequest"]] = relationship(
        "EmailChangeRequest", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )

    @property
    def pwd_hash(self) -> str:  # pragma: no cover - compatibility shim
        return self.password_hash

    @pwd_hash.setter
    def pwd_hash(self, value: str) -> None:  # pragma: no cover - compatibility shim
        self.password_hash = value


class ApiKey(Base):
    """API key material issued to a user."""

    __tablename__ = "api_keys"
    __table_args__ = (
        Index("ix_api_keys_user_id", "user_id"),
        Index("ix_api_keys_created_at", "created_at"),
        UniqueConstraint("key_id", name="uq_api_keys_key_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    venue: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[Optional[str]] = mapped_column(String(120))
    key_id: Mapped[str] = mapped_column(String(128), nullable=False)
    api_key_masked: Mapped[str] = mapped_column(String(128), nullable=False)
    secret_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    scopes: Mapped[List[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=JSON_EMPTY_ARRAY,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship("User", back_populates="api_keys")


class Node(Base):
    """Execution node launched for a user strategy."""

    __tablename__ = "nodes"
    __table_args__ = (
        Index("ix_nodes_user_id", "user_id"),
        Index("ix_nodes_mode", "mode"),
        Index("ix_nodes_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    mode: Mapped[NodeMode] = mapped_column(
        Enum(NodeMode, name="node_mode"), nullable=False
    )
    strategy_id: Mapped[Optional[str]] = mapped_column(String(128))
    status: Mapped[NodeStatus] = mapped_column(
        Enum(NodeStatus, name="node_status"),
        nullable=False,
        default=NodeStatus.CREATED,
        server_default=NodeStatus.CREATED.value,
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    stopped_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    summary: Mapped[Dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=JSON_EMPTY_OBJECT,
    )

    user: Mapped[User] = relationship("User", back_populates="nodes")
    configs: Mapped[List["Config"]] = relationship(
        "Config", back_populates="node", cascade="all, delete-orphan"
    )
    orders: Mapped[List["Order"]] = relationship(
        "Order", back_populates="node", cascade="all, delete-orphan"
    )
    positions: Mapped[List["Position"]] = relationship(
        "Position", back_populates="node", cascade="all, delete-orphan"
    )
    balances: Mapped[List["Balance"]] = relationship(
        "Balance", back_populates="node", cascade="all, delete-orphan"
    )
    risk_alerts: Mapped[List["RiskAlert"]] = relationship(
        "RiskAlert", back_populates="node", cascade="all, delete-orphan"
    )
    logs_index: Mapped[List["LogsIndex"]] = relationship(
        "LogsIndex", back_populates="node", cascade="all, delete-orphan"
    )
    equity_history: Mapped[List["EquityHistory"]] = relationship(
        "EquityHistory", back_populates="node", cascade="all, delete-orphan"
    )


class Config(Base):
    """Versioned configuration attached to a node."""

    __tablename__ = "configs"
    __table_args__ = (
        Index("ix_configs_node_id", "node_id"),
        Index("ix_configs_created_at", "created_at"),
        UniqueConstraint("node_id", "version", name="uq_configs_node_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    node_id: Mapped[int] = mapped_column(
        ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[ConfigSource] = mapped_column(
        Enum(ConfigSource, name="config_source"), nullable=False
    )
    format: Mapped[ConfigFormat] = mapped_column(
        Enum(ConfigFormat, name="config_format"), nullable=False
    )
    content: Mapped[Dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=JSON_EMPTY_OBJECT,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    node: Mapped[Node] = relationship("Node", back_populates="configs")


class Order(Base):
    """Order submitted by a node."""

    __tablename__ = "orders"
    __table_args__ = (
        Index("ix_orders_node_id", "node_id"),
        Index("ix_orders_client_order_id", "client_order_id"),
        Index("ix_orders_instrument", "instrument"),
        Index("ix_orders_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    node_id: Mapped[int] = mapped_column(
        ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False
    )
    client_order_id: Mapped[Optional[str]] = mapped_column(String(128))
    instrument: Mapped[str] = mapped_column(String(120), nullable=False)
    side: Mapped[str] = mapped_column(String(16), nullable=False)
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    tif: Mapped[Optional[str]] = mapped_column(String(16))
    post_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reduce_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    price: Mapped[Optional[Decimal]] = mapped_column(Numeric(precision=28, scale=8))
    qty: Mapped[Decimal] = mapped_column(Numeric(precision=28, scale=8), nullable=False)
    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus, name="order_status"),
        nullable=False,
        default=OrderStatus.NEW,
        server_default=OrderStatus.NEW.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    extra: Mapped[Dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=JSON_EMPTY_OBJECT,
    )

    node: Mapped[Node] = relationship("Node", back_populates="orders")
    executions: Mapped[List["Execution"]] = relationship(
        "Execution", back_populates="order", cascade="all, delete-orphan"
    )


class Execution(Base):
    """Execution information linked to an order."""

    __tablename__ = "executions"
    __table_args__ = (
        Index("ix_executions_order_id", "order_id"),
        Index("ix_executions_trade_id", "trade_id", unique=True),
        Index("ix_executions_ts", "ts"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    trade_id: Mapped[str] = mapped_column(String(128), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(precision=28, scale=8), nullable=False)
    qty: Mapped[Decimal] = mapped_column(Numeric(precision=28, scale=8), nullable=False)
    fee: Mapped[Optional[Decimal]] = mapped_column(Numeric(precision=28, scale=8))
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    extra: Mapped[Dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=JSON_EMPTY_OBJECT,
    )

    order: Mapped[Order] = relationship("Order", back_populates="executions")


class Position(Base):
    """Current position for an instrument on a node."""

    __tablename__ = "positions"
    __table_args__ = (
        Index("ix_positions_node_id", "node_id"),
        Index("ix_positions_updated_at", "updated_at"),
        UniqueConstraint("node_id", "instrument", "mode", name="uq_positions_scope"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    node_id: Mapped[int] = mapped_column(
        ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False
    )
    instrument: Mapped[str] = mapped_column(String(120), nullable=False)
    mode: Mapped[PositionMode] = mapped_column(
        Enum(PositionMode, name="position_mode"), nullable=False
    )
    qty: Mapped[Decimal] = mapped_column(Numeric(precision=28, scale=8), nullable=False)
    avg_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(precision=28, scale=8))
    unrealized_pnl: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(precision=28, scale=8)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    node: Mapped[Node] = relationship("Node", back_populates="positions")


class Balance(Base):
    """Account balance captured for a node."""

    __tablename__ = "balances"
    __table_args__ = (
        Index("ix_balances_node_id", "node_id"),
        UniqueConstraint("node_id", "account", "asset", name="uq_balances_scope"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    node_id: Mapped[int] = mapped_column(
        ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False
    )
    account: Mapped[str] = mapped_column(String(120), nullable=False)
    asset: Mapped[str] = mapped_column(String(64), nullable=False)
    free: Mapped[Decimal] = mapped_column(Numeric(precision=28, scale=8), nullable=False)
    locked: Mapped[Decimal] = mapped_column(Numeric(precision=28, scale=8), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    node: Mapped[Node] = relationship("Node", back_populates="balances")


class RiskLimit(Base):
    """Risk constraint configuration for a user or node."""

    __tablename__ = "risk_limits"
    __table_args__ = (
        Index("ix_risk_limits_user_id", "user_id"),
        Index("ix_risk_limits_node_id", "node_id"),
        UniqueConstraint("user_id", "node_id", name="uq_risk_limits_scope"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    node_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("nodes.id", ondelete="CASCADE"), nullable=True
    )
    cfg: Mapped[Dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=JSON_EMPTY_OBJECT,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship("User", back_populates="risk_limits")
    node: Mapped[Optional[Node]] = relationship("Node")


class RiskAlert(Base):
    """Alert emitted by the risk engine."""

    __tablename__ = "risk_alerts"
    __table_args__ = (
        Index("ix_risk_alerts_node_id", "node_id"),
        Index("ix_risk_alerts_ts", "ts"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    node_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("nodes.id", ondelete="CASCADE"), nullable=True
    )
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    cleared_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    node: Mapped[Optional[Node]] = relationship("Node", back_populates="risk_alerts")


class Watchlist(Base):
    """User defined watchlist."""

    __tablename__ = "watchlists"
    __table_args__ = (
        Index("ix_watchlists_user_id", "user_id"),
        Index("ix_watchlists_created_at", "created_at"),
        UniqueConstraint("user_id", "name", name="uq_watchlists_user_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    user: Mapped[User] = relationship("User", back_populates="watchlists")
    items: Mapped[List["WatchlistItem"]] = relationship(
        "WatchlistItem", back_populates="watchlist", cascade="all, delete-orphan"
    )


class AuthSession(Base):
    """Refresh token session issued to a user."""

    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    refresh_token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    user_agent: Mapped[Optional[str]] = mapped_column(String(255))
    ip_address: Mapped[Optional[str]] = mapped_column(String(45))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship("User", back_populates="sessions")


class EmailChangeRequest(Base):
    """Pending e-mail change that requires verification."""

    __tablename__ = "email_change_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    new_email: Mapped[str] = mapped_column(CaseInsensitiveText(), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship("User", back_populates="pending_email_change")


class WatchlistItem(Base):
    """Instrument entry within a watchlist."""

    __tablename__ = "watchlist_items"
    __table_args__ = (
        Index("ix_watchlist_items_watchlist_id", "watchlist_id"),
        UniqueConstraint("watchlist_id", "instrument", name="uq_watchlist_items_unique"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    watchlist_id: Mapped[int] = mapped_column(
        ForeignKey("watchlists.id", ondelete="CASCADE"), nullable=False
    )
    instrument: Mapped[str] = mapped_column(String(120), nullable=False)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    watchlist: Mapped[Watchlist] = relationship("Watchlist", back_populates="items")


class LogsIndex(Base):
    """Tracks log ingestion progress for a node log file."""

    __tablename__ = "logs_index"
    __table_args__ = (
        Index("ix_logs_index_node_id", "node_id"),
        UniqueConstraint("node_id", "file_path", name="uq_logs_index_path"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    node_id: Mapped[int] = mapped_column(
        ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False
    )
    file_path: Mapped[str] = mapped_column(String(255), nullable=False)
    last_offset: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    node: Mapped[Node] = relationship("Node", back_populates="logs_index")


class EquityHistory(Base):
    """Historical equity curve for a node."""

    __tablename__ = "equity_history"
    __table_args__ = (
        Index("ix_equity_history_node_id", "node_id"),
        Index("ix_equity_history_ts", "ts"),
        UniqueConstraint("node_id", "ts", name="uq_equity_history_node_ts"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    node_id: Mapped[int] = mapped_column(
        ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False
    )
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    equity: Mapped[Decimal] = mapped_column(Numeric(precision=28, scale=8), nullable=False)
    pnl: Mapped[Decimal] = mapped_column(Numeric(precision=28, scale=8), nullable=False)

    node: Mapped[Node] = relationship("Node", back_populates="equity_history")


class HistoricalDataStatus(str, enum.Enum):
    """Lifecycle status of a historical data snapshot."""

    PENDING = "pending"
    RUNNING = "running"
    READY = "ready"
    FAILED = "failed"


class HistoricalDataset(Base):
    """Metadata describing a cached historical market data snapshot."""

    __tablename__ = "historical_datasets"
    __table_args__ = (
        Index("ix_historical_datasets_fingerprint", "fingerprint", unique=True),
        Index("ix_historical_datasets_dataset_id", "dataset_id", unique=True),
        Index("ix_historical_datasets_status", "status"),
        Index("ix_historical_datasets_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[str] = mapped_column(String(160), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    venue: Mapped[str] = mapped_column(String(64), nullable=False)
    instrument: Mapped[str] = mapped_column(String(128), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(32), nullable=False)
    date_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    date_to: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[HistoricalDataStatus] = mapped_column(
        Enum(HistoricalDataStatus, name="historical_data_status"),
        nullable=False,
        default=HistoricalDataStatus.PENDING,
        server_default=HistoricalDataStatus.PENDING.value,
    )
    source: Mapped[Optional[str]] = mapped_column(String(64))
    path: Mapped[Optional[str]] = mapped_column(String(255))
    size_bytes: Mapped[Optional[int]] = mapped_column(Integer)
    rows: Mapped[Optional[int]] = mapped_column(Integer)
    error: Mapped[Optional[str]] = mapped_column(Text)
    parameters: Mapped[Dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=JSON_EMPTY_OBJECT,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    backtests: Mapped[List["BacktestResult"]] = relationship(
        "BacktestResult", back_populates="dataset", cascade="all, delete-orphan"
    )


class BacktestResult(Base):
    """Aggregated metrics recorded after a backtest run completes."""

    __tablename__ = "backtest_results"
    __table_args__ = (
        Index("ix_backtest_results_node_key", "node_key", unique=True),
        Index("ix_backtest_results_dataset_id", "dataset_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    node_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    dataset_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("historical_datasets.id", ondelete="SET NULL")
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    total_return: Mapped[Optional[Decimal]] = mapped_column(Numeric(precision=20, scale=10))
    sharpe_ratio: Mapped[Optional[Decimal]] = mapped_column(Numeric(precision=20, scale=10))
    max_drawdown: Mapped[Optional[Decimal]] = mapped_column(Numeric(precision=20, scale=10))
    metrics: Mapped[Dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=JSON_EMPTY_OBJECT,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    dataset: Mapped[Optional[HistoricalDataset]] = relationship(
        "HistoricalDataset", back_populates="backtests"
    )


class BacktestRunStatus(str, enum.Enum):
    """Execution status for a strategy optimisation job."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class BacktestRun(Base):
    """Persisted record of a single parameter combination backtest run."""

    __tablename__ = "backtest_runs"
    __table_args__ = (
        UniqueConstraint("run_id", "position", name="uq_backtest_runs_run_id_position"),
        Index("ix_backtest_runs_run_id", "run_id"),
        Index("ix_backtest_runs_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    plan: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[BacktestRunStatus] = mapped_column(
        Enum(BacktestRunStatus, name="backtest_run_status"),
        nullable=False,
        default=BacktestRunStatus.PENDING,
        server_default=BacktestRunStatus.PENDING.value,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    parameters: Mapped[Dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=JSON_EMPTY_OBJECT,
    )
    base_config: Mapped[Dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=JSON_EMPTY_OBJECT,
    )
    metrics: Mapped[Dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=JSON_EMPTY_OBJECT,
    )
    optimisation_metric: Mapped[Optional[str]] = mapped_column(String(64))
    optimisation_direction: Mapped[Optional[str]] = mapped_column(String(16))
    optimisation_score: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(precision=20, scale=10)
    )
    node_id: Mapped[Optional[str]] = mapped_column(String(64))
    error: Mapped[Optional[str]] = mapped_column(Text)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


__all__ = [
    "ApiKey",
    "BacktestRun",
    "BacktestRunStatus",
    "BacktestResult",
    "Balance",
    "Config",
    "ConfigFormat",
    "ConfigSource",
    "AuthSession",
    "EmailChangeRequest",
    "EquityHistory",
    "HistoricalDataStatus",
    "HistoricalDataset",
    "Execution",
    "LogsIndex",
    "Node",
    "NodeMode",
    "NodeStatus",
    "Order",
    "OrderStatus",
    "Position",
    "PositionMode",
    "RiskAlert",
    "RiskLimit",
    "User",
    "UserRole",
    "Watchlist",
    "WatchlistItem",
]
