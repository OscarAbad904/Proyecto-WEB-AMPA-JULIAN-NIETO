"""add user seen items

Revision ID: 3a9b1c2d3e4f
Revises: 1db393e78336
Create Date: 2026-01-01

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "3a9b1c2d3e4f"
down_revision = "1db393e78336"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "user_seen_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("item_type", sa.String(length=16), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("seen_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "item_type", "item_id", name="uq_user_seen_items"),
    )
    with op.batch_alter_table("user_seen_items", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_user_seen_items_user_id"), ["user_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_user_seen_items_item_type"), ["item_type"], unique=False)
        batch_op.create_index(batch_op.f("ix_user_seen_items_item_id"), ["item_id"], unique=False)


def downgrade():
    with op.batch_alter_table("user_seen_items", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_user_seen_items_item_id"))
        batch_op.drop_index(batch_op.f("ix_user_seen_items_item_type"))
        batch_op.drop_index(batch_op.f("ix_user_seen_items_user_id"))
    op.drop_table("user_seen_items")
