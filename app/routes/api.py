from flask import Blueprint, jsonify, request, current_app, abort, send_file
from flask_login import login_required, current_user
from datetime import datetime, timedelta
import json
import sqlalchemy as sa
from sqlalchemy.exc import ProgrammingError

from app.models import (
    Permission,
    user_is_privileged,
    CommissionMeeting,
    CommissionMembership,
    Commission,
    CommissionProject,
    Suggestion,
    Comment,
    DriveFile,
    DriveFileEvent,
    Event,
    Post,
    UserSeenItem,
)
from app.extensions import db
from app.extensions import csrf
from app.utils import get_local_now
from app.services.commission_drive_service import (
    ensure_commission_drive_folder,
    ensure_project_drive_folder,
)
from app.services.drive_files_service import (
    list_drive_files,
    find_drive_file_by_name,
    upload_drive_file,
    get_drive_file_meta,
    download_drive_file,
    delete_drive_file,
    restore_drive_file,
)
from app.services.discussion_poll_service import get_latest_poll_activity_by_discussion

api_bp = Blueprint("api", __name__)


def _get_latest_nine_post_ids() -> list[int]:
    posts = (
        Post.query.filter_by(status="published")
        .order_by(Post.published_at.desc().nullslast(), Post.created_at.desc())
        .limit(9)
        .all()
    )
    return [p.id for p in posts]


def _get_upcoming_nine_event_ids(now_dt: datetime) -> list[int]:
    events = (
        Event.query.filter(Event.status == "published")
        .filter(Event.end_at >= now_dt)
        .order_by(Event.start_at.asc())
        .limit(9)
        .all()
    )
    return [e.id for e in events]


@api_bp.route("/me/unread-counts")
@login_required
def me_unread_counts():
    now_dt = get_local_now()

    post_ids = _get_latest_nine_post_ids()
    event_ids = _get_upcoming_nine_event_ids(now_dt)

    posts_unread = 0
    events_unread = 0
    commissions_unread = 0
    commissions_unread_breakdown = {
        "commissions": 0,
        "projects": 0,
        "discussions": 0,
        "files": 0,
    }

    if post_ids:
        try:
            seen_post_ids = {
                row.item_id
                for row in (
                    UserSeenItem.query.filter_by(user_id=current_user.id, item_type="post")
                    .filter(UserSeenItem.item_id.in_(post_ids))
                    .all()
                )
            }
            posts_unread = len(set(post_ids) - seen_post_ids)
        except ProgrammingError:
            db.session.rollback()
            posts_unread = len(post_ids)

    if event_ids:
        try:
            seen_event_ids = {
                row.item_id
                for row in (
                    UserSeenItem.query.filter_by(user_id=current_user.id, item_type="event")
                    .filter(UserSeenItem.item_id.in_(event_ids))
                    .all()
                )
            }
            events_unread = len(set(event_ids) - seen_event_ids)
        except ProgrammingError:
            db.session.rollback()
            events_unread = len(event_ids)

    # Novedades en Comisiones para el usuario (solo ámbito donde es miembro activo):
    # - Comisión: no vista.
    # - Proyecto: no visto.
    # - Discusión: no vista o con comentarios posteriores a la última visita.
    # - Archivos: registros DriveFile no vistos (solo si existen en DB; se crean al listar la carpeta).
    try:
        member_commission_ids = [
            commission_id
            for (commission_id,) in (
                CommissionMembership.query.with_entities(CommissionMembership.commission_id)
                .join(Commission)
                .filter(
                    CommissionMembership.user_id == current_user.id,
                    CommissionMembership.is_active.is_(True),
                    Commission.is_active.is_(True),
                )
                .all()
            )
        ]
        if member_commission_ids:
            # 1) Comisiones no vistas.
            seen_commission_ids = {
                row.item_id
                for row in (
                    UserSeenItem.query.filter_by(user_id=current_user.id, item_type="commission")
                    .filter(UserSeenItem.item_id.in_(member_commission_ids))
                    .all()
                )
            }
            commissions_new = len(set(member_commission_ids) - seen_commission_ids)

            # 2) Proyectos activos no vistos.
            active_project_statuses = ("pendiente", "en_progreso")
            project_ids = [
                project_id
                for (project_id,) in (
                    CommissionProject.query.with_entities(CommissionProject.id)
                    .filter(CommissionProject.commission_id.in_(member_commission_ids))
                    .filter(CommissionProject.status.in_(active_project_statuses))
                    .all()
                )
            ]
            seen_project_ids: set[int] = set()
            if project_ids:
                seen_project_ids = {
                    row.item_id
                    for row in (
                        UserSeenItem.query.filter_by(user_id=current_user.id, item_type="c_project")
                        .filter(UserSeenItem.item_id.in_(project_ids))
                        .all()
                    )
                }
            projects_new = len(set(project_ids) - seen_project_ids)

            # 3) Discusiones (comisión + proyecto) no vistas o con comentarios nuevos.
            categories = [f"comision:{cid}" for cid in member_commission_ids]
            if project_ids:
                categories.extend([f"proyecto:{pid}" for pid in project_ids])

            discussion_ids: list[int] = []
            if categories:
                discussion_ids = [
                    suggestion_id
                    for (suggestion_id,) in (
                        Suggestion.query.with_entities(Suggestion.id)
                        .filter(Suggestion.category.in_(categories))
                        .filter(Suggestion.status.in_(("pendiente", "aprobada")))
                        .all()
                    )
                ]

            discussions_new = 0
            if discussion_ids:
                seen_rows = (
                    UserSeenItem.query.filter_by(user_id=current_user.id, item_type="suggestion")
                    .filter(UserSeenItem.item_id.in_(discussion_ids))
                    .all()
                )
                seen_at_by_discussion_id = {row.item_id: row.seen_at for row in seen_rows}
                unseen_discussion_ids = set(discussion_ids) - set(seen_at_by_discussion_id.keys())

                latest_comment_rows = (
                    db.session.query(Comment.suggestion_id, sa.func.max(Comment.created_at))
                    .filter(Comment.suggestion_id.in_(discussion_ids))
                    .group_by(Comment.suggestion_id)
                    .all()
                )
                latest_comment_at_by_discussion_id = {
                    suggestion_id: latest_at for suggestion_id, latest_at in latest_comment_rows
                }
                latest_poll_at_by_discussion_id = get_latest_poll_activity_by_discussion(discussion_ids)

                updated_discussion_ids = set()
                for discussion_id, seen_at in seen_at_by_discussion_id.items():
                    latest_comment_at = latest_comment_at_by_discussion_id.get(discussion_id)
                    latest_poll_at = latest_poll_at_by_discussion_id.get(discussion_id)
                    if latest_comment_at and seen_at and latest_comment_at > seen_at:
                        updated_discussion_ids.add(discussion_id)
                        continue
                    if latest_poll_at and seen_at and latest_poll_at > seen_at:
                        updated_discussion_ids.add(discussion_id)

                discussions_new = len(unseen_discussion_ids) + len(updated_discussion_ids)

            # 4) Archivos no vistos (solo registros ya conocidos; se crean al listar).
            drive_db_ids = [
                file_db_id
                for (file_db_id,) in (
                    DriveFile.query.with_entities(DriveFile.id)
                    .filter(DriveFile.deleted_at.is_(None))
                    .filter(
                        sa.or_(
                            sa.and_(
                                DriveFile.scope_type == "commission",
                                DriveFile.scope_id.in_(member_commission_ids),
                            ),
                            sa.and_(
                                DriveFile.scope_type == "project",
                                DriveFile.scope_id.in_(project_ids or [-1]),
                            ),
                        )
                    )
                    .all()
                )
            ]
            files_new = 0
            if drive_db_ids:
                seen_drive_ids = {
                    row.item_id
                    for row in (
                        UserSeenItem.query.filter_by(user_id=current_user.id, item_type="drivefile")
                        .filter(UserSeenItem.item_id.in_(drive_db_ids))
                        .all()
                    )
                }
                files_new = len(set(drive_db_ids) - seen_drive_ids)

            commissions_unread_breakdown = {
                "commissions": int(commissions_new),
                "projects": int(projects_new),
                "discussions": int(discussions_new),
                "files": int(files_new),
            }

            commissions_unread = int(commissions_new + projects_new + discussions_new + files_new)
    except ProgrammingError:
        db.session.rollback()
        commissions_unread = 0

    return jsonify(
        {
            "ok": True,
            "posts_unread": int(posts_unread),
            "events_unread": int(events_unread),
            "commissions_unread": int(commissions_unread),
            "commissions_unread_breakdown": commissions_unread_breakdown,
            "limit": 9,
        }
    ), 200


