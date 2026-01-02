"""add image_variants to events

Revision ID: e9c2d3e4f5a6
Revises: e8b1c2d3e4f5
Create Date: 2026-01-02

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e9c2d3e4f5a6"
down_revision = "e8b1c2d3e4f5"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("events", sa.Column("image_variants", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("events", "image_variants")
