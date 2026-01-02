"""add google_event_id to events

Revision ID: e8b1c2d3e4f5
Revises: cda65ecd4c01
Create Date: 2026-01-02

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e8b1c2d3e4f5"
down_revision = "cda65ecd4c01"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("events") as batch_op:
        batch_op.add_column(sa.Column("google_event_id", sa.String(length=255), nullable=True))


def downgrade():
    with op.batch_alter_table("events") as batch_op:
        batch_op.drop_column("google_event_id")
