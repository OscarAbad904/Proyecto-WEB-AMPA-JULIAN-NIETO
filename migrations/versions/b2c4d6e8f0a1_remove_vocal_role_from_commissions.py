"""Remove 'vocal' role from commission memberships.

Revision ID: b2c4d6e8f0a1
Revises: a13b7c9d2e4f
Create Date: 2025-12-19 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "b2c4d6e8f0a1"
down_revision = "a13b7c9d2e4f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE commission_memberships SET role = 'miembro' WHERE lower(role) = 'vocal'"
        )
    )


def downgrade() -> None:
    # No reversible sin pérdida de intención original; dejamos como 'miembro'.
    pass