@api_bp.route("/me/seen", methods=["POST"])
@csrf.exempt
@login_required
def me_mark_seen():
    payload = request.get_json(silent=True) or {}
    item_type = str(payload.get("item_type") or "").strip().lower()
    item_id = payload.get("item_id")

    # Nota: item_type está limitado a 16 chars (UserSeenItem.item_type).
    if item_type not in {"post", "event", "commission", "suggestion", "c_project", "drivefile"}:
        return jsonify({"ok": False, "error": "item_type inválido"}), 400
    try:
        item_id_int = int(item_id)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "item_id inválido"}), 400
    if item_id_int <= 0:
        return jsonify({"ok": False, "error": "item_id inválido"}), 400

    if item_type == "post":
        exists = Post.query.filter_by(id=item_id_int, status="published").first()
        if not exists:
            return jsonify({"ok": False, "error": "Noticia no encontrada"}), 404
    if item_type == "event":
        exists = Event.query.filter_by(id=item_id_int, status="published").first()
        if not exists:
            return jsonify({"ok": False, "error": "Evento no encontrado"}), 404

    if item_type == "commission":
        commission = Commission.query.filter_by(id=item_id_int).first()
        if not commission:
            return jsonify({"ok": False, "error": "Comisión no encontrada"}), 404

        can_view_all_commissions = (
            current_user.has_permission("view_commissions")
            or current_user.has_permission("manage_commissions")
            or current_user.has_permission("manage_commission_members")
            or user_is_privileged(current_user)
        )
        is_member = bool(
            CommissionMembership.query.filter_by(
                user_id=current_user.id,
                commission_id=item_id_int,
                is_active=True,
            ).first()
        )
        if not (is_member or can_view_all_commissions):
            return jsonify({"ok": False, "error": "No autorizado"}), 403

    if item_type == "c_project":
        project = CommissionProject.query.filter_by(id=item_id_int).first()
        if not project:
            return jsonify({"ok": False, "error": "Proyecto no encontrado"}), 404

        can_view_all_commissions = (
            current_user.has_permission("view_commissions")
            or current_user.has_permission("manage_commissions")
            or current_user.has_permission("manage_commission_members")
            or user_is_privileged(current_user)
        )
        is_member = bool(
            CommissionMembership.query.filter_by(
                user_id=current_user.id,
                commission_id=project.commission_id,
                is_active=True,
            ).first()
        )
        if not (is_member or can_view_all_commissions):
            return jsonify({"ok": False, "error": "No autorizado"}), 403

    if item_type == "suggestion":
        suggestion = Suggestion.query.filter_by(id=item_id_int).first()
        if not suggestion:
            return jsonify({"ok": False, "error": "Discusión no encontrada"}), 404

        category = (getattr(suggestion, "category", None) or "").strip()
        commission_id = None
        project_id = None
        if category.startswith("comision:"):
            try:
                commission_id = int(category.split(":", 1)[1])
            except Exception:
                commission_id = None
        elif category.startswith("proyecto:"):
            try:
                project_id = int(category.split(":", 1)[1])
            except Exception:
                project_id = None

        is_scoped = commission_id is not None or project_id is not None

        # Si el foro general está deshabilitado, solo se permiten discusiones scoped.
        if not bool(current_app.config.get("SUGGESTIONS_FORUM_ENABLED", False)) and not is_scoped:
            return jsonify({"ok": False, "error": "Discusión no encontrada"}), 404

        if not is_scoped and not current_user.has_permission("view_suggestions"):
            return jsonify({"ok": False, "error": "No autorizado"}), 403

        # Para discusiones scoped (comisiones/proyectos), validar pertenencia o permisos.
        if commission_id is not None:
            can_view_scoped = (
                bool(
                    CommissionMembership.query.filter_by(
                        user_id=current_user.id,
                        commission_id=commission_id,
                        is_active=True,
                    ).first()
                )
                or current_user.has_permission("manage_commission_members")
                or current_user.has_permission("manage_commissions")
                or user_is_privileged(current_user)
            )
            if not can_view_scoped:
                return jsonify({"ok": False, "error": "No autorizado"}), 403

        if project_id is not None:
            project = CommissionProject.query.filter_by(id=project_id).first()
            if not project:
                return jsonify({"ok": False, "error": "Discusión no encontrada"}), 404
            can_view_scoped = (
                bool(
                    CommissionMembership.query.filter_by(
                        user_id=current_user.id,
                        commission_id=project.commission_id,
                        is_active=True,
                    ).first()
                )
                or current_user.has_permission("manage_commission_members")
                or current_user.has_permission("manage_commissions")
                or user_is_privileged(current_user)
            )
            if not can_view_scoped:
                return jsonify({"ok": False, "error": "No autorizado"}), 403

    if item_type == "drivefile":
        drive_file = DriveFile.query.filter_by(id=item_id_int).first()
        if not drive_file:
            return jsonify({"ok": False, "error": "Archivo no encontrado"}), 404

        scope_type = (getattr(drive_file, "scope_type", None) or "").strip().lower()
        scope_id = getattr(drive_file, "scope_id", None)
        try:
            scope_id_int = int(scope_id)
        except (TypeError, ValueError):
            scope_id_int = 0

        if scope_type == "commission":
            commission = Commission.query.filter_by(id=scope_id_int).first()
            if not commission:
                return jsonify({"ok": False, "error": "Archivo no encontrado"}), 404
            if not _can_access_commission_files(commission):
                return jsonify({"ok": False, "error": "No autorizado"}), 403
        elif scope_type == "project":
            project = CommissionProject.query.filter_by(id=scope_id_int).first()
            commission = project.commission if project else None
            if commission is None and project is not None:
                commission = Commission.query.get(project.commission_id)
            if not project or not commission:
                return jsonify({"ok": False, "error": "Archivo no encontrado"}), 404
            if not _can_access_commission_files(commission):
                return jsonify({"ok": False, "error": "No autorizado"}), 403
        else:
            return jsonify({"ok": False, "error": "Archivo no encontrado"}), 404

    now_dt = get_local_now()
    try:
        existing = UserSeenItem.query.filter_by(
            user_id=current_user.id,
            item_type=item_type,
            item_id=item_id_int,
        ).first()
        if existing:
            existing.seen_at = now_dt
        else:
            db.session.add(
                UserSeenItem(
                    user_id=current_user.id,
                    item_type=item_type,
                    item_id=item_id_int,
                    seen_at=now_dt,
                )
            )
        db.session.commit()
        return jsonify({"ok": True}), 200
    except ProgrammingError:
        db.session.rollback()
        return jsonify({"ok": False, "error": "Migración pendiente: ejecuta flask db upgrade"}), 409


@api_bp.route("/status")
def status() -> tuple[dict[str, str], int]:
    payload: dict[str, str] = {
        "status": "ok",
        "service": "AMPA Julián Nieto",
        "version": "0.1",
    }
    return payload, 200


@api_bp.route("/publicaciones")
def publicaciones() -> tuple[dict[str, object], int]:
    payload: dict[str, object] = {
        "items": [],
        "pagination": {"page": 1, "per_page": 10},
    }
    return payload, 200


