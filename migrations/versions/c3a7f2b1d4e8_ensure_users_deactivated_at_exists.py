"""Ensure users.deactivated_at exists (safe).

Revision ID: c3a7f2b1d4e8
Revises: 6c8d1a2f3b4c
Create Date: 2026-01-03

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c3a7f2b1d4e8"
down_revision = "6c8d1a2f3b4c"
branch_labels = None
depends_on = None


def _has_column(bind, table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(bind)
    try:
        cols = inspector.get_columns(table_name)
    except Exception:
        return False
    return any((c.get("name") or "").lower() == column_name.lower() for c in cols)


def upgrade():
    bind = op.get_bind()
    if not _has_column(bind, "users", "deactivated_at"):
        op.add_column("users", sa.Column("deactivated_at", sa.DateTime(), nullable=True))


def downgrade():
    bind = op.get_bind()
    if _has_column(bind, "users", "deactivated_at"):
        op.drop_column("users", "deactivated_at")
