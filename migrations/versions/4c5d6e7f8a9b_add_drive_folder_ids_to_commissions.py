"""add drive folder ids to commissions and projects

Revision ID: 4c5d6e7f8a9b
Revises: 9f8e7d6c5b4a
Create Date: 2026-02-01
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "4c5d6e7f8a9b"
down_revision = "9f8e7d6c5b4a"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("commissions", sa.Column("drive_folder_id", sa.String(length=255), nullable=True))
    op.add_column("commission_projects", sa.Column("drive_folder_id", sa.String(length=255), nullable=True))


def downgrade():
    op.drop_column("commission_projects", "drive_folder_id")
    op.drop_column("commissions", "drive_folder_id")