@api_bp.route("/calendario/eventos")
def calendario_eventos():
    """
    Endpoint REST para obtener eventos internos del AMPA.

    Parametros opcionales:
        - rango_inicial: Fecha de inicio (formato YYYY-MM-DD)
        - rango_final: Fecha de fin (formato YYYY-MM-DD)
        - limite: Numero maximo de eventos a devolver (por defecto 50)

    Returns:
        JSON con estructura:
        {
            "ok": true/false,
            "eventos": [...],
            "total": int,
            "desde": str,
            "hasta": str,
            "cached": bool
        }
    """
    # Restringir acceso: solo publico si el permiso de eventos esta marcado como publico.
    is_public = Permission.is_key_public("manage_events") or Permission.is_key_public("view_events")
    if not is_public:
        if not current_user.is_authenticated:
            return jsonify({"ok": False, "error": "Acceso no autorizado"}), 403
        if not (
            current_user.has_permission("manage_events")
            or current_user.has_permission("view_events")
            or user_is_privileged(current_user)
        ):
            return jsonify({"ok": False, "error": "No tienes permisos para ver el calendario"}), 403

    rango_inicial = request.args.get("rango_inicial")
    rango_final = request.args.get("rango_final")
    limite = request.args.get("limite", 50, type=int)

    time_min = None
    time_max = None
    range_start = None
    range_end = None

    if rango_inicial:
        try:
            fecha_inicio = datetime.strptime(rango_inicial, "%Y-%m-%d")
            range_start = fecha_inicio
            time_min = fecha_inicio.isoformat() + "Z"
        except ValueError:
            return jsonify({
                "ok": False,
                "error": "Formato de rango_inicial invalido. Use YYYY-MM-DD",
                "eventos": [],
                "total": 0,
            }), 400

    if rango_final:
        try:
            fecha_fin = datetime.strptime(rango_final, "%Y-%m-%d")
            fecha_fin = fecha_fin.replace(hour=23, minute=59, second=59)
            range_end = fecha_fin
            time_max = fecha_fin.isoformat() + "Z"
        except ValueError:
            return jsonify({
                "ok": False,
                "error": "Formato de rango_final invalido. Use YYYY-MM-DD",
                "eventos": [],
                "total": 0,
            }), 400

    if range_start is None:
        range_start = get_local_now().replace(hour=0, minute=0, second=0, microsecond=0)
        time_min = time_min or range_start.isoformat() + "Z"
    if range_end is None:
        range_end = range_start + timedelta(days=180)
        time_max = time_max or range_end.isoformat() + "Z"

    now_dt = get_local_now()
    newest_event_ids: set[int] = set()
    seen_event_ids: set[int] = set()
    if current_user.is_authenticated:
        newest_event_ids = set(_get_upcoming_nine_event_ids(now_dt))
        if newest_event_ids:
            try:
                seen_event_ids = {
                    row.item_id
                    for row in (
                        UserSeenItem.query.filter_by(user_id=current_user.id, item_type="event")
                        .filter(UserSeenItem.item_id.in_(list(newest_event_ids)))
                        .all()
                    )
                }
            except ProgrammingError:
                db.session.rollback()
                seen_event_ids = set()

    events_query = (
        Event.query
        .filter(Event.end_at >= range_start)
        .filter(Event.start_at <= range_end)
        .filter(Event.status == "published")
        .order_by(Event.start_at.asc())
    )
    can_manage = current_user.is_authenticated and (
        current_user.has_permission("manage_events") or user_is_privileged(current_user)
    )
    if not can_manage:
        # Filtrar por visibilidad: solo públicos si no es socio aprobado
        if not current_user.is_authenticated:
            # No autenticado: solo eventos públicos
            events_query = events_query.filter(Event.is_public.is_(True))
        elif not getattr(current_user, "registration_approved", False):
            # Autenticado pero no aprobado: solo eventos públicos
            events_query = events_query.filter(Event.is_public.is_(True))
        # Si es socio aprobado, puede ver todos los eventos (públicos + privados)

    eventos: list[dict] = []
    from app.services.calendar_service import build_calendar_event_url
    for event in events_query.limit(limite).all():
        is_new = bool(
            current_user.is_authenticated
            and event.id in newest_event_ids
            and event.id not in seen_event_ids
        )
        calendar_id = current_app.config.get("GOOGLE_CALENDAR_ID", "primary")
        eventos.append({
            "id": f"event-{event.id}",
            "titulo": event.title,
            "descripcion": event.description_html or "",
            "cover_image": event.cover_image or "",
            "inicio": event.start_at.isoformat(),
            "fin": event.end_at.isoformat(),
            "ubicacion": event.location or "",
            "url": build_calendar_event_url(event.google_event_id, calendar_id=calendar_id) if getattr(event, "google_event_id", None) else None,
            "todo_el_dia": False,
            "categoria": event.category or "general",
            "is_new": is_new,
        })

    respuesta = {
        "ok": True,
        "eventos": eventos,
        "total": len(eventos),
        "desde": time_min,
        "hasta": time_max,
        "cached": False,
    }

    return jsonify(respuesta), 200


@api_bp.route("/calendario/mis-eventos")
@login_required
def calendario_mis_eventos():
    """
    Eventos combinados para socios autenticados:
    - Eventos generales del calendario del AMPA (solo con permiso de eventos).
    - Reuniones de comisiones a las que pertenece el usuario.
    """
    from app.services.calendar_service import build_calendar_event_url

    def _parse_bool(value: str | None) -> bool:
        if value is None:
            return False
        return value.strip().lower() in {"1", "true", "t", "yes", "y", "on", "si", "sí"}

    membership = (
        CommissionMembership.query.filter_by(user_id=current_user.id, is_active=True)
        .join(Commission)
        .filter(Commission.is_active.is_(True))
        .first()
    )
    if not (
        membership
        or current_user.has_permission("view_private_calendar")
    ):
        return jsonify({"ok": False, "error": "No tienes permisos para ver el calendario"}), 403

    rango_inicial = request.args.get("rango_inicial")
    rango_final = request.args.get("rango_final")
    limite = request.args.get("limite", 50, type=int)

    solicitar_todas_reuniones = _parse_bool(request.args.get("todas_reuniones"))
    can_view_all_commissions = (
        current_user.has_permission("view_commissions")
        or current_user.has_permission("manage_commissions")
        or current_user.has_permission("manage_commission_members")
        or user_is_privileged(current_user)
    )
    mostrar_todas_reuniones = bool(solicitar_todas_reuniones and can_view_all_commissions)

    time_min = None
    time_max = None
    range_start = None
    range_end = None

    if rango_inicial:
        try:
            fecha_inicio = datetime.strptime(rango_inicial, "%Y-%m-%d")
            range_start = fecha_inicio
            time_min = fecha_inicio.isoformat() + "Z"
        except ValueError:
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": "Formato de rango_inicial inválido. Use YYYY-MM-DD",
                        "eventos": [],
                        "total": 0,
                    }
                ),
                400,
            )

    if rango_final:
        try:
            fecha_fin = datetime.strptime(rango_final, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
            range_end = fecha_fin
            time_max = fecha_fin.isoformat() + "Z"
        except ValueError:
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": "Formato de rango_final inválido. Use YYYY-MM-DD",
                        "eventos": [],
                        "total": 0,
                    }
                ),
                400,
            )

    if range_start is None:
        range_start = get_local_now().replace(hour=0, minute=0, second=0, microsecond=0)
        time_min = time_min or range_start.isoformat() + "Z"
    if range_end is None:
        range_end = range_start + timedelta(days=180)
        time_max = time_max or range_end.isoformat() + "Z"

    general_events: list[dict] = []
    include_general_events = (
        current_user.has_permission("manage_events")
        or current_user.has_permission("view_events")
        or user_is_privileged(current_user)
    )
    if include_general_events:
        now_dt = get_local_now()
        newest_event_ids: set[int] = set(_get_upcoming_nine_event_ids(now_dt)) if current_user.is_authenticated else set()
        seen_event_ids: set[int] = set()
        if newest_event_ids:
            try:
                seen_event_ids = {
                    row.item_id
                    for row in (
                        UserSeenItem.query.filter_by(user_id=current_user.id, item_type="event")
                        .filter(UserSeenItem.item_id.in_(list(newest_event_ids)))
                        .all()
                    )
                }
            except ProgrammingError:
                db.session.rollback()
                seen_event_ids = set()

        events_query = (
            Event.query
            .filter(Event.end_at >= range_start)
            .filter(Event.start_at <= range_end)
        )
        if not (current_user.has_permission("manage_events") or user_is_privileged(current_user)):
            events_query = events_query.filter(Event.status == "published")
            # Filtrar por visibilidad según estado de aprobación
            if not getattr(current_user, "registration_approved", False):
                events_query = events_query.filter(Event.is_public.is_(True))

        for event in events_query.order_by(Event.start_at.asc()).all():
            is_new = bool(
                current_user.is_authenticated
                and event.id in newest_event_ids
                and event.id not in seen_event_ids
            )
            calendar_id = current_app.config.get("GOOGLE_CALENDAR_ID", "primary")
            general_events.append({
                "id": f"event-{event.id}",
                "titulo": event.title,
                "descripcion": event.description_html or "",
                "cover_image": event.cover_image or "",
                "inicio": event.start_at.isoformat(),
                "fin": event.end_at.isoformat(),
                "ubicacion": event.location or "",
                "url": build_calendar_event_url(event.google_event_id, calendar_id=calendar_id) if getattr(event, "google_event_id", None) else None,
                "todo_el_dia": False,
                "categoria": event.category or "general",
                "is_new": is_new,
            })

    membership_query = (
        CommissionMembership.query.filter_by(user_id=current_user.id, is_active=True)
        .join(Commission)
        .filter(Commission.is_active.is_(True))
    )
    commission_ids = [m.commission_id for m in membership_query.all()]

    meetings_query = (
        CommissionMeeting.query.join(Commission)
        .filter(Commission.is_active.is_(True))
        .filter(CommissionMeeting.end_at >= range_start)
        .filter(CommissionMeeting.start_at <= range_end)
    )
    if not mostrar_todas_reuniones:
        if commission_ids:
            meetings_query = meetings_query.filter(CommissionMeeting.commission_id.in_(commission_ids))
        else:
            meetings_query = meetings_query.filter(sa.false())

    commission_events: list[dict] = []
    for meeting in meetings_query.order_by(CommissionMeeting.start_at.asc()).all():
        project = meeting.project
        event_payload = {
            "id": f"commission-{meeting.id}",
            "titulo": meeting.title,
            "descripcion": meeting.description_html or "",
            "inicio": meeting.start_at.isoformat(),
            "fin": meeting.end_at.isoformat(),
            "ubicacion": meeting.location or "",
            "url": None,
            "todo_el_dia": False,
            "es_comision": True,
            "commission_name": meeting.commission.name if meeting.commission else "",
            "commission_slug": meeting.commission.slug if meeting.commission else "",
            "es_proyecto": bool(project),
            "project_id": project.id if project else None,
            "project_name": project.title if project else "",
        }
        if meeting.google_event_id:
            event_payload["url"] = build_calendar_event_url(meeting.google_event_id)
        commission_events.append(event_payload)

    eventos_combinados = (general_events or []) + commission_events
    eventos_combinados.sort(key=lambda ev: ev.get("inicio") or "")

    respuesta = {
        "ok": True,
        "eventos": eventos_combinados,
        "total": len(eventos_combinados),
        "desde": time_min,
        "hasta": time_max,
        "cached": False,
        "can_toggle_reuniones": bool(can_view_all_commissions),
        "mostrando_todas_reuniones": bool(mostrar_todas_reuniones),
    }

    return jsonify(respuesta), 200


