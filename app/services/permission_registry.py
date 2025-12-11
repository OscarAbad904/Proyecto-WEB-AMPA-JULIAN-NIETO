from __future__ import annotations

from typing import Iterable, Sequence

from sqlalchemy import inspect
from flask import current_app

from app.extensions import db
from app.models import Permission, RolePermission, Role
from app.utils import make_lookup_hash

# Roles base que siempre deberían existir para poder asignar permisos.
DEFAULT_ROLE_NAMES = [
    "Administrador",
    "Presidencia",
    "Vicepresidencia",
    "Secretaría",
    "Vicesecretaría",
    "Tesorería",
    "Vicetesorería",
    "Vocal",
    "Socio",
]

# Variantes conocidas (corruptas o sin acento) a normalizar hacia el nombre canónico.
ROLE_VARIANTS: list[tuple[str, str]] = [
    ("Admin", "Administrador"),
    ("Administrador", "Administrador"),
    ("Presidencia", "Presidencia"),
    ("Vicepresidencia", "Vicepresidencia"),
    ("Secretaria", "Secretaría"),
    ("Secretaría", "Secretaría"),
    ("Secretar?a", "Secretaría"),
    ("Secretarí­a", "Secretaría"),
    ("Secretaría", "Secretaría"),
    ("Secretar?a", "Secretaría"),
    ("Secretar?a", "Secretaría"),
    ("Secretarヮa", "Secretaría"),
    ("Vicesecretaria", "Vicesecretaría"),
    ("Vicesecretaría", "Vicesecretaría"),
    ("Vicesecretar?a", "Vicesecretaría"),
    ("Vicesecretar?a", "Vicesecretaría"),
    ("Vicesecretarヮa", "Vicesecretaría"),
    ("Tesoreria", "Tesorería"),
    ("Tesorería", "Tesorería"),
    ("Tesorer?a", "Tesorería"),
    ("Tesorer?a", "Tesorería"),
    ("Tesorerヮa", "Tesorería"),
    ("Vicetesoreria", "Vicetesorería"),
    ("Vicetesorería", "Vicetesorería"),
    ("Vicetesorer?a", "Vicetesorería"),
    ("Vicetesorer?a", "Vicetesorería"),
    ("Vicetesorerヮa", "Vicetesorería"),
    ("Vocal", "Vocal"),
    ("Socio", "Socio"),
]

