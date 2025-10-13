"""Ensure admin flag and role remain consistent."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import column, table

try:  # pragma: no cover - support running from backend/
    from gateway.config import settings
except ModuleNotFoundError:  # pragma: no cover - support running from backend/
    from backend.gateway.config import settings  # type: ignore


# revision identifiers, used by Alembic.
revision = "0006_users_admin_consistency"
down_revision = "0005_user_is_admin_default"
branch_labels = None
depends_on = None


SCHEMA = settings.storage.schema

USER_ROLE = sa.Enum(
    "admin",
    "member",
    "viewer",
    name="user_role",
    schema=SCHEMA,
)
USER_ROLE.create_type = False


def upgrade() -> None:
    users = table(
        "users",
        column("role", USER_ROLE),
        column("is_admin", sa.Boolean()),
    )

    admin_role = sa.cast(sa.literal("admin"), USER_ROLE)
    member_role = sa.cast(sa.literal("member"), USER_ROLE)

    op.execute(users.update().where(users.c.is_admin.is_(True)).values(role=admin_role))
    op.execute(
        users.update()
        .where(users.c.is_admin.is_(False))
        .where(users.c.role == admin_role)
        .values(role=member_role)
    )

    op.alter_column(
        "users",
        "is_admin",
        existing_type=sa.Boolean(),
        nullable=False,
        server_default=sa.false(),
    )

    escaped_schema = SCHEMA.replace('"', '""') if SCHEMA else "public"
    enum_type = f'"{escaped_schema}"."user_role"' if SCHEMA else 'user_role'
    constraint = (
        f"(is_admin AND role = 'admin'::{enum_type}) "
        f"OR (NOT is_admin AND role <> 'admin'::{enum_type})"
    )

    op.create_check_constraint("ck_users_admin_consistency", "users", constraint)


def downgrade() -> None:
    op.drop_constraint("ck_users_admin_consistency", "users", type_="check")

    users = table(
        "users",
        column("role", USER_ROLE),
        column("is_admin", sa.Boolean()),
    )

    admin_role = sa.cast(sa.literal("admin"), USER_ROLE)
    op.execute(users.update().where(users.c.role == admin_role).values(is_admin=True))

    op.alter_column(
        "users",
        "is_admin",
        existing_type=sa.Boolean(),
        nullable=False,
        server_default=sa.true(),
    )
