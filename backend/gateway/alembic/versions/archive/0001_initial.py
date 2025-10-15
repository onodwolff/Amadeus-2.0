"""Initial database schema for the Amadeus gateway."""
from __future__ import annotations

from pathlib import Path
import sys
import types
from importlib import metadata as importlib_metadata

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

CURRENT_DIR = Path(__file__).resolve()
BACKEND_DIR = CURRENT_DIR.parents[2]
REPO_ROOT = BACKEND_DIR.parent

for path in (REPO_ROOT, BACKEND_DIR):
    if str(path) not in sys.path:
        sys.path.append(str(path))


def _install_logging_stub() -> None:
    stub = types.ModuleType("gateway.app.logging")
    stub.setup_logging = lambda *_, **__: None  # type: ignore[attr-defined]
    stub.bind_contextvars = lambda **__: None  # type: ignore[attr-defined]
    stub.clear_contextvars = lambda: None  # type: ignore[attr-defined]
    stub.get_logger = lambda *_: None  # type: ignore[attr-defined]
    sys.modules.setdefault("gateway.app.logging", stub)
    sys.modules.setdefault("backend.gateway.app.logging", stub)


def _install_email_validator_stub() -> None:
    try:
        importlib_metadata.version("email-validator")
        return
    except importlib_metadata.PackageNotFoundError:
        pass

    module = types.ModuleType("email_validator")
    module.__version__ = "2.0.0"

    class EmailNotValidError(ValueError):
        """Fallback error raised when email validation fails."""

    def validate_email(value: str, *args, **kwargs):  # type: ignore[unused-arg]
        return types.SimpleNamespace(email=value)

    module.EmailNotValidError = EmailNotValidError  # type: ignore[attr-defined]
    module.validate_email = validate_email  # type: ignore[attr-defined]
    module.__all__ = ["validate_email", "EmailNotValidError"]
    sys.modules.setdefault("email_validator", module)

    if not getattr(importlib_metadata, "_email_validator_stub_installed", False):
        original_version = importlib_metadata.version

        def _version(package_name: str) -> str:
            if package_name == "email-validator":
                return module.__version__
            return original_version(package_name)

        importlib_metadata.version = _version  # type: ignore[assignment]
        importlib_metadata._email_validator_stub_installed = True  # type: ignore[attr-defined]


_install_logging_stub()
_install_email_validator_stub()

try:  # pragma: no cover - support running from backend/
    from gateway.config import settings
except ModuleNotFoundError:  # pragma: no cover - support running from backend/
    from backend.gateway.config import settings  # type: ignore


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


SCHEMA = settings.storage.schema


def _enum(name: str, *values: str) -> sa.Enum:
    enum = sa.Enum(*values, name=name, schema=SCHEMA)
    enum.create_type = False
    return enum


