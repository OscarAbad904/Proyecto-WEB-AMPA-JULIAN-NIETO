"""Resequence core role IDs to a stable numbering.

After normalizing and deduplicating roles, the remaining rows can have IDs far
from the desired small range. This migration assigns the following IDs:

1  Administrador
2  Presidencia
3  Vicepresidencia
4  Secretaría
5  Vicesecretaría
6  Tesorería
7  Vicetesorería
8  Vocal
9  Socio

It creates new role rows with the target IDs, updates foreign keys in `users`
and `role_permissions`, then deletes the old role rows.

Revision ID: 7b2a0d3fb1f1
Revises: df3a61b8a4c2
Create Date: 2025-12-13 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
from sqlalchemy.sql import text

from config import decrypt_value


revision = "7b2a0d3fb1f1"
down_revision = "df3a61b8a4c2"
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


def _normalize(value: str | None) -> str:
    return (value or "").strip().lower()


def upgrade() -> None:
    connection = op.get_bind()

    # Guard: avoid attempting to reuse IDs that are already occupied.
    occupied = connection.execute(
        text("SELECT id, name, name_lookup FROM roles WHERE id BETWEEN 1 AND 9 ORDER BY id")
    ).fetchall()
    if occupied:
        occupied_str = ", ".join(f"{row[0]}:{row[2]}" for row in occupied)
        raise RuntimeError(
            "No se puede re-secuenciar roles porque ya existen IDs 1..9 en roles: "
            + occupied_str
        )

    desired = [
        ("administrador", 1),
        ("presidencia", 2),
        ("vicepresidencia", 3),
        ("secretaría", 4),
        ("vicesecretaría", 5),
        ("tesorería", 6),
        ("vicetesorería", 7),
        ("vocal", 8),
        ("socio", 9),
    ]
    desired_keys = {key for key, _id in desired}

    rows = connection.execute(text("SELECT id, name, name_lookup FROM roles")).fetchall()
    by_key: dict[str, list[tuple[int, str, str]]] = {}
    for role_id, name, name_lookup in rows:
        decrypted_name = _decrypt_if_needed(name)
        key = _normalize(decrypted_name)
        by_key.setdefault(key, []).append((int(role_id), decrypted_name, name_lookup))

    # Ensure required roles exist (by normalized name).
    missing = [key for key in desired_keys if key not in by_key]
    if missing:
        raise RuntimeError(
            "Faltan roles necesarios para re-secuenciar IDs: " + ", ".join(sorted(missing))
        )

    # Step 1: free unique constraint on name_lookup by assigning placeholders to old rows.
    for key, _new_id in desired:
        candidates = by_key.get(key, [])
        # Prefer the row that already has the correct lookup value.
        candidates_sorted = sorted(
            candidates,
            key=lambda item: (0 if (item[2] or "") == key else 1, item[0]),
        )
        old_id, _name, _lookup = candidates_sorted[0]
        placeholder = f"__old__{old_id}"
        connection.execute(
            text("UPDATE roles SET name_lookup = :placeholder WHERE id = :id"),
            {"id": old_id, "placeholder": placeholder},
        )

    # Step 2: create new role rows with the desired IDs and lookups.
    for key, new_id in desired:
        candidates = by_key.get(key, [])
        candidates_sorted = sorted(
            candidates,
            key=lambda item: (0 if (item[2] or "") == key else 1, item[0]),
        )
        old_id, name, _lookup = candidates_sorted[0]

        connection.execute(
            text("INSERT INTO roles (id, name, name_lookup) VALUES (:id, :name, :lookup)"),
            {"id": new_id, "name": name, "lookup": key},
        )

        # Update foreign keys to point to the new role id.
        connection.execute(
            text("UPDATE users SET role_id = :new WHERE role_id = :old"),
            {"new": new_id, "old": old_id},
        )
        connection.execute(
            text("UPDATE role_permissions SET role_id = :new WHERE role_id = :old"),
            {"new": new_id, "old": old_id},
        )

        # Delete the old role row.
        connection.execute(text("DELETE FROM roles WHERE id = :old"), {"old": old_id})

    # Step 3: keep roles.id sequence in sync (if any).
    seq = connection.execute(
        text("SELECT pg_get_serial_sequence('roles', 'id') AS seq")
    ).scalar()
    if seq:
        connection.execute(
            text("SELECT setval(:seq, (SELECT MAX(id) FROM roles), true)"),
            {"seq": seq},
        )


def downgrade() -> None:
    # Not reversible: restoring previous IDs would require storing the old mapping.
    pass
