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
)

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

    return jsonify(
        {
            "ok": True,
            "posts_unread": int(posts_unread),
            "events_unread": int(events_unread),
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

    if item_type not in {"post", "event"}:
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
        files = list_drive_files(folder_id, drive_id=shared_drive_id)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 500
    return jsonify({"ok": True, "files": files}), 200


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

    folder_id = _resolve_commission_folder(commission)
    if not folder_id:
        return jsonify({"ok": False, "error": "No se pudo resolver la carpeta de Drive."}), 500

    shared_drive_id = current_app.config.get("GOOGLE_DRIVE_SHARED_DRIVE_ID") or None
    resolutions = _parse_resolutions(request.form.get("resolutions"))
    existing_map: dict[str, dict] = {}
    conflicts: list[dict] = []

    for file in files:
        name = (file.filename or "").strip()
        if not name:
            continue
        try:
            existing = find_drive_file_by_name(folder_id, name, drive_id=shared_drive_id)
        except Exception as exc:  # noqa: BLE001
            return jsonify({"ok": False, "error": str(exc)}), 500
        existing_map[name] = existing
        if existing and name not in resolutions:
            conflicts.append(
                {
                    "name": name,
                    "createdTime": existing.get("createdTime"),
                    "modifiedTime": existing.get("modifiedTime"),
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
    if not _can_manage_commission_files(commission):
        abort(403)

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
        files = list_drive_files(folder_id, drive_id=shared_drive_id)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 500
    return jsonify({"ok": True, "files": files}), 200


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

    folder_id = _resolve_project_folder(project)
    if not folder_id:
        return jsonify({"ok": False, "error": "No se pudo resolver la carpeta de Drive."}), 500

    shared_drive_id = current_app.config.get("GOOGLE_DRIVE_SHARED_DRIVE_ID") or None
    resolutions = _parse_resolutions(request.form.get("resolutions"))
    existing_map: dict[str, dict] = {}
    conflicts: list[dict] = []

    for file in files:
        name = (file.filename or "").strip()
        if not name:
            continue
        try:
            existing = find_drive_file_by_name(folder_id, name, drive_id=shared_drive_id)
        except Exception as exc:  # noqa: BLE001
            return jsonify({"ok": False, "error": str(exc)}), 500
        existing_map[name] = existing
        if existing and name not in resolutions:
            conflicts.append(
                {
                    "name": name,
                    "createdTime": existing.get("createdTime"),
                    "modifiedTime": existing.get("modifiedTime"),
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
    if not _can_manage_commission_files(commission):
        abort(403)

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

    return jsonify({"ok": True, "deleted": {"id": file_id}}), 200