@api_bp.route("/calendario/limpiar-cache", methods=["POST"])
@login_required
def limpiar_cache_calendario():
    """
    Endpoint para limpiar la cache del calendario.
    
    Solo disponible para usuarios autenticados con permisos de administración.
    """
    if not (
        current_user.has_permission("clear_calendar_cache")
        or user_is_privileged(current_user)
    ):
        return jsonify({
            "ok": False,
            "error": "No tienes permisos para realizar esta acci?n",
        }), 403
    
    from app.services.calendar_service import clear_calendar_cache
    clear_calendar_cache()
    
    return jsonify({
        "ok": True,
        "message": "Cache del calendario limpiada correctamente",
    }), 200

@api_bp.route("/comisiones/<int:commission_id>/reuniones")
@login_required
def api_commission_meetings(commission_id: int):
    """
    Endpoint REST para obtener reuniones de una comisión.
    
    Parámetros opcionales:
        - tipo: "all" (defecto), "upcoming", "past"
        - ordenar: "fecha_desc" (defecto), "fecha_asc", "titulo_asc", "titulo_desc"
        - buscar: Buscar en título o ubicación
    
    Returns:
        JSON con estructura:
        {
            "ok": true/false,
            "reuniones": [...],
            "total": int,
            "proximas": int,
            "pasadas": int
        }
    """
    # Validar permisos
    commission = Commission.query.get(commission_id)
    if not commission:
        return jsonify({
            "ok": False,
            "error": "Comisión no encontrada",
        }), 404
    
    membership = CommissionMembership.query.filter_by(
        commission_id=commission_id, 
        user_id=current_user.id, 
        is_active=True
    ).first()
    
    can_view = (
        bool(membership)
        or current_user.has_permission("manage_commission_members")
        or current_user.has_permission("manage_commissions")
        or user_is_privileged(current_user)
    )
    
    if not can_view:
        return jsonify({
            "ok": False,
            "error": "No tienes permisos para ver esta comisión",
        }), 403
    
    # Obtener parámetros
    meeting_type = request.args.get("tipo", "all")
    sort_by = request.args.get("ordenar", "fecha_desc")
    search_query = request.args.get("buscar", "").strip()
    
    # Consulta base
    query = CommissionMeeting.query.filter_by(
        commission_id=commission_id,
        project_id=None,
    )
    
    # Búsqueda
    if search_query:
        query = query.filter(
            (CommissionMeeting.title.ilike(f"%{search_query}%")) |
            (CommissionMeeting.location.ilike(f"%{search_query}%"))
        )
    
    # Filtrado
    now_dt = get_local_now()
    if meeting_type == "upcoming":
        query = query.filter(CommissionMeeting.end_at >= now_dt)
    elif meeting_type == "past":
        query = query.filter(CommissionMeeting.end_at < now_dt)
    
    # Ordenamiento
    if sort_by == "fecha_asc":
        query = query.order_by(CommissionMeeting.start_at.asc())
    elif sort_by == "titulo_asc":
        query = query.order_by(CommissionMeeting.title.asc())
    elif sort_by == "titulo_desc":
        query = query.order_by(CommissionMeeting.title.desc())
    else:
        query = query.order_by(CommissionMeeting.start_at.desc())
    
    meetings = query.all()
    
    # Contar próximas y pasadas
    upcoming_count = sum(1 for m in meetings if m.end_at >= now_dt)
    past_count = sum(1 for m in meetings if m.end_at < now_dt)
    
    # Formatear respuesta
    meetings_data = []
    for meeting in meetings:
        meetings_data.append({
            "id": meeting.id,
            "titulo": meeting.title,
            "descripcion": meeting.description_html,
            "inicio": meeting.start_at.isoformat(),
            "fin": meeting.end_at.isoformat(),
            "ubicacion": meeting.location,
            "es_proxima": meeting.end_at >= now_dt,
            "tiene_acta": bool(meeting.minutes_document),
            "google_event_id": meeting.google_event_id,
        })
    
    return jsonify({
        "ok": True,
        "reuniones": meetings_data,
        "total": len(meetings),
        "proximas": upcoming_count,
        "pasadas": past_count,
    }), 200


def _can_access_commission_files(commission: Commission) -> bool:
    if user_is_privileged(current_user):
        return True
    if current_user.has_permission("manage_commissions"):
        return True
    if current_user.has_permission("manage_commission_members"):
        return True
    if current_user.has_permission("manage_commission_projects"):
        return True
    if current_user.has_permission("view_commissions"):
        return True
    membership = CommissionMembership.query.filter_by(
        commission_id=commission.id,
        user_id=current_user.id,
        is_active=True,
    ).first()
    return membership is not None


def _can_manage_commission_files(commission: Commission) -> bool:
    if user_is_privileged(current_user):
        return True
    if current_user.has_permission("manage_commissions"):
        return True
    membership = CommissionMembership.query.filter_by(
        commission_id=commission.id,
        user_id=current_user.id,
        is_active=True,
    ).first()
    if not membership:
        return False
    return (membership.role or "").strip().lower() == "coordinador"


def _can_view_drive_history(commission: Commission | None = None) -> bool:
    if not (current_user.is_authenticated and current_user.id):
        return False
    if (
        user_is_privileged(current_user)
        or current_user.has_permission("manage_commissions")
        or current_user.has_permission("manage_commission_drive_files")
        or current_user.has_permission("view_commission_drive_history")
    ):
        return True
    if commission is None:
        return False
    return _can_manage_commission_files(commission)


def _display_user_label(user) -> str:
    if not user:
        return ""
    first = (getattr(user, "first_name", None) or "").strip()
    last = (getattr(user, "last_name", None) or "").strip()
    full = (f"{first} {last}").strip()
    return full or (getattr(user, "username", None) or "").strip() or ""


def _drive_file_edit_window() -> timedelta:
    return timedelta(days=2)


def _can_edit_drive_file_record(
    record: DriveFile | None,
    *,
    commission: Commission | None = None,
) -> bool:
    if not (current_user.is_authenticated and current_user.id):
        return False
    # Coordinadores/privilegiados/gestion de comisiones: siempre.
    if (
        user_is_privileged(current_user)
        or current_user.has_permission("manage_commissions")
        or current_user.has_permission("manage_commission_drive_files")
    ):
        return True
    if commission is not None and _can_manage_commission_files(commission):
        return True

    if record is None:
        return False

    if record.uploaded_by_id != current_user.id:
        return False
    if not record.uploaded_at:
        return False
    try:
        return (get_local_now() - record.uploaded_at) <= _drive_file_edit_window()
    except TypeError:
        # Incompatibilidad naive/aware.
        return False