_user_role = _enum("user_role", "admin", "member", "viewer")
_node_mode = _enum("node_mode", "backtest", "sandbox", "live")
_node_status = _enum("node_status", "created", "running", "stopped", "error")
_config_source = _enum("config_source", "upload", "template", "ui")
_config_format = _enum("config_format", "yaml", "json")
_position_mode = _enum("position_mode", "net", "hedge")
_order_status = _enum(
    "order_status",
    "new",
    "pending",
    "partially_filled",
    "filled",
    "canceled",
    "rejected",
    "expired",
    "failed",
)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("pwd_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "role",
            _user_role,
            server_default="member",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.UniqueConstraint("username", name="uq_users_username"),
    )

    op.create_table(
        "nodes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("mode", _node_mode, nullable=False),
        sa.Column("strategy_id", sa.String(length=128), nullable=True),
        sa.Column(
            "status",
            _node_status,
            server_default="created",
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "summary",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_nodes"),
    )
    op.create_index("ix_nodes_user_id", "nodes", ["user_id"], unique=False)
    op.create_index("ix_nodes_mode", "nodes", ["mode"], unique=False)
    op.create_index("ix_nodes_status", "nodes", ["status"], unique=False)

    op.create_table(
        "api_keys",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("venue", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=True),
        sa.Column("key_id", sa.String(length=128), nullable=False),
        sa.Column("api_key_masked", sa.String(length=128), nullable=False),
        sa.Column("secret_enc", sa.LargeBinary(), nullable=False),
        sa.Column(
            "scopes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_api_keys"),
        sa.UniqueConstraint("key_id", name="uq_api_keys_key_id"),
    )
    op.create_index("ix_api_keys_user_id", "api_keys", ["user_id"], unique=False)
    op.create_index("ix_api_keys_created_at", "api_keys", ["created_at"], unique=False)

    op.create_table(
        "configs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("node_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source", _config_source, nullable=False),
        sa.Column("format", _config_format, nullable=False),
        sa.Column(
            "content",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["node_id"], ["nodes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_configs"),
        sa.UniqueConstraint("node_id", "version", name="uq_configs_node_version"),
    )
    op.create_index("ix_configs_node_id", "configs", ["node_id"], unique=False)
    op.create_index("ix_configs_created_at", "configs", ["created_at"], unique=False)

    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("node_id", sa.Integer(), nullable=False),
        sa.Column("client_order_id", sa.String(length=128), nullable=True),
        sa.Column("instrument", sa.String(length=120), nullable=False),
        sa.Column("side", sa.String(length=16), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("tif", sa.String(length=16), nullable=True),
        sa.Column(
            "post_only",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "reduce_only",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column("price", sa.Numeric(precision=28, scale=8), nullable=True),
        sa.Column("qty", sa.Numeric(precision=28, scale=8), nullable=False),
        sa.Column(
            "status",
            _order_status,
            server_default="new",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "extra",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["node_id"], ["nodes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_orders"),
    )
    op.create_index("ix_orders_node_id", "orders", ["node_id"], unique=False)
    op.create_index("ix_orders_client_order_id", "orders", ["client_order_id"], unique=False)
    op.create_index("ix_orders_instrument", "orders", ["instrument"], unique=False)
    op.create_index("ix_orders_created_at", "orders", ["created_at"], unique=False)

    op.create_table(
        "positions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("node_id", sa.Integer(), nullable=False),
        sa.Column("instrument", sa.String(length=120), nullable=False),
        sa.Column("mode", _position_mode, nullable=False),
        sa.Column("qty", sa.Numeric(precision=28, scale=8), nullable=False),
        sa.Column("avg_price", sa.Numeric(precision=28, scale=8), nullable=True),
        sa.Column("unrealized_pnl", sa.Numeric(precision=28, scale=8), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["node_id"], ["nodes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_positions"),
        sa.UniqueConstraint("node_id", "instrument", "mode", name="uq_positions_scope"),
    )
    op.create_index("ix_positions_node_id", "positions", ["node_id"], unique=False)
    op.create_index("ix_positions_updated_at", "positions", ["updated_at"], unique=False)

    op.create_table(
        "balances",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("node_id", sa.Integer(), nullable=False),
        sa.Column("account", sa.String(length=120), nullable=False),
        sa.Column("asset", sa.String(length=64), nullable=False),
        sa.Column("free", sa.Numeric(precision=28, scale=8), nullable=False),
        sa.Column("locked", sa.Numeric(precision=28, scale=8), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["node_id"], ["nodes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_balances"),
        sa.UniqueConstraint("node_id", "account", "asset", name="uq_balances_scope"),
    )
    op.create_index("ix_balances_node_id", "balances", ["node_id"], unique=False)

    op.create_table(
        "executions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("trade_id", sa.String(length=128), nullable=False),
        sa.Column("price", sa.Numeric(precision=28, scale=8), nullable=False),
        sa.Column("qty", sa.Numeric(precision=28, scale=8), nullable=False),
        sa.Column("fee", sa.Numeric(precision=28, scale=8), nullable=True),
        sa.Column(
            "ts",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "extra",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_executions"),
    )
    op.create_index("ix_executions_order_id", "executions", ["order_id"], unique=False)
    op.create_index("ix_executions_trade_id", "executions", ["trade_id"], unique=True)
    op.create_index("ix_executions_ts", "executions", ["ts"], unique=False)

    op.create_table(
        "risk_limits",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("node_id", sa.Integer(), nullable=True),
        sa.Column(
            "cfg",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["node_id"], ["nodes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_risk_limits"),
        sa.UniqueConstraint("user_id", "node_id", name="uq_risk_limits_scope"),
    )
    op.create_index("ix_risk_limits_user_id", "risk_limits", ["user_id"], unique=False)
    op.create_index("ix_risk_limits_node_id", "risk_limits", ["node_id"], unique=False)

    op.create_table(
        "risk_alerts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("node_id", sa.Integer(), nullable=True),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "ts",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("cleared_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["node_id"], ["nodes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_risk_alerts"),
    )
    op.create_index("ix_risk_alerts_node_id", "risk_alerts", ["node_id"], unique=False)
    op.create_index("ix_risk_alerts_ts", "risk_alerts", ["ts"], unique=False)

    op.create_table(
        "watchlists",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_watchlists"),
        sa.UniqueConstraint("user_id", "name", name="uq_watchlists_user_name"),
    )
    op.create_index("ix_watchlists_user_id", "watchlists", ["user_id"], unique=False)
    op.create_index("ix_watchlists_created_at", "watchlists", ["created_at"], unique=False)

    op.create_table(
        "watchlist_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("watchlist_id", sa.Integer(), nullable=False),
        sa.Column("instrument", sa.String(length=120), nullable=False),
        sa.Column(
            "added_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["watchlist_id"], ["watchlists.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_watchlist_items"),
        sa.UniqueConstraint("watchlist_id", "instrument", name="uq_watchlist_items_unique"),
    )
    op.create_index(
        "ix_watchlist_items_watchlist_id",
        "watchlist_items",
        ["watchlist_id"],
        unique=False,
    )

    op.create_table(
        "logs_index",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("node_id", sa.Integer(), nullable=False),
        sa.Column("file_path", sa.String(length=255), nullable=False),
        sa.Column(
            "last_offset",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["node_id"], ["nodes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_logs_index"),
        sa.UniqueConstraint("node_id", "file_path", name="uq_logs_index_path"),
    )
    op.create_index("ix_logs_index_node_id", "logs_index", ["node_id"], unique=False)

    op.create_table(
        "equity_history",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("node_id", sa.Integer(), nullable=False),
        sa.Column(
            "ts",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("equity", sa.Numeric(precision=28, scale=8), nullable=False),
        sa.Column("pnl", sa.Numeric(precision=28, scale=8), nullable=False),
        sa.ForeignKeyConstraint(["node_id"], ["nodes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_equity_history"),
        sa.UniqueConstraint("node_id", "ts", name="uq_equity_history_node_ts"),
    )
    op.create_index("ix_equity_history_node_id", "equity_history", ["node_id"], unique=False)
    op.create_index("ix_equity_history_ts", "equity_history", ["ts"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_equity_history_ts", table_name="equity_history")
    op.drop_index("ix_equity_history_node_id", table_name="equity_history")
    op.drop_table("equity_history")

    op.drop_index("ix_logs_index_node_id", table_name="logs_index")
    op.drop_table("logs_index")

    op.drop_index("ix_watchlist_items_watchlist_id", table_name="watchlist_items")
    op.drop_table("watchlist_items")

    op.drop_index("ix_watchlists_created_at", table_name="watchlists")
    op.drop_index("ix_watchlists_user_id", table_name="watchlists")
    op.drop_table("watchlists")

    op.drop_index("ix_risk_alerts_ts", table_name="risk_alerts")
    op.drop_index("ix_risk_alerts_node_id", table_name="risk_alerts")
    op.drop_table("risk_alerts")

    op.drop_index("ix_risk_limits_node_id", table_name="risk_limits")
    op.drop_index("ix_risk_limits_user_id", table_name="risk_limits")
    op.drop_table("risk_limits")

    op.drop_index("ix_executions_ts", table_name="executions")
    op.drop_index("ix_executions_trade_id", table_name="executions")
    op.drop_index("ix_executions_order_id", table_name="executions")
    op.drop_table("executions")

    op.drop_index("ix_balances_node_id", table_name="balances")
    op.drop_table("balances")

    op.drop_index("ix_positions_updated_at", table_name="positions")
    op.drop_index("ix_positions_node_id", table_name="positions")
    op.drop_table("positions")

    op.drop_index("ix_orders_created_at", table_name="orders")
    op.drop_index("ix_orders_instrument", table_name="orders")
    op.drop_index("ix_orders_client_order_id", table_name="orders")
    op.drop_index("ix_orders_node_id", table_name="orders")
    op.drop_table("orders")

    op.drop_index("ix_configs_created_at", table_name="configs")
    op.drop_index("ix_configs_node_id", table_name="configs")
    op.drop_table("configs")

    op.drop_index("ix_api_keys_created_at", table_name="api_keys")
    op.drop_index("ix_api_keys_user_id", table_name="api_keys")
    op.drop_table("api_keys")

    op.drop_index("ix_nodes_status", table_name="nodes")
    op.drop_index("ix_nodes_mode", table_name="nodes")
    op.drop_index("ix_nodes_user_id", table_name="nodes")
    op.drop_table("nodes")

    op.drop_table("users")

    _order_status.drop(op.get_bind(), checkfirst=True)
    _position_mode.drop(op.get_bind(), checkfirst=True)
    _config_format.drop(op.get_bind(), checkfirst=True)
    _config_source.drop(op.get_bind(), checkfirst=True)
    _node_status.drop(op.get_bind(), checkfirst=True)
    _node_mode.drop(op.get_bind(), checkfirst=True)
    _user_role.drop(op.get_bind(), checkfirst=True)
