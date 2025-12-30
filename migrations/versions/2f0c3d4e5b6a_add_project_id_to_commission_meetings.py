"""add project_id to commission_meetings

Revision ID: 2f0c3d4e5b6a
Revises: 1db393e78336
Create Date: 2026-01-02 00:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = "2f0c3d4e5b6a"
down_revision = "1db393e78336"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("commission_meetings", schema=None) as batch_op:
        batch_op.add_column(sa.Column("project_id", sa.Integer(), nullable=True))
        batch_op.create_index(
            batch_op.f("ix_commission_meetings_project_id"),
            ["project_id"],
            unique=False,
        )
        batch_op.create_foreign_key(
            "fk_commission_meetings_project_id",
            "commission_projects",
            ["project_id"],
            ["id"],
        )


def downgrade():
    with op.batch_alter_table("commission_meetings", schema=None) as batch_op:
        batch_op.drop_constraint("fk_commission_meetings_project_id", type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_commission_meetings_project_id"))
        batch_op.drop_column("project_id")
