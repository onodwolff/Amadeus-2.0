"""Add backtest_runs table for strategy optimisation"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0003_strategy_tester"
down_revision = "0002_historical_data"
branch_labels = None
depends_on = None


_backtest_run_status = sa.Enum(
    "pending",
    "running",
    "completed",
    "failed",
    name="backtest_run_status",
)


def upgrade() -> None:
    _backtest_run_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "backtest_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("plan", sa.String(length=32), nullable=False),
        sa.Column("status", _backtest_run_status, nullable=False, server_default="pending"),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "parameters",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "base_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "metrics",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("optimisation_metric", sa.String(length=64), nullable=True),
        sa.Column("optimisation_direction", sa.String(length=16), nullable=True),
        sa.Column("optimisation_score", sa.Numeric(precision=20, scale=10), nullable=True),
        sa.Column("node_id", sa.String(length=64), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            server_onupdate=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_backtest_runs"),
        sa.UniqueConstraint("run_id", "position", name="uq_backtest_runs_run_id_position"),
    )
    op.create_index("ix_backtest_runs_run_id", "backtest_runs", ["run_id"], unique=False)
    op.create_index("ix_backtest_runs_status", "backtest_runs", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_backtest_runs_status", table_name="backtest_runs")
    op.drop_index("ix_backtest_runs_run_id", table_name="backtest_runs")
    op.drop_table("backtest_runs")

    _backtest_run_status.drop(op.get_bind(), checkfirst=True)
