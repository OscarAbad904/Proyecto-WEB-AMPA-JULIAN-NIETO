"""add commissions and permissions tables with safety checks

Revision ID: e6ad2c3f4b5a
Revises: c1d2e3f4a5b6
Create Date: 2025-12-07 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
import hashlib

try:
    from app.models import EncryptedType as _EncryptedType
except Exception:
    _EncryptedType = None

# Fallback to plain Text if the encrypted type is not importable
class EncryptedType(sa.Text if _EncryptedType is None else _EncryptedType):
    cache_ok = True


# revision identifiers, used by Alembic.
revision = "e6ad2c3f4b5a"
down_revision = "c1d2e3f4a5b6"
branch_labels = None
depends_on = None


def _make_lookup(value: str) -> str:
    normalized = (value or "").strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _has_table(inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _has_index(inspector, table: str, name: str) -> bool:
    return any(idx.get("name") == name for idx in inspector.get_indexes(table))


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # permissions
    if not _has_table(inspector, "permissions"):
        op.create_table(
            "permissions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("key", sa.String(length=128), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
        )
    if not _has_index(inspector, "permissions", op.f("ix_permissions_key")) and _has_table(inspector, "permissions"):
        op.create_index(op.f("ix_permissions_key"), "permissions", ["key"], unique=True)

    # commissions
    if not _has_table(inspector, "commissions"):
        op.create_table(
            "commissions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("slug", sa.String(length=255), nullable=False),
            sa.Column("description_html", EncryptedType(), nullable=True),
            sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()")),
            sa.UniqueConstraint("slug"),
        )
    if _has_table(inspector, "commissions"):
        if not _has_index(inspector, "commissions", op.f("ix_commissions_is_active")):
            op.create_index(op.f("ix_commissions_is_active"), "commissions", ["is_active"], unique=False)
        if not _has_index(inspector, "commissions", op.f("ix_commissions_name")):
            op.create_index(op.f("ix_commissions_name"), "commissions", ["name"], unique=False)
        if not _has_index(inspector, "commissions", op.f("ix_commissions_slug")):
            op.create_index(op.f("ix_commissions_slug"), "commissions", ["slug"], unique=True)

    # role_permissions
    if not _has_table(inspector, "role_permissions"):
        op.create_table(
            "role_permissions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("role_id", sa.Integer(), nullable=False),
            sa.Column("permission_id", sa.Integer(), nullable=False),
            sa.Column("allowed", sa.Boolean(), server_default=sa.text("true"), nullable=False),
            sa.ForeignKeyConstraint(["permission_id"], ["permissions.id"]),
            sa.ForeignKeyConstraint(["role_id"], ["roles.id"]),
            sa.UniqueConstraint("role_id", "permission_id", name="uq_role_permission"),
        )
    if _has_table(inspector, "role_permissions"):
        if not _has_index(inspector, "role_permissions", op.f("ix_role_permissions_permission_id")):
            op.create_index(op.f("ix_role_permissions_permission_id"), "role_permissions", ["permission_id"], unique=False)
        if not _has_index(inspector, "role_permissions", op.f("ix_role_permissions_role_id")):
            op.create_index(op.f("ix_role_permissions_role_id"), "role_permissions", ["role_id"], unique=False)

    # commission_memberships
    if not _has_table(inspector, "commission_memberships"):
        op.create_table(
            "commission_memberships",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("commission_id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("role", sa.String(length=32), nullable=False),
            sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()")),
            sa.ForeignKeyConstraint(["commission_id"], ["commissions.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.UniqueConstraint("commission_id", "user_id", name="uq_commission_member"),
        )
    if _has_table(inspector, "commission_memberships"):
        if not _has_index(inspector, "commission_memberships", op.f("ix_commission_memberships_commission_id")):
            op.create_index(
                op.f("ix_commission_memberships_commission_id"),
                "commission_memberships",
                ["commission_id"],
                unique=False,
            )
        if not _has_index(inspector, "commission_memberships", op.f("ix_commission_memberships_role")):
            op.create_index(op.f("ix_commission_memberships_role"), "commission_memberships", ["role"], unique=False)
        if not _has_index(inspector, "commission_memberships", op.f("ix_commission_memberships_user_id")):
            op.create_index(op.f("ix_commission_memberships_user_id"), "commission_memberships", ["user_id"], unique=False)

    # commission_projects
    if not _has_table(inspector, "commission_projects"):
        op.create_table(
            "commission_projects",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("commission_id", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("description_html", EncryptedType(), nullable=True),
            sa.Column("status", sa.String(length=32), server_default=sa.text("'pendiente'"), nullable=False),
            sa.Column("start_date", sa.Date()),
            sa.Column("end_date", sa.Date()),
            sa.Column("responsible_id", sa.Integer()),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()")),
            sa.ForeignKeyConstraint(["commission_id"], ["commissions.id"]),
            sa.ForeignKeyConstraint(["responsible_id"], ["users.id"]),
        )
    if _has_table(inspector, "commission_projects"):
        if not _has_index(inspector, "commission_projects", op.f("ix_commission_projects_commission_id")):
            op.create_index(
                op.f("ix_commission_projects_commission_id"),
                "commission_projects",
                ["commission_id"],
                unique=False,
            )
        if not _has_index(inspector, "commission_projects", op.f("ix_commission_projects_status")):
            op.create_index(op.f("ix_commission_projects_status"), "commission_projects", ["status"], unique=False)

    # commission_meetings
    if not _has_table(inspector, "commission_meetings"):
        op.create_table(
            "commission_meetings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("commission_id", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("description_html", EncryptedType(), nullable=True),
            sa.Column("start_at", sa.DateTime(), nullable=False),
            sa.Column("end_at", sa.DateTime(), nullable=False),
            sa.Column("location", sa.String(length=255)),
            sa.Column("google_event_id", sa.String(length=255)),
            sa.Column("minutes_document_id", sa.Integer()),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()")),
            sa.ForeignKeyConstraint(["commission_id"], ["commissions.id"]),
            sa.ForeignKeyConstraint(["minutes_document_id"], ["documents.id"]),
        )
    if _has_table(inspector, "commission_meetings"):
        if not _has_index(inspector, "commission_meetings", op.f("ix_commission_meetings_commission_id")):
            op.create_index(
                op.f("ix_commission_meetings_commission_id"),
                "commission_meetings",
                ["commission_id"],
                unique=False,
            )
        if not _has_index(inspector, "commission_meetings", op.f("ix_commission_meetings_end_at")):
            op.create_index(op.f("ix_commission_meetings_end_at"), "commission_meetings", ["end_at"], unique=False)
        if not _has_index(inspector, "commission_meetings", op.f("ix_commission_meetings_start_at")):
            op.create_index(op.f("ix_commission_meetings_start_at"), "commission_meetings", ["start_at"], unique=False)

    # seed permissions and grant to admin-like roles
    permissions_to_create = [
        {
            "key": "view_commissions",
            "name": "Ver sección de comisiones",
            "description": "Permite acceder al listado y ficha de comisiones.",
        },
        {
            "key": "manage_commissions",
            "name": "Gestionar comisiones",
            "description": "Crear o editar comisiones desde el panel de administración.",
        },
        {
            "key": "manage_commission_members",
            "name": "Gestionar miembros de comisiones",
            "description": "Añadir o quitar miembros en una comisión.",
        },
        {
            "key": "manage_commission_projects",
            "name": "Gestionar proyectos de comisiones",
            "description": "Crear y actualizar proyectos asociados a una comisión.",
        },
        {
            "key": "manage_commission_meetings",
            "name": "Gestionar reuniones de comisiones",
            "description": "Crear y actualizar reuniones de comisión.",
        },
        {
            "key": "manage_permissions",
            "name": "Gestionar permisos",
            "description": "Administrar permisos por rol.",
        },
        {
            "key": "view_all_commission_calendar",
            "name": "Ver todas las reuniones de comisiones",
            "description": "Acceso a reuniones de cualquier comisión en el calendario interno.",
        },
    ]

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

    existing_perm_rows = bind.execute(sa.select(permission_table.c.key, permission_table.c.id)).fetchall() if _has_table(inspector, "permissions") else []
    existing_perm_keys = {row.key for row in existing_perm_rows}
    if _has_table(inspector, "permissions"):
        to_insert = [p for p in permissions_to_create if p["key"] not in existing_perm_keys]
        if to_insert:
            op.bulk_insert(permission_table, to_insert)

    # refresh permission ids
    perm_rows = bind.execute(sa.select(permission_table.c.id, permission_table.c.key)).fetchall() if _has_table(inspector, "permissions") else []
    perm_by_key = {row.key: row.id for row in perm_rows}

    admin_lookups = {_make_lookup("admin"), _make_lookup("administrador")}
    role_rows = bind.execute(
        sa.select(roles_table.c.id, roles_table.c.name_lookup).where(roles_table.c.name_lookup.in_(admin_lookups))
    ).fetchall() if _has_table(inspector, "roles") else []

    existing_role_perms = set()
    if _has_table(inspector, "role_permissions"):
        existing_role_perms = {
            (row.role_id, row.permission_id)
            for row in bind.execute(sa.select(role_permissions_table.c.role_id, role_permissions_table.c.permission_id))
        }

    inserts = []
    for role_row in role_rows:
        for key, perm_id in perm_by_key.items():
            if (role_row.id, perm_id) not in existing_role_perms:
                inserts.append({"role_id": role_row.id, "permission_id": perm_id, "allowed": True})
    if inserts and _has_table(inspector, "role_permissions"):
        op.bulk_insert(role_permissions_table, inserts)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for name in [
        "commission_meetings",
        "commission_projects",
        "commission_memberships",
        "role_permissions",
        "commissions",
        "permissions",
    ]:
        if _has_table(inspector, name):
            op.drop_table(name)