def _upsert_drive_file_from_drive_meta(
    *,
    scope_type: str,
    scope_id: int,
    file_meta: dict,
    actor_user=None,
    actor_label: str | None = None,
    record_external_modifications: bool = True,
) -> DriveFile:
    now_dt = get_local_now()
    drive_file_id = (file_meta.get("id") or "").strip()
    drive_name = (file_meta.get("name") or "").strip() or "-"
    created_time = file_meta.get("createdTime")
    modified_time = file_meta.get("modifiedTime")

    drive_file = DriveFile.query.filter_by(
        scope_type=scope_type,
        scope_id=scope_id,
        drive_file_id=drive_file_id,
    ).first()

    if drive_file is None:
        drive_file = DriveFile(
            scope_type=scope_type,
            scope_id=scope_id,
            drive_file_id=drive_file_id,
            name=drive_name,
            drive_created_time=created_time,
            drive_modified_time=modified_time,
            uploaded_at=now_dt,
            uploaded_by_id=getattr(actor_user, "id", None),
            uploaded_by_label=(actor_label or _display_user_label(actor_user)) or None,
            last_seen_at=now_dt,
        )
        db.session.add(drive_file)
        return drive_file

    changed_name = drive_file.name != drive_name
    changed_modified_time = (drive_file.drive_modified_time or None) != (modified_time or None)

    if record_external_modifications and (changed_name or changed_modified_time):
        event = DriveFileEvent(
            drive_file=drive_file,
            scope_type=scope_type,
            scope_id=scope_id,
            drive_file_id=drive_file_id,
            event_type="external_modify",
            actor_user_id=None,
            actor_label=(actor_label or "Drive"),
            old_name=drive_file.name if changed_name else None,
            new_name=drive_name if changed_name else None,
        )
        db.session.add(event)
        drive_file.modified_at = now_dt
        drive_file.modified_by_id = None
        drive_file.modified_by_label = (actor_label or "Drive")

    drive_file.name = drive_name
    drive_file.drive_created_time = created_time
    drive_file.drive_modified_time = modified_time
    drive_file.last_seen_at = now_dt
    return drive_file


def _drive_file_to_api_dict(
    drive_file: DriveFile,
    *,
    commission: Commission | None = None,
    seen_db_ids: set[int] | None = None,
) -> dict:
    can_manage = False
    if current_user.is_authenticated and current_user.id:
        if (
            user_is_privileged(current_user)
            or current_user.has_permission("manage_commissions")
            or current_user.has_permission("manage_commission_drive_files")
        ):
            can_manage = True
        elif commission is not None and _can_manage_commission_files(commission):
            can_manage = True

    can_edit = _can_edit_drive_file_record(drive_file, commission=commission)

    is_new = False
    if current_user.is_authenticated and current_user.id and seen_db_ids is not None:
        try:
            is_new = int(drive_file.id) not in seen_db_ids
        except Exception:
            is_new = False

    return {
        "dbId": drive_file.id,
        "id": drive_file.drive_file_id,
        "name": drive_file.name,
        "createdTime": drive_file.drive_created_time,
        "modifiedTime": drive_file.drive_modified_time,
        "description": drive_file.description,
        "deletedAt": drive_file.deleted_at.isoformat() if drive_file.deleted_at else None,
        "deletedBy": drive_file.deleted_by_label,
        "modifiedAt": drive_file.modified_at.isoformat() if drive_file.modified_at else None,
        "modifiedBy": drive_file.modified_by_label,
        "uploadedAt": drive_file.uploaded_at.isoformat() if drive_file.uploaded_at else None,
        "uploadedBy": drive_file.uploaded_by_label,
        "isNew": bool(is_new),
        "canDelete": bool(can_edit) and not bool(drive_file.deleted_at),
        "canEditDescription": bool(can_edit) and not bool(drive_file.deleted_at),
        "canRestore": bool(can_manage),
    }


def _parse_resolutions(payload: str | None) -> dict:
    if not payload:
        return {}
    try:
        resolutions = json.loads(payload)
    except ValueError:
        return {}
    if not isinstance(resolutions, dict):
        return {}
    return resolutions


def _resolve_commission_folder(commission: Commission) -> str | None:
    folder_id = ensure_commission_drive_folder(commission)
    return (folder_id or "").strip() or None


def _resolve_project_folder(project: CommissionProject) -> str | None:
    folder_id = ensure_project_drive_folder(project)
    return (folder_id or "").strip() or None


def _assert_file_in_folder(file_id: str, folder_id: str) -> dict | None:
    try:
        meta = get_drive_file_meta(file_id)
    except Exception:
        return None
    parents = meta.get("parents") or []
    if folder_id not in parents:
        return None
    return meta


@api_bp.route("/drive-files/commissions/<int:commission_id>", methods=["GET"])
@login_required
def commission_drive_files_list(commission_id: int):
    commission = Commission.query.get_or_404(commission_id)
    if not _can_access_commission_files(commission):
        abort(403)
    folder_id = _resolve_commission_folder(commission)
    if not folder_id:
        return jsonify({"ok": False, "error": "No se pudo resolver la carpeta de Drive."}), 500

    shared_drive_id = current_app.config.get("GOOGLE_DRIVE_SHARED_DRIVE_ID") or None
    try:
        drive_files = list_drive_files(folder_id, drive_id=shared_drive_id, trashed=False)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 500

    records: list[DriveFile] = []
    for f in drive_files:
        record = _upsert_drive_file_from_drive_meta(
            scope_type="commission",
            scope_id=commission.id,
            file_meta=f,
            actor_label="Drive",
            record_external_modifications=True,
        )
        # Si estaba marcado como eliminado, pero vuelve a aparecer activo en Drive, lo consideramos restaurado externo.
        if record.deleted_at:
            record.deleted_at = None
            record.deleted_by_id = None
            record.deleted_by_label = None
            db.session.add(
                DriveFileEvent(
                    drive_file=record,
                    scope_type="commission",
                    scope_id=commission.id,
                    drive_file_id=record.drive_file_id,
                    event_type="restore",
                    actor_label="Drive",
                )
            )
        records.append(record)

    db.session.commit()

    seen_db_ids: set[int] = set()
    try:
        db_ids = [r.id for r in records if getattr(r, "id", None)]
        if db_ids:
            seen_db_ids = {
                row.item_id
                for row in (
                    UserSeenItem.query.filter_by(user_id=current_user.id, item_type="drivefile")
                    .filter(UserSeenItem.item_id.in_(db_ids))
                    .all()
                )
            }
    except ProgrammingError:
        db.session.rollback()
        seen_db_ids = set()

    return (
        jsonify(
            {
                "ok": True,
                "files": [_drive_file_to_api_dict(r, commission=commission, seen_db_ids=seen_db_ids) for r in records],
            }
        ),
        200,
    )


