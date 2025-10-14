"""Ensure refresh token family tracking schema exists in all deployments."""
from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from backend.gateway.alembic.versions.c7f96b8e4e7c_initial_schema import SCHEMA


revision = "5e5c7f4d5b70"
down_revision = "43bed44187a2"
branch_labels = None
depends_on = None


_AUTH_SESSIONS_TABLE = "auth_sessions"
_FAMILY_ID_INDEX = "ix_auth_sessions_family_id"
_PARENT_SESSION_FK = op.f("fk_auth_sessions_parent_session_id_auth_sessions")
_AUDIT_EVENTS_TABLE = "audit_events"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    _ensure_auth_session_family_columns(bind, inspector)
    _ensure_audit_events_table(inspector)


def downgrade() -> None:  # pragma: no cover - irreversible fix
    """No automatic downgrade; the schema is kept intact."""


def _ensure_auth_session_family_columns(bind, inspector) -> None:
    columns = {column["name"]: column for column in inspector.get_columns(_AUTH_SESSIONS_TABLE, schema=SCHEMA)}
    indexes = {index["name"] for index in inspector.get_indexes(_AUTH_SESSIONS_TABLE, schema=SCHEMA)}
    foreign_keys = {fk["name"] for fk in inspector.get_foreign_keys(_AUTH_SESSIONS_TABLE, schema=SCHEMA)}

    family_column = columns.get("family_id")
    parent_column = columns.get("parent_session_id")

    if family_column is None:
        op.add_column(
            _AUTH_SESSIONS_TABLE,
            sa.Column("family_id", sa.String(length=36), nullable=True),
            schema=SCHEMA,
        )
    if parent_column is None:
        op.add_column(
            _AUTH_SESSIONS_TABLE,
            sa.Column("parent_session_id", sa.Integer(), nullable=True),
            schema=SCHEMA,
        )

    if _FAMILY_ID_INDEX not in indexes:
        op.create_index(
            _FAMILY_ID_INDEX,
            _AUTH_SESSIONS_TABLE,
            ["family_id"],
            unique=False,
            schema=SCHEMA,
        )

    if _PARENT_SESSION_FK not in foreign_keys:
        op.create_foreign_key(
            _PARENT_SESSION_FK,
            _AUTH_SESSIONS_TABLE,
            _AUTH_SESSIONS_TABLE,
            local_cols=["parent_session_id"],
            remote_cols=["id"],
            ondelete="CASCADE",
            source_schema=SCHEMA,
            referent_schema=SCHEMA,
        )

    auth_sessions = sa.table(
        _AUTH_SESSIONS_TABLE,
        sa.column("id", sa.Integer()),
        sa.column("family_id", sa.String(length=36)),
        schema=SCHEMA,
    )

    need_family_values = family_column is None or bool(family_column.get("nullable", True))
    if not need_family_values:
        null_count = bind.execute(
            sa.select(sa.func.count()).select_from(
                auth_sessions
            ).where(auth_sessions.c.family_id.is_(None))
        ).scalar()
        need_family_values = bool(null_count)

    if need_family_values:
        rows = bind.execute(
            sa.select(auth_sessions.c.id)
            .where(auth_sessions.c.family_id.is_(None))
            .order_by(auth_sessions.c.id)
        ).fetchall()
        for (session_id,) in rows:
            bind.execute(
                sa.update(auth_sessions)
                .where(auth_sessions.c.id == session_id)
                .values(family_id=str(uuid.uuid4()))
            )

        op.alter_column(
            _AUTH_SESSIONS_TABLE,
            "family_id",
            existing_type=sa.String(length=36),
            nullable=False,
            schema=SCHEMA,
        )


def _ensure_audit_events_table(inspector) -> None:
    if inspector.has_table(_AUDIT_EVENTS_TABLE, schema=SCHEMA):
        return

    op.create_table(
        _AUDIT_EVENTS_TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("result", sa.String(length=32), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("target_user_id", sa.Integer(), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            [f"{SCHEMA}.users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["target_user_id"],
            [f"{SCHEMA}.users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=SCHEMA,
    )

    op.create_index(
        op.f("ix_audit_events_action"),
        _AUDIT_EVENTS_TABLE,
        ["action"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_audit_events_action_occurred_at",
        _AUDIT_EVENTS_TABLE,
        ["action", "occurred_at"],
        schema=SCHEMA,
    )
    op.create_index(
        op.f("ix_audit_events_actor_user_id"),
        _AUDIT_EVENTS_TABLE,
        ["actor_user_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_audit_events_actor_occurred_at",
        _AUDIT_EVENTS_TABLE,
        ["actor_user_id", "occurred_at"],
        schema=SCHEMA,
    )
    op.create_index(
        op.f("ix_audit_events_occurred_at"),
        _AUDIT_EVENTS_TABLE,
        ["occurred_at"],
        schema=SCHEMA,
    )
    op.create_index(
        op.f("ix_audit_events_result"),
        _AUDIT_EVENTS_TABLE,
        ["result"],
        schema=SCHEMA,
    )
    op.create_index(
        op.f("ix_audit_events_target_user_id"),
        _AUDIT_EVENTS_TABLE,
        ["target_user_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_audit_events_target_occurred_at",
        _AUDIT_EVENTS_TABLE,
        ["target_user_id", "occurred_at"],
        schema=SCHEMA,
    )
