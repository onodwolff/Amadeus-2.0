"""Ensure admin flag and role remain consistent."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import column, table


# revision identifiers, used by Alembic.
revision = "0006_users_admin_consistency"
down_revision = "0005_user_is_admin_default"
branch_labels = None
depends_on = None


def upgrade() -> None:
    users = table(
        "users",
        column("role", sa.String()),
        column("is_admin", sa.Boolean()),
    )

    op.execute(users.update().where(users.c.is_admin.is_(True)).values(role="ADMIN"))
    op.execute(
        users.update()
        .where(users.c.is_admin.is_(False))
        .where(users.c.role == "ADMIN")
        .values(role="MEMBER")
    )

    op.alter_column(
        "users",
        "is_admin",
        existing_type=sa.Boolean(),
        nullable=False,
        server_default=sa.false(),
    )

    op.create_check_constraint(
        "ck_users_admin_consistency",
        "users",
        "(is_admin AND role = 'ADMIN') OR (NOT is_admin AND role <> 'ADMIN')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_admin_consistency", "users", type_="check")

    users = table(
        "users",
        column("role", sa.String()),
        column("is_admin", sa.Boolean()),
    )

    op.execute(users.update().where(users.c.role == "ADMIN").values(is_admin=True))

    op.alter_column(
        "users",
        "is_admin",
        existing_type=sa.Boolean(),
        nullable=False,
        server_default=sa.true(),
    )
