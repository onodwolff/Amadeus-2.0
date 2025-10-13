"""Set non-admin default for the users.is_admin flag."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import column, table

try:  # pragma: no cover - support running from backend/
    from gateway.config import settings
except ModuleNotFoundError:  # pragma: no cover - support running from backend/
    from backend.gateway.config import settings  # type: ignore


# revision identifiers, used by Alembic.
revision = "0005_user_is_admin_default"
down_revision = "0004_auth_users"
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
    op.alter_column(
        "users",
        "is_admin",
        existing_type=sa.Boolean(),
        nullable=False,
        server_default=sa.false(),
    )

    users = table(
        "users",
        column("is_admin", sa.Boolean()),
        column("role", USER_ROLE),
    )

    admin_role = sa.cast(sa.literal("admin"), USER_ROLE)
    op.execute(users.update().where(users.c.role != admin_role).values(is_admin=False))


def downgrade() -> None:
    users = table(
        "users",
        column("is_admin", sa.Boolean()),
    )

    op.execute(users.update().values(is_admin=True))

    op.alter_column(
        "users",
        "is_admin",
        existing_type=sa.Boolean(),
        nullable=False,
        server_default=sa.true(),
    )
