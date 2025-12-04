from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
from datetime import datetime

from app.models import user_is_privileged

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