@api_bp.route("/drive-files/commissions/<int:commission_id>", methods=["POST"])
@csrf.exempt
@login_required
def commission_drive_files_upload(commission_id: int):
    commission = Commission.query.get_or_404(commission_id)
    if not _can_access_commission_files(commission):
        abort(403)

    files = request.files.getlist("files")
    if not files:
        return jsonify({"ok": False, "error": "No se recibieron archivos."}), 400

    description = (request.form.get("description") or "").strip()

    folder_id = _resolve_commission_folder(commission)
    if not folder_id:
        return jsonify({"ok": False, "error": "No se pudo resolver la carpeta de Drive."}), 500

    shared_drive_id = current_app.config.get("GOOGLE_DRIVE_SHARED_DRIVE_ID") or None
    resolutions = _parse_resolutions(request.form.get("resolutions"))
    existing_map: dict[str, dict] = {}
    conflicts: list[dict] = []

    overwrite_capabilities: dict[str, bool] = {}

    for file in files:
        name = (file.filename or "").strip()
        if not name:
            continue
        try:
            existing = find_drive_file_by_name(folder_id, name, drive_id=shared_drive_id)
        except Exception as exc:  # noqa: BLE001
            return jsonify({"ok": False, "error": str(exc)}), 500
        existing_map[name] = existing
        if existing:
            record = DriveFile.query.filter_by(
                scope_type="commission",
                scope_id=commission.id,
                drive_file_id=(existing.get("id") or "").strip(),
            ).first()
            overwrite_capabilities[name] = _can_edit_drive_file_record(record, commission=commission)
        if existing and name not in resolutions:
            conflicts.append(
                {
                    "name": name,
                    "createdTime": existing.get("createdTime"),
                    "modifiedTime": existing.get("modifiedTime"),
                    "canOverwrite": bool(overwrite_capabilities.get(name, False)),
                }
            )

    if conflicts:
        return jsonify({"ok": False, "conflicts": conflicts}), 409

    uploaded: list[dict] = []
    skipped: list[str] = []

    for file in files:
        name = (file.filename or "").strip()
        if not name:
            continue
        existing = existing_map.get(name)
        decision = resolutions.get(name, {}) if existing else {}
        action = (decision.get("action") or "").lower()
        try:
            if existing:
                if action == "skip":
                    skipped.append(name)
                    continue
                if action == "overwrite":
                    if not overwrite_capabilities.get(name, False):
                        return jsonify(
                            {
                                "ok": False,
                                "error": "No tienes permiso para sobrescribir este archivo. Solo el autor puede hacerlo durante 2 días; después, coordinadores/administradores.",
                            }
                        ), 403
                    result = upload_drive_file(
                        folder_id,
                        file,
                        drive_id=shared_drive_id,
                        overwrite_file_id=existing.get("id"),
                    )
                elif action == "rename":
                    new_name = (decision.get("new_name") or "").strip()
                    if not new_name:
                        return jsonify({"ok": False, "error": f"Nombre nuevo invalido para {name}."}), 400
                    result = upload_drive_file(
                        folder_id,
                        file,
                        name=new_name,
                        drive_id=shared_drive_id,
                    )
                else:
                    skipped.append(name)
                    continue
            else:
                result = upload_drive_file(folder_id, file, drive_id=shared_drive_id)
        except Exception as exc:  # noqa: BLE001
            return jsonify({"ok": False, "error": str(exc)}), 500

        uploaded.append(
            {
                "id": result.get("id"),
                "name": result.get("name"),
                "createdTime": result.get("createdTime"),
                "modifiedTime": result.get("modifiedTime"),
            }
        )

        # Persistir/actualizar en BD
        record = _upsert_drive_file_from_drive_meta(
            scope_type="commission",
            scope_id=commission.id,
            file_meta=result,
            actor_user=current_user,
            actor_label=_display_user_label(current_user),
            record_external_modifications=False,
        )
        record.description = description or None
        record.deleted_at = None
        record.deleted_by_id = None
        record.deleted_by_label = None
        now_dt = get_local_now()
        if existing and action == "overwrite":
            record.modified_at = now_dt
            record.modified_by_id = current_user.id
            record.modified_by_label = _display_user_label(current_user) or None
            db.session.add(
                DriveFileEvent(
                    drive_file=record,
                    scope_type="commission",
                    scope_id=commission.id,
                    drive_file_id=record.drive_file_id,
                    event_type="overwrite",
                    actor_user_id=current_user.id,
                    actor_label=_display_user_label(current_user) or None,
                )
            )
        else:
            record.uploaded_at = record.uploaded_at or now_dt
            record.uploaded_by_id = record.uploaded_by_id or current_user.id
            record.uploaded_by_label = record.uploaded_by_label or (_display_user_label(current_user) or None)
            db.session.add(
                DriveFileEvent(
                    drive_file=record,
                    scope_type="commission",
                    scope_id=commission.id,
                    drive_file_id=record.drive_file_id,
                    event_type="upload",
                    actor_user_id=current_user.id,
                    actor_label=_display_user_label(current_user) or None,
                )
            )

    db.session.commit()

    return jsonify({"ok": True, "uploaded": uploaded, "skipped": skipped}), 200


@api_bp.route("/drive-files/commissions/<int:commission_id>/download/<file_id>", methods=["GET"])
@login_required
def commission_drive_files_download(commission_id: int, file_id: str):
    commission = Commission.query.get_or_404(commission_id)
    if not _can_access_commission_files(commission):
        abort(403)

    folder_id = _resolve_commission_folder(commission)
    if not folder_id:
        return jsonify({"ok": False, "error": "No se pudo resolver la carpeta de Drive."}), 500

    meta = _assert_file_in_folder(file_id, folder_id)
    if meta is None:
        return jsonify({"ok": False, "error": "Archivo no encontrado."}), 404

    try:
        content, meta = download_drive_file(file_id)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 500

    return send_file(
        content,
        as_attachment=True,
        download_name=meta.get("name") or "archivo",
        mimetype=meta.get("mimeType") or "application/octet-stream",
    )


@api_bp.route("/drive-files/commissions/<int:commission_id>/delete/<file_id>", methods=["DELETE"])
@csrf.exempt
@login_required
def commission_drive_files_delete(commission_id: int, file_id: str):
    commission = Commission.query.get_or_404(commission_id)
    record = DriveFile.query.filter_by(
        scope_type="commission",
        scope_id=commission.id,
        drive_file_id=file_id,
    ).first()
    if not _can_edit_drive_file_record(record, commission=commission):
        return jsonify(
            {
                "ok": False,
                "error": "No tienes permiso para eliminar este archivo. Solo el autor puede hacerlo durante 2 días; después, coordinadores/administradores.",
            }
        ), 403

    folder_id = _resolve_commission_folder(commission)
    if not folder_id:
        return jsonify({"ok": False, "error": "No se pudo resolver la carpeta de Drive."}), 500

    meta = _assert_file_in_folder(file_id, folder_id)
    if meta is None:
        return jsonify({"ok": False, "error": "Archivo no encontrado."}), 404

    try:
        delete_drive_file(file_id)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 500

    now_dt = get_local_now()
    if record is None:
        record = DriveFile(
            scope_type="commission",
            scope_id=commission.id,
            drive_file_id=file_id,
            name=(meta.get("name") or "-").strip() or "-",
            drive_created_time=meta.get("createdTime"),
            drive_modified_time=meta.get("modifiedTime"),
        )
        db.session.add(record)
    record.deleted_at = now_dt
    record.deleted_by_id = current_user.id
    record.deleted_by_label = _display_user_label(current_user) or None
    db.session.add(
        DriveFileEvent(
            drive_file=record,
            scope_type="commission",
            scope_id=commission.id,
            drive_file_id=file_id,
            event_type="trash",
            actor_user_id=current_user.id,
            actor_label=_display_user_label(current_user) or None,
        )
    )
    db.session.commit()

    return jsonify({"ok": True, "deleted": {"id": file_id}}), 200


@api_bp.route("/drive-files/projects/<int:project_id>", methods=["GET"])
@login_required
def project_drive_files_list(project_id: int):
    project = CommissionProject.query.get_or_404(project_id)
    commission = project.commission or Commission.query.get(project.commission_id)
    if commission is None:
        return jsonify({"ok": False, "error": "Comision no encontrada."}), 404
    if not _can_access_commission_files(commission):
        abort(403)

    folder_id = _resolve_project_folder(project)
    if not folder_id:
        return jsonify({"ok": False, "error": "No se pudo resolver la carpeta de Drive."}), 500

    shared_drive_id = current_app.config.get("GOOGLE_DRIVE_SHARED_DRIVE_ID") or None
    try:
        drive_files = list_drive_files(folder_id, drive_id=shared_drive_id, trashed=False)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 500

    records: list[DriveFile] = []
    for f in drive_files:
        record = _upsert_drive_file_from_drive_meta(
            scope_type="project",
            scope_id=project.id,
            file_meta=f,
            actor_label="Drive",
            record_external_modifications=True,
        )
        if record.deleted_at:
            record.deleted_at = None
            record.deleted_by_id = None
            record.deleted_by_label = None
            db.session.add(
                DriveFileEvent(
                    drive_file=record,
                    scope_type="project",
                    scope_id=project.id,
                    drive_file_id=record.drive_file_id,
                    event_type="restore",
                    actor_label="Drive",
                )
            )
        records.append(record)

    db.session.commit()

    seen_db_ids: set[int] = set()
    try:
        db_ids = [r.id for r in records if getattr(r, "id", None)]
        if db_ids:
            seen_db_ids = {
                row.item_id
                for row in (
                    UserSeenItem.query.filter_by(user_id=current_user.id, item_type="drivefile")
                    .filter(UserSeenItem.item_id.in_(db_ids))
                    .all()
                )
            }
    except ProgrammingError:
        db.session.rollback()
        seen_db_ids = set()

    return (
        jsonify(
            {
                "ok": True,
                "files": [_drive_file_to_api_dict(r, commission=commission, seen_db_ids=seen_db_ids) for r in records],
            }
        ),
        200,
    )


