"""Add historical data catalog and backtest results tables."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0002_historical_data"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


_historical_data_status = sa.Enum(
    "pending",
    "running",
    "ready",
    "failed",
    name="historical_data_status",
)


def upgrade() -> None:
    _historical_data_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "historical_datasets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("dataset_id", sa.String(length=160), nullable=False),
        sa.Column("fingerprint", sa.String(length=160), nullable=False),
        sa.Column("venue", sa.String(length=64), nullable=False),
        sa.Column("instrument", sa.String(length=128), nullable=False),
        sa.Column("timeframe", sa.String(length=32), nullable=False),
        sa.Column("date_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("date_to", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status",
            _historical_data_status,
            server_default="pending",
            nullable=False,
        ),
        sa.Column("source", sa.String(length=64), nullable=True),
        sa.Column("path", sa.String(length=255), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("rows", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "parameters",
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
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_historical_datasets"),
        sa.UniqueConstraint("dataset_id", name="uq_historical_datasets_dataset_id"),
        sa.UniqueConstraint("fingerprint", name="uq_historical_datasets_fingerprint"),
    )
    op.create_index(
        "ix_historical_datasets_fingerprint",
        "historical_datasets",
        ["fingerprint"],
        unique=True,
    )
    op.create_index(
        "ix_historical_datasets_dataset_id",
        "historical_datasets",
        ["dataset_id"],
        unique=True,
    )
    op.create_index(
        "ix_historical_datasets_status",
        "historical_datasets",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_historical_datasets_created_at",
        "historical_datasets",
        ["created_at"],
        unique=False,
    )

    op.create_table(
        "backtest_results",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("node_key", sa.String(length=64), nullable=False),
        sa.Column("dataset_id", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_return", sa.Numeric(precision=20, scale=10), nullable=True),
        sa.Column("sharpe_ratio", sa.Numeric(precision=20, scale=10), nullable=True),
        sa.Column("max_drawdown", sa.Numeric(precision=20, scale=10), nullable=True),
        sa.Column(
            "metrics",
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
        sa.ForeignKeyConstraint([
            "dataset_id"
        ], ["historical_datasets.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_backtest_results"),
        sa.UniqueConstraint("node_key", name="uq_backtest_results_node_key"),
    )
    op.create_index(
        "ix_backtest_results_node_key", "backtest_results", ["node_key"], unique=True
    )
    op.create_index(
        "ix_backtest_results_dataset_id", "backtest_results", ["dataset_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_backtest_results_dataset_id", table_name="backtest_results")
    op.drop_index("ix_backtest_results_node_key", table_name="backtest_results")
    op.drop_table("backtest_results")

    op.drop_index("ix_historical_datasets_created_at", table_name="historical_datasets")
    op.drop_index("ix_historical_datasets_status", table_name="historical_datasets")
    op.drop_index("ix_historical_datasets_dataset_id", table_name="historical_datasets")
    op.drop_index("ix_historical_datasets_fingerprint", table_name="historical_datasets")
    op.drop_table("historical_datasets")

    _historical_data_status.drop(op.get_bind(), checkfirst=True)
