"""add poll description and files

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-01-06 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e2f3a4b5c6d7"
down_revision = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("discussion_polls", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("discussion_polls", sa.Column("drive_file_ids", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("discussion_polls", "drive_file_ids")
    op.drop_column("discussion_polls", "description")
