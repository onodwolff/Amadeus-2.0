"""Initial gateway schema focusing on user accounts."""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import ProgrammingError

revision = "3b22559a4dcc"
down_revision = "0006_users_admin_consistency"
branch_labels = None
depends_on = None


def _is_postgres(bind) -> bool:
    return bind.dialect.name == "postgresql"


def _ensure_extension(bind, name: str) -> None:
    if not _is_postgres(bind):
        return

    try:
        bind.exec_driver_sql(f"CREATE EXTENSION IF NOT EXISTS {name}")
    except ProgrammingError as exc:  # pragma: no cover - depends on privileges
        if getattr(getattr(exc, "orig", None), "pgcode", None) != "42501":
            raise


def upgrade() -> None:
    bind = op.get_bind()
    _ensure_extension(bind, "citext")

    email_type: sa.TypeEngine = (
        postgresql.CITEXT() if _is_postgres(bind) else sa.String(length=320)
    )

    if _is_postgres(bind):
        role_enum = postgresql.ENUM(
            "admin",
            "member",
            "viewer",
            name="user_role",
            create_type=False,
        )
        role_enum.create(bind, checkfirst=True)
    else:
        role_enum = sa.Enum("admin", "member", "viewer", name="user_role")

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("email", email_type, nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("pwd_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "role",
            role_enum,
            nullable=False,
            server_default=sa.text("'member'"),
        ),
        sa.Column(
            "is_admin",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "email_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "mfa_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("mfa_secret", sa.Text(), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
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
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.UniqueConstraint("username", name="uq_users_username"),
        sa.CheckConstraint(
            "(is_admin AND role = 'admin') OR (NOT is_admin AND role <> 'admin')",
            name="ck_users_admin_consistency",
        ),
    )

def downgrade() -> None:
    op.drop_table("users")

    bind = op.get_bind()
    if _is_postgres(bind):
        bind.exec_driver_sql("DROP EXTENSION IF EXISTS citext")
