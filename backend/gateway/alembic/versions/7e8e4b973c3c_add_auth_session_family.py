"""Add refresh token family tracking columns."""
from __future__ import annotations

import sys
import uuid
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

revision = "7e8e4b973c3c"
down_revision = "c7f96b8e4e7c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    columns = {
        column["name"]: column
        for column in inspector.get_columns("auth_sessions", schema=SCHEMA)
    }
    indexes = {
        index["name"]
        for index in inspector.get_indexes("auth_sessions", schema=SCHEMA)
    }
    foreign_keys = {
        fk["name"]: fk
        for fk in inspector.get_foreign_keys("auth_sessions", schema=SCHEMA)
    }

    if "family_id" not in columns:
        op.add_column(
            "auth_sessions",
            sa.Column("family_id", sa.String(length=36), nullable=True),
            schema=SCHEMA,
        )

    if "parent_session_id" not in columns:
        op.add_column(
            "auth_sessions",
            sa.Column("parent_session_id", sa.Integer(), nullable=True),
            schema=SCHEMA,
        )

    if "ix_auth_sessions_family_id" not in indexes:
        op.create_index(
            "ix_auth_sessions_family_id",
            "auth_sessions",
            ["family_id"],
            unique=False,
            schema=SCHEMA,
        )

    fk_name = op.f("fk_auth_sessions_parent_session_id_auth_sessions")
    if fk_name not in foreign_keys:
        op.create_foreign_key(
            fk_name,
            "auth_sessions",
            "auth_sessions",
            local_cols=["parent_session_id"],
            remote_cols=["id"],
            ondelete="CASCADE",
            source_schema=SCHEMA,
            referent_schema=SCHEMA,
        )

    auth_sessions = sa.table(
        "auth_sessions",
        sa.column("id", sa.Integer()),
        sa.column("family_id", sa.String(length=36)),
        schema=SCHEMA,
    )

    rows = bind.execute(
        sa.select(auth_sessions.c.id).where(auth_sessions.c.family_id.is_(None))
    ).fetchall()
    for (session_id,) in rows:
        bind.execute(
            sa.update(auth_sessions)
            .where(auth_sessions.c.id == session_id)
            .values(family_id=str(uuid.uuid4()))
        )

    op.alter_column(
        "auth_sessions",
        "family_id",
        existing_type=sa.String(length=36),
        nullable=False,
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_auth_sessions_parent_session_id_auth_sessions"),
        "auth_sessions",
        schema=SCHEMA,
        type_="foreignkey",
    )
    op.drop_index(
        "ix_auth_sessions_family_id",
        table_name="auth_sessions",
        schema=SCHEMA,
    )
    op.drop_column("auth_sessions", "parent_session_id", schema=SCHEMA)
    op.drop_column("auth_sessions", "family_id", schema=SCHEMA)
