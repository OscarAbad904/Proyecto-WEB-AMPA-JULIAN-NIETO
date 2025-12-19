"""Add deleted_at to users for soft deletion.

Revision ID: a13b7c9d2e4f
Revises: f974fc3bdece
Create Date: 2025-12-19 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "a13b7c9d2e4f"
down_revision = "f974fc3bdece"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("deleted_at", sa.DateTime(), nullable=True))
    op.create_index("ix_users_deleted_at", "users", ["deleted_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_users_deleted_at", table_name="users")
    op.drop_column("users", "deleted_at")

