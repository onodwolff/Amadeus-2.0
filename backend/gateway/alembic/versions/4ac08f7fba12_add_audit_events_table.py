from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from backend.gateway.alembic.versions.c7f96b8e4e7c_initial_schema import SCHEMA


# revision identifiers, used by Alembic.
revision = "4ac08f7fba12"
down_revision = "3f7a025c3f3d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("result", sa.String(length=32), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("target_user_id", sa.Integer(), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            [f"{SCHEMA}.users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["target_user_id"],
            [f"{SCHEMA}.users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=SCHEMA,
    )
    op.create_index(
        op.f("ix_audit_events_action"),
        "audit_events",
        ["action"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_audit_events_action_occurred_at",
        "audit_events",
        ["action", "occurred_at"],
        schema=SCHEMA,
    )
    op.create_index(
        op.f("ix_audit_events_actor_user_id"),
        "audit_events",
        ["actor_user_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_audit_events_actor_occurred_at",
        "audit_events",
        ["actor_user_id", "occurred_at"],
        schema=SCHEMA,
    )
    op.create_index(
        op.f("ix_audit_events_occurred_at"),
        "audit_events",
        ["occurred_at"],
        schema=SCHEMA,
    )
    op.create_index(
        op.f("ix_audit_events_result"),
        "audit_events",
        ["result"],
        schema=SCHEMA,
    )
    op.create_index(
        op.f("ix_audit_events_target_user_id"),
        "audit_events",
        ["target_user_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_audit_events_target_occurred_at",
        "audit_events",
        ["target_user_id", "occurred_at"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_audit_events_target_occurred_at",
        table_name="audit_events",
        schema=SCHEMA,
    )
    op.drop_index(
        op.f("ix_audit_events_target_user_id"),
        table_name="audit_events",
        schema=SCHEMA,
    )
    op.drop_index(
        op.f("ix_audit_events_result"),
        table_name="audit_events",
        schema=SCHEMA,
    )
    op.drop_index(
        op.f("ix_audit_events_occurred_at"),
        table_name="audit_events",
        schema=SCHEMA,
    )
    op.drop_index(
        "ix_audit_events_actor_occurred_at",
        table_name="audit_events",
        schema=SCHEMA,
    )
    op.drop_index(
        op.f("ix_audit_events_actor_user_id"),
        table_name="audit_events",
        schema=SCHEMA,
    )
    op.drop_index(
        "ix_audit_events_action_occurred_at",
        table_name="audit_events",
        schema=SCHEMA,
    )
    op.drop_index(
        op.f("ix_audit_events_action"),
        table_name="audit_events",
        schema=SCHEMA,
    )
    op.drop_table("audit_events", schema=SCHEMA)