# Catálogo de permisos de la plataforma con metadatos para UI y asignaciones iniciales.
PERMISSION_DEFINITIONS = [
    {
        "key": "access_admin_panel",
        "name": "Acceder al panel admin",
        "description": "Permite entrar al dashboard general de administración.",
        "section": "Sistema",
    },
    {
        "key": "view_posts",
        "name": "Ver noticias",
        "description": "Acceso de solo lectura al tablón de noticias en el panel.",
        "section": "Noticias",
    },
    {
        "key": "manage_posts",
        "name": "Gestionar noticias",
        "description": "Crear, editar, publicar o eliminar noticias del tablón.",
        "section": "Noticias",
    },
    {
        "key": "view_events",
        "name": "Ver eventos",
        "description": "Acceso de solo lectura al panel de eventos.",
        "section": "Eventos",
    },
    {
        "key": "manage_events",
        "name": "Gestionar eventos",
        "description": "Crear, editar y programar eventos del calendario interno.",
        "section": "Eventos",
    },
    {
        "key": "view_suggestions",
        "name": "Ver foro de sugerencias",
        "description": "Acceso al listado y detalle de sugerencias.",
        "section": "Sugerencias",
        "grant_to_all_roles": True,
    },
    {
        "key": "create_suggestions",
        "name": "Crear sugerencias",
        "description": "Permite abrir nuevas sugerencias en el foro.",
        "section": "Sugerencias",
        "grant_to_all_roles": True,
    },
    {
        "key": "comment_suggestions",
        "name": "Comentar sugerencias",
        "description": "Responder y participar en hilos del foro.",
        "section": "Sugerencias",
        "grant_to_all_roles": True,
    },
    {
        "key": "vote_suggestions",
        "name": "Votar sugerencias",
        "description": "Emitir votos positivos o negativos en el foro.",
        "section": "Sugerencias",
        "grant_to_all_roles": True,
    },
    {
        "key": "manage_suggestions",
        "name": "Moderar sugerencias",
        "description": "Cambiar estados, cerrar hilos o moderar el foro.",
        "section": "Sugerencias",
    },
    {
        "key": "view_commissions",
        "name": "Ver sección de comisiones",
        "description": "Permite acceder al listado y ficha de comisiones.",
        "section": "Comisiones",
    },
    {
        "key": "manage_commissions",
        "name": "Gestionar comisiones",
        "description": "Crear o editar comisiones desde el panel de administración.",
        "section": "Comisiones",
    },
    {
        "key": "manage_commission_members",
        "name": "Gestionar miembros de comisiones",
        "description": "Añadir o quitar miembros en una comisión.",
        "section": "Comisiones",
    },
    {
        "key": "manage_commission_projects",
        "name": "Gestionar proyectos de comisiones",
        "description": "Crear y actualizar proyectos asociados a una comisión.",
        "section": "Comisiones",
    },
    {
        "key": "manage_commission_meetings",
        "name": "Gestionar reuniones de comisiones",
        "description": "Crear y actualizar reuniones de comisión.",
        "section": "Comisiones",
    },
    {
        "key": "view_all_commission_calendar",
        "name": "Ver todas las reuniones de comisiones",
        "description": "Acceso a reuniones de cualquier comisión en el calendario interno.",
        "section": "Calendario",
    },
    {
        "key": "view_private_calendar",
        "name": "Ver calendario privado",
        "description": "Acceso al calendario interno de socios.",
        "section": "Calendario",
        "grant_to_all_roles": True,
    },
    {
        "key": "clear_calendar_cache",
        "name": "Limpiar caché de calendario",
        "description": "Permite forzar la limpieza de la caché del calendario.",
        "section": "Calendario",
    },
    {
        "key": "view_documents",
        "name": "Ver documentos",
        "description": "Acceso al listado de documentos y actas.",
        "section": "Documentos",
        "grant_to_all_roles": True,
    },
    {
        "key": "manage_documents",
        "name": "Gestionar documentos",
        "description": "Subir, editar o eliminar documentos y actas.",
        "section": "Documentos",
    },
    {
        "key": "view_members",
        "name": "Ver socios/usuarios",
        "description": "Acceso de solo lectura a la gestión de cuentas.",
        "section": "Usuarios",
    },
    {
        "key": "manage_members",
        "name": "Gestionar socios/usuarios",
        "description": "Dar de alta, baja o editar datos de socios.",
        "section": "Usuarios",
    },
    {
        "key": "view_permissions",
        "name": "Ver permisos",
        "description": "Acceso de solo lectura a la configuración de permisos.",
        "section": "Sistema",
    },
    {
        "key": "manage_permissions",
        "name": "Gestionar permisos",
        "description": "Administrar permisos por rol.",
        "section": "Sistema",
    },
]

SECTION_ORDER = [
    "Usuarios",
    "Noticias",
    "Eventos",
    "Sugerencias",
    "Comisiones",
    "Calendario",
    "Documentos",
    "Sistema",
    "Otros",
]


def _infer_section_from_key(key: str) -> str:
    if key.startswith(("manage_post", "view_post")):
        return "Noticias"
    if key.startswith(("manage_event", "view_event")):
        return "Eventos"
    if key.startswith(("manage_suggestion", "view_suggestion", "create_suggestion", "comment_suggestion", "vote_suggestion")):
        return "Sugerencias"
    if key.startswith(("manage_commission", "view_commission")):
        return "Comisiones"
    if "calendar" in key:
        return "Calendario"
    if "member" in key or "usuario" in key:
        return "Usuarios"
    if key.startswith("document"):
        return "Documentos"
    return "Otros"


