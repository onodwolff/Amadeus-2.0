"""Add persistent user active flag"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0007_user_active_flag"
down_revision = "0006_users_admin_consistency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.execute(sa.text("UPDATE users SET active = TRUE"))


def downgrade() -> None:
    op.drop_column("users", "active")
