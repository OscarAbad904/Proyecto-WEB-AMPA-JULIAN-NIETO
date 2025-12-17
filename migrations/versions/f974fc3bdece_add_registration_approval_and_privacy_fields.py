"""Add registration approval and privacy audit fields to users.

Revision ID: f974fc3bdece
Revises: 2f2a8e3d9c01
Create Date: 2025-12-17 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "f974fc3bdece"
down_revision = "2f2a8e3d9c01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "registration_approved",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column("users", sa.Column("privacy_accepted_at", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("privacy_version", sa.String(length=32), nullable=True))
    op.add_column("users", sa.Column("approved_at", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("approved_by_id", sa.Integer(), nullable=True))

    op.create_index(
        "ix_users_registration_approved",
        "users",
        ["registration_approved"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_users_approved_by_id_users",
        "users",
        "users",
        ["approved_by_id"],
        ["id"],
    )

    # Mantener compatibilidad con instalaciones existentes: todos los usuarios previos
    # se consideran "aprobados" para no bloquear el acceso tras activar este flujo.
    op.execute(sa.text("UPDATE users SET registration_approved = true"))


def downgrade() -> None:
    op.drop_constraint("fk_users_approved_by_id_users", "users", type_="foreignkey")
    op.drop_index("ix_users_registration_approved", table_name="users")
    op.drop_column("users", "approved_by_id")
    op.drop_column("users", "approved_at")
    op.drop_column("users", "privacy_version")
    op.drop_column("users", "privacy_accepted_at")
    op.drop_column("users", "registration_approved")

