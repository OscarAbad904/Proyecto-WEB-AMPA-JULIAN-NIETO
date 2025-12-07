"""Seed permisos base en español para noticias y eventos

Revision ID: b4add3d00a10
Revises: e6ad2c3f4b5a
Create Date: 2025-01-15 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
import hashlib


# revision identifiers, used by Alembic.
revision = "b4add3d00a10"
down_revision = "e6ad2c3f4b5a"
branch_labels = None
depends_on = None


def _make_lookup(value: str) -> str:
    normalized = (value or "").strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "permissions" not in inspector.get_table_names():
        return

    permission_table = sa.table(
        "permissions",
        sa.column("id", sa.Integer()),
        sa.column("key", sa.String()),
        sa.column("name", sa.String()),
        sa.column("description", sa.Text()),
    )
    role_permissions_table = sa.table(
        "role_permissions",
        sa.column("id", sa.Integer()),
        sa.column("role_id", sa.Integer()),
        sa.column("permission_id", sa.Integer()),
        sa.column("allowed", sa.Boolean()),
    )
    roles_table = sa.table(
        "roles",
        sa.column("id", sa.Integer()),
        sa.column("name_lookup", sa.String()),
    )

    new_permissions = [
        {
            "key": "manage_posts",
            "name": "Gestionar noticias",
            "description": "Crear, editar, publicar o eliminar noticias del tablón.",
        },
        {
            "key": "manage_events",
            "name": "Gestionar eventos",
            "description": "Crear, editar y programar eventos del calendario interno.",
        },
    ]

    existing_keys = {
        row.key for row in bind.execute(sa.select(permission_table.c.key)).fetchall()
    }
    to_insert = [p for p in new_permissions if p["key"] not in existing_keys]
    if to_insert:
        op.bulk_insert(permission_table, to_insert)

    # refrescar ids tras posibles inserts
    perm_rows = bind.execute(sa.select(permission_table.c.id, permission_table.c.key)).fetchall()
    perm_by_key = {row.key: row.id for row in perm_rows}

    admin_lookups = {_make_lookup("admin"), _make_lookup("administrador")}
    role_rows = (
        bind.execute(
            sa.select(roles_table.c.id, roles_table.c.name_lookup).where(
                roles_table.c.name_lookup.in_(admin_lookups)
            )
        ).fetchall()
        if "roles" in inspector.get_table_names()
        else []
    )

    if "role_permissions" in inspector.get_table_names() and role_rows:
        existing_role_perms = {
            (row.role_id, row.permission_id)
            for row in bind.execute(
                sa.select(
                    role_permissions_table.c.role_id,
                    role_permissions_table.c.permission_id,
                )
            ).fetchall()
        }
        inserts = []
        for role_id, _lookup in role_rows:
            for key in [p["key"] for p in new_permissions]:
                perm_id = perm_by_key.get(key)
                if perm_id and (role_id, perm_id) not in existing_role_perms:
                    inserts.append(
                        {
                            "role_id": role_id,
                            "permission_id": perm_id,
                            "allowed": True,
                        }
                    )
        if inserts:
            op.bulk_insert(role_permissions_table, inserts)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "permissions" not in inspector.get_table_names():
        return

    permission_table = sa.table(
        "permissions",
        sa.column("id", sa.Integer()),
        sa.column("key", sa.String()),
    )
    role_permissions_table = sa.table(
        "role_permissions",
        sa.column("id", sa.Integer()),
        sa.column("permission_id", sa.Integer()),
    )

    target_keys = {"manage_posts", "manage_events"}
    perm_rows = bind.execute(
        sa.select(permission_table.c.id, permission_table.c.key).where(
            permission_table.c.key.in_(target_keys)
        )
    ).fetchall()
    perm_ids = [row.id for row in perm_rows]

    if perm_ids and "role_permissions" in inspector.get_table_names():
        op.execute(
            role_permissions_table.delete().where(
                role_permissions_table.c.permission_id.in_(perm_ids)
            )
        )

    if perm_ids:
        op.execute(
            permission_table.delete().where(permission_table.c.id.in_(perm_ids))
        )
