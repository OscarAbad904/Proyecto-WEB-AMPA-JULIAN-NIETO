from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
from datetime import datetime, timedelta
import sqlalchemy as sa

from app.models import (
    Permission,
    user_is_privileged,
    CommissionMeeting,
    CommissionMembership,
    Commission,
    Event,
)

api_bp = Blueprint("api", __name__)


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
        range_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        time_min = time_min or range_start.isoformat() + "Z"
    if range_end is None:
        range_end = range_start + timedelta(days=180)
        time_max = time_max or range_end.isoformat() + "Z"

    events_query = (
        Event.query
        .filter(Event.end_at >= range_start)
        .filter(Event.start_at <= range_end)
        .order_by(Event.start_at.asc())
    )
    can_manage = current_user.is_authenticated and (
        current_user.has_permission("manage_events") or user_is_privileged(current_user)
    )
    if not can_manage:
        events_query = events_query.filter(Event.status == "published")

    eventos: list[dict] = []
    for event in events_query.limit(limite).all():
        eventos.append({
            "id": f"event-{event.id}",
            "titulo": event.title,
            "descripcion": event.description_html or "",
            "inicio": event.start_at.isoformat(),
            "fin": event.end_at.isoformat(),
            "ubicacion": event.location or "",
            "url": None,
            "todo_el_dia": False,
            "categoria": event.category or "general",
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
        range_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
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
        events_query = (
            Event.query
            .filter(Event.end_at >= range_start)
            .filter(Event.start_at <= range_end)
        )
        if not (current_user.has_permission("manage_events") or user_is_privileged(current_user)):
            events_query = events_query.filter(Event.status == "published")

        for event in events_query.order_by(Event.start_at.asc()).all():
            general_events.append({
                "id": f"event-{event.id}",
                "titulo": event.title,
                "descripcion": event.description_html or "",
                "inicio": event.start_at.isoformat(),
                "fin": event.end_at.isoformat(),
                "ubicacion": event.location or "",
                "url": None,
                "todo_el_dia": False,
                "categoria": event.category or "general",
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
    now_dt = datetime.utcnow()
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
