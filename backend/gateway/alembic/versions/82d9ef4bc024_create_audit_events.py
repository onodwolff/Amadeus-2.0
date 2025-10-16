"""Create audit events table."""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "82d9ef4bc024"
down_revision = "5e5c7f4d5b70"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("actor_id", sa.Integer, nullable=True),
        sa.Column("event", sa.String, nullable=False),
        sa.Column("metadata", sa.JSON, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("audit_events")
