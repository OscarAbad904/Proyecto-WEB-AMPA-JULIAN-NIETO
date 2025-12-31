"""add delete_commission_projects_permanently and delete_commission_members_permanently permissions

Revision ID: h2i3j4k5l6m7
Revises: g1h2i3j4k5l6
Create Date: 2025-12-31 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
import hashlib

revision = "h2i3j4k5l6m7"
down_revision = "2f0c3d4e5b6a"
branch_labels = None
depends_on = None


def _make_lookup(value: str) -> str:
    normalized = (value or "").strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _add_permission(bind, key: str, name: str, description: str):
    """Añade un permiso y lo asigna al rol Administrador."""
    # Verificar si el permiso ya existe
    result = bind.execute(
        sa.text("SELECT id FROM permissions WHERE key = :key"),
        {"key": key}
    ).fetchone()
    
    if result is None:
        # Insertar el nuevo permiso
        bind.execute(
            sa.text("""
                INSERT INTO permissions (key, name, description)
                VALUES (:key, :name, :description)
            """),
            {"key": key, "name": name, "description": description}
        )
        
        # Obtener el ID del permiso recién creado
        perm_result = bind.execute(
            sa.text("SELECT id FROM permissions WHERE key = :key"),
            {"key": key}
        ).fetchone()
        
        if perm_result:
            perm_id = perm_result[0]
            
            # Obtener el rol Administrador
            admin_lookup = _make_lookup("Administrador")
            role_result = bind.execute(
                sa.text("SELECT id FROM roles WHERE lookup_hash = :lookup"),
                {"lookup": admin_lookup}
            ).fetchone()
            
            if role_result:
                role_id = role_result[0]
                # Asignar el permiso al rol Administrador
                bind.execute(
                    sa.text("""
                        INSERT INTO role_permissions (role_id, permission_id)
                        VALUES (:role_id, :permission_id)
                        ON CONFLICT DO NOTHING
                    """),
                    {"role_id": role_id, "permission_id": perm_id}
                )


def _remove_permission(bind, key: str):
    """Elimina un permiso y sus asignaciones."""
    result = bind.execute(
        sa.text("SELECT id FROM permissions WHERE key = :key"),
        {"key": key}
    ).fetchone()
    
    if result:
        perm_id = result[0]
        bind.execute(
            sa.text("DELETE FROM role_permissions WHERE permission_id = :perm_id"),
            {"perm_id": perm_id}
        )
        bind.execute(
            sa.text("DELETE FROM permissions WHERE id = :perm_id"),
            {"perm_id": perm_id}
        )


def upgrade():
    bind = op.get_bind()
    
    _add_permission(
        bind,
        "delete_commission_projects_permanently",
        "Eliminar proyectos permanentemente",
        "Borrar definitivamente proyectos de comisiones junto con sus reuniones y discusiones."
    )
    
    _add_permission(
        bind,
        "delete_commission_members_permanently",
        "Eliminar miembros de comisiones permanentemente",
        "Borrar definitivamente el registro de membresía de una comisión."
    )


def downgrade():
    bind = op.get_bind()
    _remove_permission(bind, "delete_commission_projects_permanently")
    _remove_permission(bind, "delete_commission_members_permanently")
