"""add user tokens table.

Revision ID: 3bd5b0e1f5a5
Revises: 7e8e4b973c3c
Create Date: 2024-05-15 00:00:00.000000
"""

from __future__ import annotations

import sys
from pathlib import Path

import sqlalchemy as sa
from alembic import op
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
revision = "3bd5b0e1f5a5"
down_revision = "7e8e4b973c3c"
branch_labels = None
depends_on = None


user_token_purpose = postgresql.ENUM(
    "password_reset",
    "email_verification",
    name="user_token_purpose",
    schema=SCHEMA,
    create_type=False,
)


def upgrade() -> None:
    schema = SCHEMA or "public"

    op.execute(
        f"""
    DO $$
    BEGIN
      IF NOT EXISTS (
        SELECT 1 FROM pg_type t
        JOIN pg_namespace n ON n.oid = t.typnamespace
        WHERE t.typname = 'user_token_purpose' AND n.nspname = '{schema}'
      ) THEN
        CREATE TYPE {schema}.user_token_purpose AS ENUM ('password_reset', 'email_verification');
      END IF;
    END$$;
    """
    )

    op.execute(
        f"""
    ALTER TYPE {schema}.user_token_purpose ADD VALUE IF NOT EXISTS 'password_reset';
    ALTER TYPE {schema}.user_token_purpose ADD VALUE IF NOT EXISTS 'email_verification';
    """
    )

    op.create_table(
        "user_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("purpose", user_token_purpose, nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_user_tokens_hash"),
        schema=SCHEMA,
    )
    op.create_foreign_key(
        "fk_user_tokens_user_id_users",
        "user_tokens",
        "users",
        ["user_id"],
        ["id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_user_tokens_user_purpose",
        "user_tokens",
        ["user_id", "purpose", "consumed_at"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_user_tokens_user_id_users",
        "user_tokens",
        type_="foreignkey",
        schema=SCHEMA,
    )
    op.drop_index(
        "ix_user_tokens_user_purpose",
        table_name="user_tokens",
        schema=SCHEMA,
    )
    op.drop_table("user_tokens", schema=SCHEMA)
