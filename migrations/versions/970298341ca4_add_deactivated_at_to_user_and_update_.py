"""Add deactivated_at to users (safe).

Revision ID: 970298341ca4
Revises: f974fc3bdece
Create Date: 2025-12-19 09:05:01.765528
"""

from alembic import op
import sqlalchemy as sa


revision = "970298341ca4"
down_revision = "f974fc3bdece"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "users" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("users")}
    if "deactivated_at" not in columns:
        op.add_column("users", sa.Column("deactivated_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "users" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("users")}
    if "deactivated_at" in columns:
        op.drop_column("users", "deactivated_at")

