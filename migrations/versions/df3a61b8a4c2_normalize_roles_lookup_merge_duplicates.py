"""Normalize roles.name_lookup to plaintext and merge duplicates.

This project originally stored `roles.name_lookup` as a SHA-256 hash (via
`make_lookup_hash`). The new behavior uses a readable, normalized lookup
(lowercased role name). After switching behavior, existing hashed rows can
coexist with newly-created normalized rows, creating duplicates by `name`.

This migration:
- decrypts `roles.name` when still Fernet-wrapped
- sets `roles.name_lookup` = normalized(name)
- merges duplicate roles that collapse to the same normalized lookup, reassigning
  users and role_permissions safely.

Revision ID: df3a61b8a4c2
Revises: c9f1d7c86b5e
Create Date: 2025-12-13 00:00:00.000000
"""

from __future__ import annotations

from collections import defaultdict

from alembic import op
from sqlalchemy.sql import text

from app.utils import normalize_lookup
from config import decrypt_value


revision = "df3a61b8a4c2"
down_revision = "c9f1d7c86b5e"
branch_labels = None
depends_on = None


def _decrypt_if_needed(value: str | None) -> str:
    if not value:
        return ""
    try:
        decrypted = decrypt_value(value)
        return decrypted or value
    except Exception:
        return value


def upgrade() -> None:
    connection = op.get_bind()

    rows = connection.execute(text("SELECT id, name, name_lookup FROM roles")).fetchall()
    by_normalized: dict[str, list[tuple[int, str, str | None]]] = defaultdict(list)

    for role_id, name, name_lookup in rows:
        decrypted_name = _decrypt_if_needed(name)
        normalized = normalize_lookup(decrypted_name)
        by_normalized[normalized].append((int(role_id), decrypted_name, name_lookup))

    # Process each normalized group: choose a keeper, merge others.
    for normalized, group in by_normalized.items():
        if not normalized:
            # Skip empty lookups; avoid breaking constraints. Operator can fix manually.
            continue

        # Prefer keeping the row already using the new normalized lookup.
        keep_id = None
        keep_name = None
        for role_id, decrypted_name, name_lookup in group:
            if (name_lookup or "") == normalized:
                keep_id = role_id
                keep_name = decrypted_name
                break
        if keep_id is None:
            # Otherwise keep the lowest id for stability.
            role_id, decrypted_name, _ = sorted(group, key=lambda item: item[0])[0]
            keep_id = role_id
            keep_name = decrypted_name

        # First, update the keeper's fields.
        connection.execute(
            text("UPDATE roles SET name = :name, name_lookup = :lookup WHERE id = :id"),
            {"id": keep_id, "name": keep_name, "lookup": normalized},
        )

        # Merge duplicates into keeper.
        for role_id, _decrypted_name, _name_lookup in group:
            if role_id == keep_id:
                continue

            # Reassign users
            connection.execute(
                text("UPDATE users SET role_id = :keep WHERE role_id = :dup"),
                {"keep": keep_id, "dup": role_id},
            )

            # For role_permissions, avoid unique collisions (role_id, permission_id).
            connection.execute(
                text(
                    """
                    DELETE FROM role_permissions rp
                    USING role_permissions rp_keep
                    WHERE rp.role_id = :dup
                      AND rp_keep.role_id = :keep
                      AND rp.permission_id = rp_keep.permission_id
                    """
                ),
                {"dup": role_id, "keep": keep_id},
            )
            connection.execute(
                text("UPDATE role_permissions SET role_id = :keep WHERE role_id = :dup"),
                {"keep": keep_id, "dup": role_id},
            )

            # Finally, delete duplicate role row.
            connection.execute(text("DELETE FROM roles WHERE id = :dup"), {"dup": role_id})

    # Normalize any remaining rows (including ones that didn't duplicate).
    remaining = connection.execute(text("SELECT id, name FROM roles")).fetchall()
    for role_id, name in remaining:
        decrypted_name = _decrypt_if_needed(name)
        normalized = normalize_lookup(decrypted_name)
        if not normalized:
            continue
        connection.execute(
            text("UPDATE roles SET name = :name, name_lookup = :lookup WHERE id = :id"),
            {"id": int(role_id), "name": decrypted_name, "lookup": normalized},
        )


def downgrade() -> None:
    # Not reversible: merging duplicates deletes rows.
    pass

