"""Create audit events table."""
from __future__ import annotations

import sys
from pathlib import Path

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

CURRENT_DIR = Path(__file__).resolve()
BACKEND_DIR = CURRENT_DIR.parents[2]
REPO_ROOT = BACKEND_DIR.parent

for path_entry in (REPO_ROOT, BACKEND_DIR):
    if str(path_entry) not in sys.path:
        sys.path.append(str(path_entry))

try:
    from gateway.alembic.versions.c7f96b8e4e7c_initial_schema import SCHEMA
except ModuleNotFoundError:  # pragma: no cover - support running from backend/
    from backend.gateway.alembic.versions.c7f96b8e4e7c_initial_schema import SCHEMA  # type: ignore


# revision identifiers, used by Alembic.
revision = "8513069b165d"
down_revision = "5e5c7f4d5b70"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("event", postgresql.JSONB(), nullable=False),
        sa.Column("ip", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            [f"{SCHEMA}.users.id"],
            ondelete="SET NULL",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_audit_events_created_at",
        "audit_events",
        ["created_at"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_audit_events_user_id",
        "audit_events",
        ["user_id"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_audit_events_user_id",
        table_name="audit_events",
        schema=SCHEMA,
    )
    op.drop_index(
        "ix_audit_events_created_at",
        table_name="audit_events",
        schema=SCHEMA,
    )
    op.drop_table("audit_events", schema=SCHEMA)
