# Comisiones y permisos

## Modelos añadidos
- **Commission**: nombre, slug único, descripción cifrada, activo, marcas de creación/actualización. Relaciones con miembros, proyectos y reuniones.
- **CommissionMembership**: vincula usuarios con comisiones, rol interno (`coordinador`, `vocal`, `miembro`), estado activo y unicidad por comisión/usuario.
- **CommissionProject**: proyectos por comisión con estado (`pendiente`, `en_progreso`, `completado`, `en_pausa`), fechas opcionales y responsable.
- **CommissionMeeting**: reuniones de comisión con rango de fechas, ubicación opcional, enlace a Google Calendar y acta (`minutes_document_id` hacia `Document`).
- **Permission / RolePermission**: permisos de alto nivel asociados a roles (`allowed` por combinación rol-permiso).

## Permisos clave
- `view_commissions`, `manage_commissions`
- `manage_commission_members`, `manage_commission_projects`, `manage_commission_meetings`
- `manage_permissions`
- `view_all_commission_calendar`

Los roles privilegiados (`PRIVILEGED_ROLES`) siguen teniendo acceso total. `User.has_permission` devuelve `True` para privilegiados; en otro caso consulta `RolePermission` y devuelve `False` por defecto si no hay entrada.

## Pantallas y rutas
- Socios:
  - `/socios/comisiones` (listado) y `/socios/comisiones/<slug>` (detalle). Requiere pertenencia activa o permiso `view_commissions`.
  - `/socios/calendario` muestra eventos generales + reuniones de comisiones propias (o todas si el rol tiene `view_all_commission_calendar`).
- Acciones internas de comisión (socios):
  - Añadir/desactivar miembros: `/socios/comisiones/<slug>/miembros/nuevo` y desactivación vía botón en detalle (requiere `manage_commission_members` y rol de coordinador o superior).
  - Proyectos: `/socios/comisiones/<slug>/proyectos/nuevo|<id>/editar` con `manage_commission_projects`.
  - Reuniones: `/socios/comisiones/<slug>/reuniones/nueva|<id>/editar` con `manage_commission_meetings`.
- Admin:
  - `/admin/comisiones` y `/admin/comisiones/<id>/editar` requieren `manage_commissions`.
  - `/admin/comisiones/<id>/miembros`, `/proyectos/...`, `/reuniones/...` para gestión centralizada.
  - `/admin/permisos` requiere `manage_permissions` o rol privilegiado para marcar permisos por rol.

## Migración
La migración `e6ad2c3f4b5a_commissions_permissions.py` crea las tablas nuevas, inicializa los permisos anteriores y los asigna a roles `admin`/`administrador` si existen.
