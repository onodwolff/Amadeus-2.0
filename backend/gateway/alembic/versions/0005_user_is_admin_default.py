"""Set non-admin default for the users.is_admin flag."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import column, table


# revision identifiers, used by Alembic.
revision = "0005_user_is_admin_default"
down_revision = "0004_auth_users"
branch_labels = None
depends_on = None


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
        column("role", sa.String()),
    )

    op.execute(
        users.update().where(users.c.role != "admin").values(is_admin=False)
    )


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
