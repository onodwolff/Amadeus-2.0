"""Add MFA support structures."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "8d8c8cfa3f42"
down_revision = "3bd5b0e1f5a5"
branch_labels = None
depends_on = None


_OLD_USER_TOKEN_PURPOSE = ("password_reset", "email_verification")
_NEW_USER_TOKEN_PURPOSE = _OLD_USER_TOKEN_PURPOSE + ("mfa_challenge",)


def _enum_type(values: tuple[str, ...]) -> sa.Enum:
    return sa.Enum(*values, name="user_token_purpose", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {
        column["name"] for column in inspector.get_columns("auth_sessions")
    }

    if bind.dialect.name == "postgresql":
        op.execute("ALTER TYPE user_token_purpose ADD VALUE IF NOT EXISTS 'mfa_challenge'")

    with op.batch_alter_table("user_tokens") as batch_op:
        batch_op.alter_column(
            "purpose",
            existing_type=_enum_type(_OLD_USER_TOKEN_PURPOSE),
            type_=_enum_type(_NEW_USER_TOKEN_PURPOSE),
            existing_nullable=False,
        )

    op.create_table(
        "user_mfa_backup_codes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("code_hash", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code_hash", name="uq_user_mfa_backup_codes_hash"),
    )
    op.create_index(
        op.f("ix_user_mfa_backup_codes_user_id"),
        "user_mfa_backup_codes",
        ["user_id"],
    )

    with op.batch_alter_table("auth_sessions") as batch_op:
        if "mfa_verified_at" not in existing_columns:
            batch_op.add_column(
                sa.Column("mfa_verified_at", sa.DateTime(timezone=True), nullable=True)
            )
        if "mfa_method" not in existing_columns:
            batch_op.add_column(sa.Column("mfa_method", sa.String(length=32), nullable=True))
        if "mfa_remember_device" not in existing_columns:
            batch_op.add_column(
                sa.Column(
                    "mfa_remember_device",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.text("false"),
                )
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {
        column["name"] for column in inspector.get_columns("auth_sessions")
    }

    with op.batch_alter_table("auth_sessions") as batch_op:
        if "mfa_remember_device" in existing_columns:
            batch_op.drop_column("mfa_remember_device")
        if "mfa_method" in existing_columns:
            batch_op.drop_column("mfa_method")
        if "mfa_verified_at" in existing_columns:
            batch_op.drop_column("mfa_verified_at")

    op.drop_index(op.f("ix_user_mfa_backup_codes_user_id"), table_name="user_mfa_backup_codes")
    op.drop_table("user_mfa_backup_codes")

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        temp_enum = sa.Enum(*_OLD_USER_TOKEN_PURPOSE, name="user_token_purpose_old")
        temp_enum.create(bind, checkfirst=False)

        op.execute(
            "ALTER TABLE user_tokens ALTER COLUMN purpose TYPE user_token_purpose_old USING purpose::text::user_token_purpose_old"
        )
        op.execute("DROP TYPE user_token_purpose")
        op.execute("ALTER TYPE user_token_purpose_old RENAME TO user_token_purpose")
    else:
        with op.batch_alter_table("user_tokens") as batch_op:
            batch_op.alter_column(
                "purpose",
                existing_type=_enum_type(_NEW_USER_TOKEN_PURPOSE),
                type_=_enum_type(_OLD_USER_TOKEN_PURPOSE),
                existing_nullable=False,
            )
