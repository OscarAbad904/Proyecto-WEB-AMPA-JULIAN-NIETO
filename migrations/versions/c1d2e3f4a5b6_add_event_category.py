"""Add category to events

Revision ID: c1d2e3f4a5b6
Revises: d09c3b1d2f87
Create Date: 2025-12-01 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "c1d2e3f4a5b6"
down_revision = "d09c3b1d2f87"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "events",
        sa.Column("category", sa.String(length=64), nullable=True),
    )


def downgrade():
    op.drop_column("events", "category")
