from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
from datetime import datetime, timedelta
import sqlalchemy as sa

from app.models import user_is_privileged, CommissionMeeting, CommissionMembership, Commission

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
    Endpoint REST para obtener eventos del calendario de Google del AMPA.
    
    Parámetros opcionales:
        - rango_inicial: Fecha de inicio (formato YYYY-MM-DD)
        - rango_final: Fecha de fin (formato YYYY-MM-DD)
        - limite: Número máximo de eventos a devolver (por defecto 50)
    
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
    from app.services.calendar_service import get_calendar_events
    
    # Obtener parámetros de la request
    rango_inicial = request.args.get("rango_inicial")
    rango_final = request.args.get("rango_final")
    limite = request.args.get("limite", 50, type=int)
    
    # Convertir formato de fecha si se proporciona
    time_min = None
    time_max = None
    
    if rango_inicial:
        try:
            fecha_inicio = datetime.strptime(rango_inicial, "%Y-%m-%d")
            time_min = fecha_inicio.isoformat() + "Z"
        except ValueError:
            return jsonify({
                "ok": False,
                "error": "Formato de rango_inicial inválido. Use YYYY-MM-DD",
                "eventos": [],
                "total": 0,
            }), 400
    
    if rango_final:
        try:
            fecha_fin = datetime.strptime(rango_final, "%Y-%m-%d")
            # Ajustar al final del día
            fecha_fin = fecha_fin.replace(hour=23, minute=59, second=59)
            time_max = fecha_fin.isoformat() + "Z"
        except ValueError:
            return jsonify({
                "ok": False,
                "error": "Formato de rango_final inválido. Use YYYY-MM-DD",
                "eventos": [],
                "total": 0,
            }), 400
    
    # Obtener eventos del servicio de calendario
    resultado = get_calendar_events(
        time_min=time_min,
        time_max=time_max,
        max_results=limite,
    )
    
    if resultado.get("ok"):
        return jsonify(resultado), 200
    else:
        return jsonify(resultado), 503


@api_bp.route("/calendario/mis-eventos")
@login_required
def calendario_mis_eventos():
    """
    Eventos combinados para socios autenticados:
    - Eventos generales del calendario del AMPA (Google Calendar).
    - Reuniones de comisiones a las que pertenece el usuario o, si tiene permiso, todas.
    """
    from app.services.calendar_service import get_calendar_events

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

    calendar_result = get_calendar_events(time_min=time_min, time_max=time_max, max_results=limite)
    general_events = calendar_result.get("eventos") if calendar_result.get("ok") else []

    include_all_commissions = user_is_privileged(current_user) or current_user.has_permission(
        "view_all_commission_calendar"
    )
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
    if not include_all_commissions:
        if commission_ids:
            meetings_query = meetings_query.filter(CommissionMeeting.commission_id.in_(commission_ids))
        else:
            meetings_query = meetings_query.filter(sa.false())

    commission_events: list[dict] = []
    for meeting in meetings_query.order_by(CommissionMeeting.start_at.asc()).all():
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
        }
        if meeting.google_event_id:
            event_payload["url"] = f"https://calendar.google.com/calendar/event?eid={meeting.google_event_id}"
        commission_events.append(event_payload)

    eventos_combinados = (general_events or []) + commission_events
    eventos_combinados.sort(key=lambda ev: ev.get("inicio") or "")

    respuesta = {
        "ok": True,
        "eventos": eventos_combinados,
        "total": len(eventos_combinados),
        "desde": time_min,
        "hasta": time_max,
        "cached": calendar_result.get("cached", False),
    }
    if not calendar_result.get("ok"):
        respuesta["calendar_error"] = calendar_result.get("error")

    return jsonify(respuesta), 200


@api_bp.route("/calendario/limpiar-cache", methods=["POST"])
@login_required
def limpiar_cache_calendario():
    """
    Endpoint para limpiar la cache del calendario.
    
    Solo disponible para usuarios autenticados con permisos de administración.
    """
    if not user_is_privileged(current_user):
        return jsonify({
            "ok": False,
            "error": "No tienes permisos para realizar esta acción",
        }), 403
    
    from app.services.calendar_service import clear_calendar_cache
    clear_calendar_cache()
    
    return jsonify({
        "ok": True,
        "message": "Cache del calendario limpiada correctamente",
    }), 200