@api_bp.route("/drive-files/projects/<int:project_id>", methods=["POST"])
@csrf.exempt
@login_required
def project_drive_files_upload(project_id: int):
    project = CommissionProject.query.get_or_404(project_id)
    commission = project.commission or Commission.query.get(project.commission_id)
    if commission is None:
        return jsonify({"ok": False, "error": "Comision no encontrada."}), 404
    if not _can_access_commission_files(commission):
        abort(403)

    files = request.files.getlist("files")
    if not files:
        return jsonify({"ok": False, "error": "No se recibieron archivos."}), 400

    description = (request.form.get("description") or "").strip()

    folder_id = _resolve_project_folder(project)
    if not folder_id:
        return jsonify({"ok": False, "error": "No se pudo resolver la carpeta de Drive."}), 500

    shared_drive_id = current_app.config.get("GOOGLE_DRIVE_SHARED_DRIVE_ID") or None
    resolutions = _parse_resolutions(request.form.get("resolutions"))
    existing_map: dict[str, dict] = {}
    conflicts: list[dict] = []

    overwrite_capabilities: dict[str, bool] = {}

    for file in files:
        name = (file.filename or "").strip()
        if not name:
            continue
        try:
            existing = find_drive_file_by_name(folder_id, name, drive_id=shared_drive_id)
        except Exception as exc:  # noqa: BLE001
            return jsonify({"ok": False, "error": str(exc)}), 500
        existing_map[name] = existing
        if existing:
            record = DriveFile.query.filter_by(
                scope_type="project",
                scope_id=project.id,
                drive_file_id=(existing.get("id") or "").strip(),
            ).first()
            overwrite_capabilities[name] = _can_edit_drive_file_record(record, commission=commission)
        if existing and name not in resolutions:
            conflicts.append(
                {
                    "name": name,
                    "createdTime": existing.get("createdTime"),
                    "modifiedTime": existing.get("modifiedTime"),
                    "canOverwrite": bool(overwrite_capabilities.get(name, False)),
                }
            )

    if conflicts:
        return jsonify({"ok": False, "conflicts": conflicts}), 409

    uploaded: list[dict] = []
    skipped: list[str] = []

    for file in files:
        name = (file.filename or "").strip()
        if not name:
            continue
        existing = existing_map.get(name)
        decision = resolutions.get(name, {}) if existing else {}
        action = (decision.get("action") or "").lower()
        try:
            if existing:
                if action == "skip":
                    skipped.append(name)
                    continue
                if action == "overwrite":
                    if not overwrite_capabilities.get(name, False):
                        return jsonify(
                            {
                                "ok": False,
                                "error": "No tienes permiso para sobrescribir este archivo. Solo el autor puede hacerlo durante 2 días; después, coordinadores/administradores.",
                            }
                        ), 403
                    result = upload_drive_file(
                        folder_id,
                        file,
                        drive_id=shared_drive_id,
                        overwrite_file_id=existing.get("id"),
                    )
                elif action == "rename":
                    new_name = (decision.get("new_name") or "").strip()
                    if not new_name:
                        return jsonify({"ok": False, "error": f"Nombre nuevo invalido para {name}."}), 400
                    result = upload_drive_file(
                        folder_id,
                        file,
                        name=new_name,
                        drive_id=shared_drive_id,
                    )
                else:
                    skipped.append(name)
                    continue
            else:
                result = upload_drive_file(folder_id, file, drive_id=shared_drive_id)
        except Exception as exc:  # noqa: BLE001
            return jsonify({"ok": False, "error": str(exc)}), 500

        uploaded.append(
            {
                "id": result.get("id"),
                "name": result.get("name"),
                "createdTime": result.get("createdTime"),
                "modifiedTime": result.get("modifiedTime"),
            }
        )

        record = _upsert_drive_file_from_drive_meta(
            scope_type="project",
            scope_id=project.id,
            file_meta=result,
            actor_user=current_user,
            actor_label=_display_user_label(current_user),
            record_external_modifications=False,
        )
        record.description = description or None
        record.deleted_at = None
        record.deleted_by_id = None
        record.deleted_by_label = None
        now_dt = get_local_now()
        if existing and action == "overwrite":
            record.modified_at = now_dt
            record.modified_by_id = current_user.id
            record.modified_by_label = _display_user_label(current_user) or None
            db.session.add(
                DriveFileEvent(
                    drive_file=record,
                    scope_type="project",
                    scope_id=project.id,
                    drive_file_id=record.drive_file_id,
                    event_type="overwrite",
                    actor_user_id=current_user.id,
                    actor_label=_display_user_label(current_user) or None,
                )
            )
        else:
            record.uploaded_at = record.uploaded_at or now_dt
            record.uploaded_by_id = record.uploaded_by_id or current_user.id
            record.uploaded_by_label = record.uploaded_by_label or (_display_user_label(current_user) or None)
            db.session.add(
                DriveFileEvent(
                    drive_file=record,
                    scope_type="project",
                    scope_id=project.id,
                    drive_file_id=record.drive_file_id,
                    event_type="upload",
                    actor_user_id=current_user.id,
                    actor_label=_display_user_label(current_user) or None,
                )
            )

    db.session.commit()

    return jsonify({"ok": True, "uploaded": uploaded, "skipped": skipped}), 200


@api_bp.route("/drive-files/projects/<int:project_id>/download/<file_id>", methods=["GET"])
@login_required
def project_drive_files_download(project_id: int, file_id: str):
    project = CommissionProject.query.get_or_404(project_id)
    commission = project.commission or Commission.query.get(project.commission_id)
    if commission is None:
        return jsonify({"ok": False, "error": "Comision no encontrada."}), 404
    if not _can_access_commission_files(commission):
        abort(403)

    folder_id = _resolve_project_folder(project)
    if not folder_id:
        return jsonify({"ok": False, "error": "No se pudo resolver la carpeta de Drive."}), 500

    meta = _assert_file_in_folder(file_id, folder_id)
    if meta is None:
        return jsonify({"ok": False, "error": "Archivo no encontrado."}), 404

    try:
        content, meta = download_drive_file(file_id)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 500

    return send_file(
        content,
        as_attachment=True,
        download_name=meta.get("name") or "archivo",
        mimetype=meta.get("mimeType") or "application/octet-stream",
    )


@api_bp.route("/drive-files/projects/<int:project_id>/delete/<file_id>", methods=["DELETE"])
@csrf.exempt
@login_required
def project_drive_files_delete(project_id: int, file_id: str):
    project = CommissionProject.query.get_or_404(project_id)
    commission = project.commission or Commission.query.get(project.commission_id)
    if commission is None:
        return jsonify({"ok": False, "error": "Comision no encontrada."}), 404
    record = DriveFile.query.filter_by(
        scope_type="project",
        scope_id=project.id,
        drive_file_id=file_id,
    ).first()
    if not _can_edit_drive_file_record(record, commission=commission):
        return jsonify(
            {
                "ok": False,
                "error": "No tienes permiso para eliminar este archivo. Solo el autor puede hacerlo durante 2 días; después, coordinadores/administradores.",
            }
        ), 403

    folder_id = _resolve_project_folder(project)
    if not folder_id:
        return jsonify({"ok": False, "error": "No se pudo resolver la carpeta de Drive."}), 500

    meta = _assert_file_in_folder(file_id, folder_id)
    if meta is None:
        return jsonify({"ok": False, "error": "Archivo no encontrado."}), 404

    try:
        delete_drive_file(file_id)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 500

    now_dt = get_local_now()
    if record is None:
        record = DriveFile(
            scope_type="project",
            scope_id=project.id,
            drive_file_id=file_id,
            name=(meta.get("name") or "-").strip() or "-",
            drive_created_time=meta.get("createdTime"),
            drive_modified_time=meta.get("modifiedTime"),
        )
        db.session.add(record)
    record.deleted_at = now_dt
    record.deleted_by_id = current_user.id
    record.deleted_by_label = _display_user_label(current_user) or None
    db.session.add(
        DriveFileEvent(
            drive_file=record,
            scope_type="project",
            scope_id=project.id,
            drive_file_id=file_id,
            event_type="trash",
            actor_user_id=current_user.id,
            actor_label=_display_user_label(current_user) or None,
        )
    )
    db.session.commit()

    return jsonify({"ok": True, "deleted": {"id": file_id}}), 200


@api_bp.route("/drive-files/commissions/<int:commission_id>/history", methods=["GET"])
@login_required
def commission_drive_files_history(commission_id: int):
    commission = Commission.query.get_or_404(commission_id)
    if not _can_view_drive_history(commission):
        abort(403)
    # Aun asi, valida que el usuario pueda acceder a la comision.
    if not _can_access_commission_files(commission):
        abort(403)

    records = (
        DriveFile.query.filter_by(scope_type="commission", scope_id=commission.id)
        .order_by(DriveFile.deleted_at.desc().nullslast(), DriveFile.updated_at.desc().nullslast())
        .all()
    )
    return jsonify({"ok": True, "files": [_drive_file_to_api_dict(r, commission=commission) for r in records]}), 200


@api_bp.route("/drive-files/projects/<int:project_id>/history", methods=["GET"])
@login_required
def project_drive_files_history(project_id: int):
    project = CommissionProject.query.get_or_404(project_id)
    commission = project.commission or Commission.query.get(project.commission_id)
    if commission is None:
        return jsonify({"ok": False, "error": "Comision no encontrada."}), 404
    if not _can_view_drive_history(commission):
        abort(403)
    if not _can_access_commission_files(commission):
        abort(403)

    records = (
        DriveFile.query.filter_by(scope_type="project", scope_id=project.id)
        .order_by(DriveFile.deleted_at.desc().nullslast(), DriveFile.updated_at.desc().nullslast())
        .all()
    )
    return jsonify({"ok": True, "files": [_drive_file_to_api_dict(r, commission=commission) for r in records]}), 200


