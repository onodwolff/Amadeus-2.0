"""add user tokens table

Revision ID: 3bd5b0e1f5a5
Revises: 7e8e4b973c3c
Create Date: 2024-05-15 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "3bd5b0e1f5a5"
down_revision = "7e8e4b973c3c"
branch_labels = None
depends_on = None


user_token_purpose = sa.Enum(
    "password_reset",
    "email_verification",
    name="user_token_purpose",
)


def upgrade() -> None:
    op.create_table(
        "user_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("purpose", user_token_purpose, nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_user_tokens_hash"),
    )
    op.create_index(
        "ix_user_tokens_user_purpose",
        "user_tokens",
        ["user_id", "purpose", "consumed_at"],
    )



def downgrade() -> None:
    op.drop_index("ix_user_tokens_user_purpose", table_name="user_tokens")
    op.drop_table("user_tokens")
    user_token_purpose.drop(op.get_bind(), checkfirst=False)
