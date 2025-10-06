"""Initial database schema for the gateway."""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

_engine_mode_enum = sa.Enum("backtest", "sandbox", "live", name="enginemode")


def upgrade() -> None:
    _engine_mode_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "instruments",
        sa.Column("instrument_id", sa.String(length=120), nullable=False),
        sa.Column("venue", sa.String(length=60), nullable=False),
        sa.Column("symbol", sa.String(length=120), nullable=False),
        sa.Column("raw", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("instrument_id", name="pk_instruments"),
    )
    op.create_index("ix_instruments_symbol", "instruments", ["symbol"], unique=False)
    op.create_index("ix_instruments_venue", "instruments", ["venue"], unique=False)

    op.create_table(
        "nodes",
        sa.Column("node_id", sa.String(length=64), nullable=False),
        sa.Column("mode", _engine_mode_enum, nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("node_id", name="pk_nodes"),
    )

    op.create_table(
        "node_lifecycle",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("node_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["node_id"], ["nodes.node_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_node_lifecycle"),
    )
    op.create_index("ix_node_lifecycle_node_id", "node_lifecycle", ["node_id"], unique=False)
    op.create_index("ix_node_lifecycle_timestamp", "node_lifecycle", ["timestamp"], unique=False)

    op.create_table(
        "node_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("node_id", sa.String(length=64), nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["node_id"], ["nodes.node_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_node_logs"),
    )
    op.create_index("ix_node_logs_node_id", "node_logs", ["node_id"], unique=False)
    op.create_index("ix_node_logs_timestamp", "node_logs", ["timestamp"], unique=False)

    op.create_table(
        "node_metrics",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("node_id", sa.String(length=64), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("pnl", sa.Float(), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("cpu_percent", sa.Float(), nullable=False),
        sa.Column("memory_mb", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["node_id"], ["nodes.node_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_node_metrics"),
    )
    op.create_index("ix_node_metrics_node_id", "node_metrics", ["node_id"], unique=False)
    op.create_index("ix_node_metrics_timestamp", "node_metrics", ["timestamp"], unique=False)

    op.create_table(
        "orders",
        sa.Column("order_id", sa.String(length=80), nullable=False),
        sa.Column("client_order_id", sa.String(length=80), nullable=True),
        sa.Column("venue_order_id", sa.String(length=80), nullable=True),
        sa.Column("symbol", sa.String(length=120), nullable=False),
        sa.Column("venue", sa.String(length=60), nullable=False),
        sa.Column("side", sa.String(length=16), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("filled_quantity", sa.Float(), nullable=False),
        sa.Column("price", sa.Float(), nullable=True),
        sa.Column("average_price", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("time_in_force", sa.String(length=16), nullable=True),
        sa.Column("expire_time", sa.String(length=64), nullable=True),
        sa.Column("instructions", sa.JSON(), nullable=False),
        sa.Column("node_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("order_id", name="pk_orders"),
    )
    op.create_index("ix_orders_client_order_id", "orders", ["client_order_id"], unique=False)
    op.create_index("ix_orders_created_at", "orders", ["created_at"], unique=False)
    op.create_index("ix_orders_node_id", "orders", ["node_id"], unique=False)
    op.create_index("ix_orders_symbol", "orders", ["symbol"], unique=False)
    op.create_index("ix_orders_venue", "orders", ["venue"], unique=False)
    op.create_index("ix_orders_venue_order_id", "orders", ["venue_order_id"], unique=False)

    op.create_table(
        "executions",
        sa.Column("execution_id", sa.String(length=80), nullable=False),
        sa.Column("order_id", sa.String(length=80), nullable=False),
        sa.Column("symbol", sa.String(length=120), nullable=False),
        sa.Column("venue", sa.String(length=60), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("side", sa.String(length=16), nullable=False),
        sa.Column("liquidity", sa.String(length=16), nullable=True),
        sa.Column("fees", sa.Float(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("node_id", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["order_id"], ["orders.order_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("execution_id", name="pk_executions"),
    )
    op.create_index("ix_executions_node_id", "executions", ["node_id"], unique=False)
    op.create_index("ix_executions_order_id", "executions", ["order_id"], unique=False)
    op.create_index("ix_executions_symbol", "executions", ["symbol"], unique=False)
    op.create_index("ix_executions_timestamp", "executions", ["timestamp"], unique=False)
    op.create_index("ix_executions_venue", "executions", ["venue"], unique=False)

    op.create_table(
        "risk_alerts",
        sa.Column("alert_id", sa.String(length=80), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("node_id", sa.String(length=64), nullable=True),
        sa.Column("acknowledged", sa.Boolean(), nullable=False),
        sa.Column("context", sa.JSON(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("alert_id", name="pk_risk_alerts"),
    )
    op.create_index("ix_risk_alerts_category", "risk_alerts", ["category"], unique=False)
    op.create_index("ix_risk_alerts_node_id", "risk_alerts", ["node_id"], unique=False)
    op.create_index("ix_risk_alerts_severity", "risk_alerts", ["severity"], unique=False)
    op.create_index("ix_risk_alerts_timestamp", "risk_alerts", ["timestamp"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_risk_alerts_timestamp", table_name="risk_alerts")
    op.drop_index("ix_risk_alerts_severity", table_name="risk_alerts")
    op.drop_index("ix_risk_alerts_node_id", table_name="risk_alerts")
    op.drop_index("ix_risk_alerts_category", table_name="risk_alerts")
    op.drop_table("risk_alerts")

    op.drop_index("ix_executions_venue", table_name="executions")
    op.drop_index("ix_executions_timestamp", table_name="executions")
    op.drop_index("ix_executions_symbol", table_name="executions")
    op.drop_index("ix_executions_order_id", table_name="executions")
    op.drop_index("ix_executions_node_id", table_name="executions")
    op.drop_table("executions")

    op.drop_index("ix_orders_venue_order_id", table_name="orders")
    op.drop_index("ix_orders_venue", table_name="orders")
    op.drop_index("ix_orders_symbol", table_name="orders")
    op.drop_index("ix_orders_node_id", table_name="orders")
    op.drop_index("ix_orders_created_at", table_name="orders")
    op.drop_index("ix_orders_client_order_id", table_name="orders")
    op.drop_table("orders")

    op.drop_index("ix_node_metrics_timestamp", table_name="node_metrics")
    op.drop_index("ix_node_metrics_node_id", table_name="node_metrics")
    op.drop_table("node_metrics")

    op.drop_index("ix_node_logs_timestamp", table_name="node_logs")
    op.drop_index("ix_node_logs_node_id", table_name="node_logs")
    op.drop_table("node_logs")

    op.drop_index("ix_node_lifecycle_timestamp", table_name="node_lifecycle")
    op.drop_index("ix_node_lifecycle_node_id", table_name="node_lifecycle")
    op.drop_table("node_lifecycle")

    op.drop_table("nodes")

    op.drop_index("ix_instruments_venue", table_name="instruments")
    op.drop_index("ix_instruments_symbol", table_name="instruments")
    op.drop_table("instruments")

    _engine_mode_enum.drop(op.get_bind(), checkfirst=True)
