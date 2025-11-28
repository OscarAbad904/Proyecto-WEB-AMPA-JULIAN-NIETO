"""Add featured position to posts

Revision ID: d09c3b1d2f87
Revises: f7f1a9c2e1c4
Create Date: 2025-11-29 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "d09c3b1d2f87"
down_revision = "f7f1a9c2e1c4"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("posts", sa.Column("featured_position", sa.Integer(), nullable=True))
    op.create_index(op.f("ix_posts_featured_position"), "posts", ["featured_position"], unique=False)


def downgrade():
    with op.batch_alter_table("posts") as batch_op:
        batch_op.drop_index(batch_op.f("ix_posts_featured_position"))
        batch_op.drop_column("featured_position")
