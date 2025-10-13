"""Add authentication support fields and tables."""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import ProgrammingError


def _has_citext_extension(bind) -> bool:
    if not _is_postgres(bind):
        return False

    result = bind.exec_driver_sql(
        "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'citext')"
    )
    return bool(result.scalar())


def _is_postgres(bind) -> bool:
    return bind.dialect.name == "postgresql"


def _ensure_citext_extension(bind) -> bool:
    if not _is_postgres(bind):
        return False

    if _has_citext_extension(bind):
        return True

    try:
        bind.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS citext")
    except ProgrammingError as exc:  # pragma: no cover - depends on database privs
        if getattr(getattr(exc, "orig", None), "pgcode", None) != "42501":
            raise
    return _has_citext_extension(bind)

# revision identifiers, used by Alembic.
revision = "0004_auth_users"
down_revision = "0003_strategy_tester"
branch_labels = None
depends_on = None
def upgrade() -> None:
    bind = op.get_bind()
    citext_available = _ensure_citext_extension(bind)

    if citext_available:
        op.alter_column(
            "users",
            "email",
            type_=postgresql.CITEXT(),
            existing_type=sa.String(length=320),
            existing_nullable=False,
        )

    op.add_column(
        "users",
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "users",
        sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "users",
        sa.Column("mfa_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("users", sa.Column("mfa_secret", sa.Text(), nullable=True))
    op.add_column(
        "users",
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
    )

    new_email_type = (
        postgresql.CITEXT() if citext_available else sa.String(length=320)
    )
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("refresh_token_hash", sa.String(length=128), nullable=False),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("refresh_token_hash", name="uq_auth_sessions_refresh_token_hash"),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])

    op.create_table(
        "email_change_requests",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("new_email", new_email_type, nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("token_hash", name="uq_email_change_requests_token_hash"),
    )
    op.create_index(
        "ix_email_change_requests_user_id",
        "email_change_requests",
        ["user_id"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    citext_available = _has_citext_extension(bind)

    op.drop_index("ix_email_change_requests_user_id", table_name="email_change_requests")
    op.drop_table("email_change_requests")

    op.drop_index("ix_auth_sessions_expires_at", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_user_id", table_name="auth_sessions")
    op.drop_table("auth_sessions")

    op.drop_column("users", "last_login_at")
    op.drop_column("users", "mfa_secret")
    op.drop_column("users", "mfa_enabled")
    op.drop_column("users", "email_verified")
    op.drop_column("users", "is_admin")

    if citext_available:
        op.alter_column(
            "users",
            "email",
            type_=sa.String(length=320),
            existing_type=postgresql.CITEXT(),
            existing_nullable=False,
        )

    if _is_postgres(bind):
        bind.exec_driver_sql("DROP EXTENSION IF EXISTS citext")
