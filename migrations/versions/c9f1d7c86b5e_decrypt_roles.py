"""Decrypt role names and keep them in plaintext.

Revision ID: c9f1d7c86b5e
Revises: b4add3d00a10
Create Date: 2025-12-11 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text

from config import decrypt_value


revision = "c9f1d7c86b5e"
down_revision = "b4add3d00a10"
branch_labels = None
depends_on = None


def _decrypt_role_name(value: str | None) -> str:
    """Ensure we keep the decrypted name, falling back to the stored value on failure."""
    if not value:
        return ""
    try:
        decrypted = decrypt_value(value)
        return decrypted or value
    except Exception:
        return value


def upgrade() -> None:
    connection = op.get_bind()
    rows = connection.execute(text("SELECT id, name FROM roles")).fetchall()
    for role_id, encrypted_name in rows:
        if encrypted_name is None:
            continue
        decrypted_name = _decrypt_role_name(encrypted_name)
        connection.execute(
            text(
                "UPDATE roles SET name = :name WHERE id = :role_id"
            ),
            {"role_id": role_id, "name": decrypted_name},
        )

    op.alter_column(
        "roles",
        "name",
        existing_type=sa.Text(),
        type_=sa.String(length=64),
        nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "roles",
        "name",
        existing_type=sa.String(length=64),
        type_=sa.Text(),
        nullable=False,
    )
