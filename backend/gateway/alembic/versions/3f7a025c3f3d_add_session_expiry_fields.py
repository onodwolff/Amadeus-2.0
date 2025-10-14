"""Add absolute and idle expiry tracking to auth sessions."""
from __future__ import annotations

import sys
from pathlib import Path

import sqlalchemy as sa
from alembic import op

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


revision = "3f7a025c3f3d"
down_revision = "8d8c8cfa3f42"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "auth_sessions",
        sa.Column("absolute_expires_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "auth_sessions",
        sa.Column("idle_expires_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )

    auth_sessions = sa.table(
        "auth_sessions",
        sa.column("id", sa.Integer()),
        sa.column("expires_at", sa.DateTime(timezone=True)),
        sa.column("absolute_expires_at", sa.DateTime(timezone=True)),
        sa.column("idle_expires_at", sa.DateTime(timezone=True)),
    )

    bind = op.get_bind()
    now = sa.func.now()

    bind.execute(
        sa.update(auth_sessions)
        .where(auth_sessions.c.absolute_expires_at.is_(None))
        .values(absolute_expires_at=auth_sessions.c.expires_at)
    )
    bind.execute(
        sa.update(auth_sessions)
        .where(auth_sessions.c.idle_expires_at.is_(None))
        .values(idle_expires_at=now)
    )

    op.alter_column(
        "auth_sessions",
        "absolute_expires_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
        schema=SCHEMA,
    )
    op.alter_column(
        "auth_sessions",
        "idle_expires_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_column("auth_sessions", "idle_expires_at", schema=SCHEMA)
    op.drop_column("auth_sessions", "absolute_expires_at", schema=SCHEMA)