def ensure_roles_and_permissions(
    default_roles: Iterable[str] | None = None,
) -> tuple[list[Role], list[Permission]]:
    """Asegura que roles base, permisos y asignaciones por defecto existan."""
    defaults = list(default_roles or DEFAULT_ROLE_NAMES)
    try:
        inspector = inspect(db.engine)
    except Exception as exc:  # noqa: BLE001
        current_app.logger.error("No se pudo inspeccionar la base de datos para sincronizar permisos: %s", exc)
        return [], []

    tables = set(inspector.get_table_names())
    if not {"roles", "permissions", "role_permissions"}.issubset(tables):
        # Migraciones no aplicadas todavía
        return [], []

    roles = list(Role.query.all())

    # Normalizar nombres corruptos o sin acentos hacia los canónicos.
    alias_lookup_to_name = {
        make_lookup_hash(alias): canonical for alias, canonical in ROLE_VARIANTS
    }
    canonical_lookup_to_name = {make_lookup_hash(name): name for name in defaults}

    role_lookup: dict[str, Role] = {role.name_lookup: role for role in roles}
    needs_commit = False
    for role in list(roles):
        target_name = alias_lookup_to_name.get(role.name_lookup)
        if not target_name:
            continue
        target_lookup = make_lookup_hash(target_name)
        if target_lookup == role.name_lookup and role.name == target_name:
            continue
        # ¿Existe ya el rol canónico?
        existing_target = role_lookup.get(target_lookup)
        if existing_target and existing_target.id != role.id:
            # Reasignar usuarios y permisos al rol correcto y eliminar el corrupto.
            for user in role.users:
                user.role_id = existing_target.id
            for rp in list(role.role_permissions):
                duplicate = RolePermission.query.filter_by(
                    role_id=existing_target.id, permission_id=rp.permission_id
                ).first()
                if duplicate:
                    db.session.delete(rp)
                else:
                    rp.role_id = existing_target.id
            db.session.delete(role)
            roles.remove(role)
            needs_commit = True
        else:
            role.name = target_name
            role_lookup.pop(role.name_lookup, None)
            role_lookup[target_lookup] = role
            needs_commit = True
    if needs_commit:
        db.session.commit()
        roles = list(Role.query.all())
        role_lookup = {role.name_lookup: role for role in roles}

    created_roles = 0
    for role_name in defaults:
        lookup = make_lookup_hash(role_name)
        if lookup not in role_lookup:
            role = Role(name=role_name)
            db.session.add(role)
            created_roles += 1
    if created_roles:
        db.session.commit()
        roles = list(Role.query.all())
        role_lookup = {role.name_lookup: role for role in roles}

    definitions = {entry["key"]: entry for entry in PERMISSION_DEFINITIONS}
    perm_map: dict[str, Permission] = {perm.key: perm for perm in Permission.query.all()}

    created_or_updated = False
    for key, meta in definitions.items():
        perm = perm_map.get(key)
        if not perm:
            perm = Permission(
                key=key,
                name=meta.get("name") or key,
                description=meta.get("description"),
            )
            db.session.add(perm)
            perm_map[key] = perm
            created_or_updated = True
        else:
            updated = False
            if meta.get("name") and perm.name != meta["name"]:
                perm.name = meta["name"]
                updated = True
            if meta.get("description") and perm.description != meta["description"]:
                perm.description = meta["description"]
                updated = True
            if updated:
                created_or_updated = True
    if created_or_updated:
        db.session.commit()
        perm_map = {perm.key: perm for perm in Permission.query.all()}

    rp_existing = {(rp.role_id, rp.permission_id) for rp in RolePermission.query.all()}
    role_permissions_to_add: list[RolePermission] = []
    for meta in PERMISSION_DEFINITIONS:
        perm = perm_map.get(meta["key"])
        if not perm:
            continue
        targets: list[Role] = []
        if meta.get("grant_to_all_roles"):
            targets = roles
        else:
            for role_name in meta.get("grant_to_roles", []):
                role = role_lookup.get(make_lookup_hash(role_name))
                if role:
                    targets.append(role)
        for role in targets:
            if (role.id, perm.id) not in rp_existing:
                role_permissions_to_add.append(
                    RolePermission(role_id=role.id, permission_id=perm.id, allowed=True)
                )
                rp_existing.add((role.id, perm.id))
    if role_permissions_to_add:
        db.session.bulk_save_objects(role_permissions_to_add)
        db.session.commit()

    order_map = {make_lookup_hash(name): idx for idx, name in enumerate(defaults)}
    roles.sort(key=lambda r: (order_map.get(r.name_lookup, len(order_map)), r.name_lookup or ""))
    permissions = list(perm_map.values())
    permissions.sort(key=lambda p: p.key or "")
    return roles, permissions


def group_permissions_by_section(permissions: Sequence[Permission]) -> list[tuple[str, list[dict]]]:
    """Agrupa permisos por sección para facilitar el render en /admin/permisos."""
    definitions = {entry["key"]: entry for entry in PERMISSION_DEFINITIONS}
    section_map: dict[str, list[dict]] = {}

    for perm in permissions:
        meta = definitions.get(perm.key, {})
        section = meta.get("section") or _infer_section_from_key(perm.key or "")
        entry = {
            "permission": perm,
            "label": meta.get("name") or perm.name or perm.key,
            "description": meta.get("description") or perm.description or "",
        }
        section_map.setdefault(section, []).append(entry)

    grouped: list[tuple[str, list[dict]]] = []
    for section in SECTION_ORDER:
        if section in section_map:
            grouped.append(
                (
                    section,
                    sorted(section_map.pop(section), key=lambda item: (item["label"] or "").lower()),
                )
            )
    for section, items in section_map.items():
        grouped.append((section, sorted(items, key=lambda item: (item["label"] or "").lower())))
    return grouped
