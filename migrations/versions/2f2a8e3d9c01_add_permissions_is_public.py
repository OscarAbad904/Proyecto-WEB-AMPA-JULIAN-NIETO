"""Add is_public flag to permissions.

Revision ID: 2f2a8e3d9c01
Revises: 7b2a0d3fb1f1
Create Date: 2025-12-16 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "2f2a8e3d9c01"
down_revision = "7b2a0d3fb1f1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "permissions",
        sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_permissions_is_public", "permissions", ["is_public"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_permissions_is_public", table_name="permissions")
    op.drop_column("permissions", "is_public")

