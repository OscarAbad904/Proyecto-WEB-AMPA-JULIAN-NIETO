"""add image_variants to posts

Revision ID: f7f1a9c2e1c4
Revises: 85389f93bec9
Create Date: 2025-11-26 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f7f1a9c2e1c4"
down_revision = "85389f93bec9"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("posts", sa.Column("image_variants", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("posts", "image_variants")
