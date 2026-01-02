"""merge heads drive and events

Revision ID: 5b7c9d0e1f2a
Revises: 4c5d6e7f8a9b, e9c2d3e4f5a6
Create Date: 2026-02-01
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "5b7c9d0e1f2a"
down_revision = ("4c5d6e7f8a9b", "e9c2d3e4f5a6")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
