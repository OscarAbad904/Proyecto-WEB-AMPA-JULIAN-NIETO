"""Añade datos de perfil y bandera de 2FA para usuarios."""

from alembic import op
import sqlalchemy as sa


revision = "0002_member_profile_and_twofa"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("first_name", sa.String(length=64)))
    op.add_column("users", sa.Column("last_name", sa.String(length=64)))
    op.add_column("users", sa.Column("phone_number", sa.String(length=32)))
    op.add_column("users", sa.Column("address", sa.String(length=255)))
    op.add_column("users", sa.Column("city", sa.String(length=128)))
    op.add_column("users", sa.Column("postal_code", sa.String(length=10)))
    op.add_column(
        "users",
        sa.Column(
            "two_fa_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index(op.f("ix_users_phone_number"), "users", ["phone_number"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_users_phone_number"), table_name="users")
    op.drop_column("users", "two_fa_enabled")
    op.drop_column("users", "postal_code")
    op.drop_column("users", "city")
    op.drop_column("users", "address")
    op.drop_column("users", "phone_number")
    op.drop_column("users", "last_name")
    op.drop_column("users", "first_name")
