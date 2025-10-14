"""Merge audit and user token heads

Revision ID: 43bed44187a2
Revises: 3bd5b0e1f5a5, 4ac08f7fba12
Create Date: 2024-08-13 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "43bed44187a2"
down_revision = ("3bd5b0e1f5a5", "4ac08f7fba12")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