@api_bp.route("/drive-files/commissions/<int:commission_id>/restore/<file_id>", methods=["POST"])
@csrf.exempt
@login_required
def commission_drive_files_restore(commission_id: int, file_id: str):
    commission = Commission.query.get_or_404(commission_id)
    if not (
        _can_manage_commission_files(commission)
        or current_user.has_permission("manage_commission_drive_files")
        or current_user.has_permission("manage_commissions")
        or user_is_privileged(current_user)
    ):
        abort(403)
    if not _can_access_commission_files(commission):
        abort(403)

    folder_id = _resolve_commission_folder(commission)
    if not folder_id:
        return jsonify({"ok": False, "error": "No se pudo resolver la carpeta de Drive."}), 500

    meta = _assert_file_in_folder(file_id, folder_id)
    if meta is None:
        return jsonify({"ok": False, "error": "Archivo no encontrado."}), 404

    try:
        restore_drive_file(file_id)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 500

    now_dt = get_local_now()
    record = DriveFile.query.filter_by(
        scope_type="commission",
        scope_id=commission.id,
        drive_file_id=file_id,
    ).first()
    if record is None:
        record = DriveFile(
            scope_type="commission",
            scope_id=commission.id,
            drive_file_id=file_id,
            name=(meta.get("name") or "-").strip() or "-",
            drive_created_time=meta.get("createdTime"),
            drive_modified_time=meta.get("modifiedTime"),
        )
        db.session.add(record)
    record.deleted_at = None
    record.deleted_by_id = None
    record.deleted_by_label = None
    record.modified_at = now_dt
    record.modified_by_id = current_user.id
    record.modified_by_label = _display_user_label(current_user) or None
    db.session.add(
        DriveFileEvent(
            drive_file=record,
            scope_type="commission",
            scope_id=commission.id,
            drive_file_id=file_id,
            event_type="restore",
            actor_user_id=current_user.id,
            actor_label=_display_user_label(current_user) or None,
        )
    )
    db.session.commit()
    return jsonify({"ok": True, "restored": {"id": file_id}}), 200


@api_bp.route("/drive-files/projects/<int:project_id>/restore/<file_id>", methods=["POST"])
@csrf.exempt
@login_required
def project_drive_files_restore(project_id: int, file_id: str):
    project = CommissionProject.query.get_or_404(project_id)
    commission = project.commission or Commission.query.get(project.commission_id)
    if commission is None:
        return jsonify({"ok": False, "error": "Comision no encontrada."}), 404
    if not (
        _can_manage_commission_files(commission)
        or current_user.has_permission("manage_commission_drive_files")
        or current_user.has_permission("manage_commissions")
        or user_is_privileged(current_user)
    ):
        abort(403)
    if not _can_access_commission_files(commission):
        abort(403)

    folder_id = _resolve_project_folder(project)
    if not folder_id:
        return jsonify({"ok": False, "error": "No se pudo resolver la carpeta de Drive."}), 500

    meta = _assert_file_in_folder(file_id, folder_id)
    if meta is None:
        return jsonify({"ok": False, "error": "Archivo no encontrado."}), 404

    try:
        restore_drive_file(file_id)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 500

    now_dt = get_local_now()
    record = DriveFile.query.filter_by(
        scope_type="project",
        scope_id=project.id,
        drive_file_id=file_id,
    ).first()
    if record is None:
        record = DriveFile(
            scope_type="project",
            scope_id=project.id,
            drive_file_id=file_id,
            name=(meta.get("name") or "-").strip() or "-",
            drive_created_time=meta.get("createdTime"),
            drive_modified_time=meta.get("modifiedTime"),
        )
        db.session.add(record)
    record.deleted_at = None
    record.deleted_by_id = None
    record.deleted_by_label = None
    record.modified_at = now_dt
    record.modified_by_id = current_user.id
    record.modified_by_label = _display_user_label(current_user) or None
    db.session.add(
        DriveFileEvent(
            drive_file=record,
            scope_type="project",
            scope_id=project.id,
            drive_file_id=file_id,
            event_type="restore",
            actor_user_id=current_user.id,
            actor_label=_display_user_label(current_user) or None,
        )
    )
    db.session.commit()
    return jsonify({"ok": True, "restored": {"id": file_id}}), 200


@api_bp.route("/drive-files/commissions/<int:commission_id>/description/<file_id>", methods=["POST"])
@csrf.exempt
@login_required
def commission_drive_files_update_description(commission_id: int, file_id: str):
    commission = Commission.query.get_or_404(commission_id)

    payload = request.get_json(silent=True) or {}
    description = (payload.get("description") or "").strip()
    if description is None:
        description = ""

    folder_id = _resolve_commission_folder(commission)
    if not folder_id:
        return jsonify({"ok": False, "error": "No se pudo resolver la carpeta de Drive."}), 500
    meta = _assert_file_in_folder(file_id, folder_id)
    if meta is None:
        return jsonify({"ok": False, "error": "Archivo no encontrado."}), 404

    record = DriveFile.query.filter_by(
        scope_type="commission",
        scope_id=commission.id,
        drive_file_id=file_id,
    ).first()

    if not _can_edit_drive_file_record(record, commission=commission):
        return jsonify(
            {
                "ok": False,
                "error": "No tienes permiso para modificar este archivo. Solo el autor puede hacerlo durante 2 días; después, coordinadores/administradores.",
            }
        ), 403
    if record is None:
        record = DriveFile(
            scope_type="commission",
            scope_id=commission.id,
            drive_file_id=file_id,
            name=(meta.get("name") or "-").strip() or "-",
            drive_created_time=meta.get("createdTime"),
            drive_modified_time=meta.get("modifiedTime"),
        )
        db.session.add(record)

    old_description = record.description
    record.description = description
    now_dt = get_local_now()
    record.modified_at = now_dt
    record.modified_by_id = current_user.id
    record.modified_by_label = _display_user_label(current_user) or None
    db.session.add(
        DriveFileEvent(
            drive_file=record,
            scope_type="commission",
            scope_id=commission.id,
            drive_file_id=file_id,
            event_type="description_update",
            actor_user_id=current_user.id,
            actor_label=_display_user_label(current_user) or None,
            old_description=old_description,
            new_description=description,
        )
    )
    db.session.commit()
    return jsonify({"ok": True, "file": _drive_file_to_api_dict(record, commission=commission)}), 200


@api_bp.route("/drive-files/projects/<int:project_id>/description/<file_id>", methods=["POST"])
@csrf.exempt
@login_required
def project_drive_files_update_description(project_id: int, file_id: str):
    project = CommissionProject.query.get_or_404(project_id)
    commission = project.commission or Commission.query.get(project.commission_id)
    if commission is None:
        return jsonify({"ok": False, "error": "Comision no encontrada."}), 404

    payload = request.get_json(silent=True) or {}
    description = (payload.get("description") or "").strip()
    if description is None:
        description = ""

    folder_id = _resolve_project_folder(project)
    if not folder_id:
        return jsonify({"ok": False, "error": "No se pudo resolver la carpeta de Drive."}), 500
    meta = _assert_file_in_folder(file_id, folder_id)
    if meta is None:
        return jsonify({"ok": False, "error": "Archivo no encontrado."}), 404

    record = DriveFile.query.filter_by(
        scope_type="project",
        scope_id=project.id,
        drive_file_id=file_id,
    ).first()

    if not _can_edit_drive_file_record(record, commission=commission):
        return jsonify(
            {
                "ok": False,
                "error": "No tienes permiso para modificar este archivo. Solo el autor puede hacerlo durante 2 días; después, coordinadores/administradores.",
            }
        ), 403
    if record is None:
        record = DriveFile(
            scope_type="project",
            scope_id=project.id,
            drive_file_id=file_id,
            name=(meta.get("name") or "-").strip() or "-",
            drive_created_time=meta.get("createdTime"),
            drive_modified_time=meta.get("modifiedTime"),
        )
        db.session.add(record)

    old_description = record.description
    record.description = description
    now_dt = get_local_now()
    record.modified_at = now_dt
    record.modified_by_id = current_user.id
    record.modified_by_label = _display_user_label(current_user) or None
    db.session.add(
        DriveFileEvent(
            drive_file=record,
            scope_type="project",
            scope_id=project.id,
            drive_file_id=file_id,
            event_type="description_update",
            actor_user_id=current_user.id,
            actor_label=_display_user_label(current_user) or None,
            old_description=old_description,
            new_description=description,
        )
    )
    db.session.commit()
    return jsonify({"ok": True, "file": _drive_file_to_api_dict(record, commission=commission)}), 200

    return jsonify({"ok": True, "deleted": {"id": file_id}}), 200
