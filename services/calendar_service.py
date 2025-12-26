"""
Servicio de Google Calendar para el AMPA Julián Nieto.

Proporciona acceso al calendario de Google del AMPA mediante OAuth,
con sistema de cache interno para optimizar llamadas a la API.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from html import unescape

from flask import current_app
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google_auth_oauthlib.flow import InstalledAppFlow


# Scopes unificados para Drive y Calendar
UNIFIED_SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/calendar.events",
]

# Cache interno para eventos del calendario
_events_cache: dict[str, Any] = {
    "data": None,
    "timestamp": 0,
    "ttl": 600,  # 10 minutos por defecto
}

_calendar_service = None


def _get_unified_credentials() -> Credentials | None:
    """
    Obtiene credenciales OAuth unificadas para Drive y Calendar.
    
    Reutiliza el sistema de tokens existente pero con scopes ampliados.
    Si el token no tiene los scopes necesarios, solicita reautorización.
    """
    try:
        token_path = Path(current_app.root_path) / "token_drive.json"
        credentials_path = Path(current_app.config.get(
            "GOOGLE_DRIVE_OAUTH_CREDENTIALS_FILE",
            Path(current_app.root_path) / "credentials_drive_oauth.json"
        ))
        
        # Intentar cargar token desde variable de entorno si no existe el archivo
        token_env = current_app.config.get("GOOGLE_DRIVE_TOKEN_JSON")
        if token_env and not token_path.exists():
            try:
                token_path.parent.mkdir(parents=True, exist_ok=True)
                token_path.write_text(token_env, encoding="utf-8")
            except Exception as exc:
                current_app.logger.warning(
                    "No se pudo escribir token_drive.json: %s", exc
                )

        # Intentar cargar credenciales desde variable de entorno
        creds_json = current_app.config.get("GOOGLE_DRIVE_OAUTH_CREDENTIALS_JSON")
        if creds_json and not credentials_path.exists():
            try:
                credentials_path.parent.mkdir(parents=True, exist_ok=True)
                credentials_path.write_text(creds_json, encoding="utf-8")
            except Exception as exc:
                current_app.logger.warning(
                    "No se pudo escribir credentials_drive_oauth.json: %s", exc
                )

        creds = None
        if token_path.exists():
            creds = Credentials.from_authorized_user_file(str(token_path), UNIFIED_SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception as e:
                    current_app.logger.warning(
                        "Error refrescando token, intentando reautorizar: %s", e
                    )
                    creds = None
            
            if not creds:
                if not credentials_path.exists():
                    current_app.logger.warning(
                        "No se encontró el archivo de credenciales OAuth."
                    )
                    return None
                
                # Verificar que las credenciales no son de demostración
                creds_content = credentials_path.read_text(encoding="utf-8")
                if "TU_CLIENT_ID" in creds_content or "TU_SECRET" in creds_content:
                    current_app.logger.warning(
                        "Las credenciales contienen valores de demostración."
                    )
                    return None
                
                # Flujo de autorización local (solo para desarrollo)
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(credentials_path),
                    UNIFIED_SCOPES,
                )
                creds = flow.run_local_server(port=0)
            
            # Guardar token actualizado
            with open(token_path, "w", encoding="utf-8") as token:
                token.write(creds.to_json())

        return creds
    
    except Exception as exc:
        current_app.logger.error(
            "Error obteniendo credenciales unificadas: %s", exc
        )
        return None


def _get_calendar_service():
    """
    Inicializa o reutiliza el cliente de Google Calendar API v3.
    """
    global _calendar_service
    
    if _calendar_service is not None:
        return _calendar_service
    
    creds = _get_unified_credentials()
    if not creds:
        return None
    
    try:
        _calendar_service = build("calendar", "v3", credentials=creds)
        return _calendar_service
    except Exception as exc:
        current_app.logger.error(
            "Error inicializando Google Calendar service: %s", exc
        )
        return None


def _clean_html(text: str | None) -> str:
    """
    Limpia HTML de una cadena de texto.
    """
    if not text:
        return ""
    
    # Decodificar entidades HTML
    text = unescape(text)
    
    # Eliminar etiquetas HTML
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<p[^>]*>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</p>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    
    # Limpiar espacios múltiples y saltos de línea
    text = re.sub(r'\n\s*\n', '\n\n', text)
    text = text.strip()
    
    return text


def _parse_datetime(dt_dict: dict | None) -> str | None:
    """
    Convierte el formato de fecha/hora de Google Calendar a ISO 8601.
    
    Google Calendar puede devolver:
    - {"dateTime": "2025-01-15T10:00:00+01:00"} para eventos con hora
    - {"date": "2025-01-15"} para eventos de día completo
    """
    if not dt_dict:
        return None
    
    # Evento con hora específica
    if "dateTime" in dt_dict:
        return dt_dict["dateTime"]
    
    # Evento de día completo (solo fecha)
    if "date" in dt_dict:
        return f"{dt_dict['date']}T00:00:00"
    
    return None


def _format_event(event: dict) -> dict:
    """
    Transforma un evento de Google Calendar al formato JSON limpio.
    
    Formato de salida:
    {
        "id": "",
        "titulo": "",
        "descripcion": "",
        "inicio": "",
        "fin": "",
        "ubicacion": "",
        "url": "",
        "todo_el_dia": false
    }
    """
    event_id = event.get("id", "")
    
    # Determinar si es evento de día completo
    start = event.get("start", {})
    end = event.get("end", {})
    is_all_day = "date" in start and "dateTime" not in start
    
    # Generar URL para abrir en Google Calendar
    html_link = event.get("htmlLink", "")
    
    return {
        "id": event_id,
        "titulo": event.get("summary", "Sin título"),
        "descripcion": _clean_html(event.get("description")),
        "inicio": _parse_datetime(start),
        "fin": _parse_datetime(end),
        "ubicacion": event.get("location", ""),
        "url": html_link,
        "todo_el_dia": is_all_day,
        "color": event.get("colorId", ""),
        "organizador": event.get("organizer", {}).get("displayName", ""),
    }


def get_calendar_events(
    calendar_id: str | None = None,
    time_min: str | None = None,
    time_max: str | None = None,
    max_results: int = 50,
    use_cache: bool = True,
) -> dict:
    """
    Obtiene eventos del calendario de Google del AMPA.
    
    Args:
        calendar_id: ID del calendario (por defecto usa GOOGLE_CALENDAR_ID de config)
        time_min: Fecha mínima en formato ISO 8601 (por defecto: hoy)
        time_max: Fecha máxima en formato ISO 8601 (por defecto: hoy + 6 meses)
        max_results: Número máximo de eventos a devolver
        use_cache: Si usar la cache interna
    
    Returns:
        {
            "ok": True/False,
            "eventos": [...],
            "total": int,
            "desde": str,
            "hasta": str,
            "cached": bool,
            "error": str (si ok=False)
        }
    """
    global _events_cache
    
    # Obtener configuración
    if not calendar_id:
        calendar_id = current_app.config.get("GOOGLE_CALENDAR_ID", "primary")
    
    cache_ttl = current_app.config.get("GOOGLE_CALENDAR_CACHE_TTL", 600)
    _events_cache["ttl"] = cache_ttl
    
    # Calcular rango de fechas por defecto
    now = datetime.utcnow()
    if not time_min:
        time_min = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat() + "Z"
    if not time_max:
        time_max = (now + timedelta(days=180)).isoformat() + "Z"
    
    # Verificar cache
    cache_key = f"{calendar_id}:{time_min}:{time_max}:{max_results}"
    if use_cache and _events_cache["data"]:
        cache_age = time.time() - _events_cache["timestamp"]
        if cache_age < _events_cache["ttl"] and _events_cache.get("key") == cache_key:
            current_app.logger.debug(
                "Devolviendo eventos desde cache (edad: %.1fs)", cache_age
            )
            cached_result = _events_cache["data"].copy()
            cached_result["cached"] = True
            return cached_result
    
    # Obtener servicio de Calendar
    service = _get_calendar_service()
    if not service:
        # Si no hay servicio pero hay cache, devolver cache aunque esté expirada
        if _events_cache["data"]:
            current_app.logger.warning(
                "Servicio de Calendar no disponible, usando cache expirada"
            )
            cached_result = _events_cache["data"].copy()
            cached_result["cached"] = True
            cached_result["stale"] = True
            return cached_result
        
        return {
            "ok": False,
            "error": "Servicio de Google Calendar no disponible",
            "eventos": [],
            "total": 0,
            "desde": time_min,
            "hasta": time_max,
            "cached": False,
        }
    
    try:
        # Llamar a la API de Google Calendar
        events_result = service.events().list(
            calendarId=calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
        ).execute()
        
        raw_events = events_result.get("items", [])
        
        # Transformar eventos al formato limpio
        eventos = [_format_event(event) for event in raw_events]
        
        result = {
            "ok": True,
            "eventos": eventos,
            "total": len(eventos),
            "desde": time_min,
            "hasta": time_max,
            "cached": False,
            "calendar_name": events_result.get("summary", ""),
        }
        
        # Actualizar cache
        _events_cache["data"] = result.copy()
        _events_cache["timestamp"] = time.time()
        _events_cache["key"] = cache_key
        
        current_app.logger.info(
            "Obtenidos %d eventos del calendario %s", len(eventos), calendar_id
        )
        
        return result
        
    except HttpError as error:
        error_msg = f"Error de API de Google Calendar: {error}"
        current_app.logger.error(error_msg)
        
        # Devolver cache si está disponible
        if _events_cache["data"]:
            current_app.logger.warning("Usando cache tras error de API")
            cached_result = _events_cache["data"].copy()
            cached_result["cached"] = True
            cached_result["stale"] = True
            cached_result["api_error"] = str(error)
            return cached_result
        
        return {
            "ok": False,
            "error": error_msg,
            "eventos": [],
            "total": 0,
            "desde": time_min,
            "hasta": time_max,
            "cached": False,
        }
    
    except Exception as exc:
        error_msg = f"Error inesperado: {exc}"
        current_app.logger.error(error_msg)
        
        if _events_cache["data"]:
            cached_result = _events_cache["data"].copy()
            cached_result["cached"] = True
            cached_result["stale"] = True
            return cached_result
        
        return {
            "ok": False,
            "error": error_msg,
            "eventos": [],
            "total": 0,
            "desde": time_min,
            "hasta": time_max,
            "cached": False,
        }


def clear_calendar_cache() -> None:
    """
    Limpia la cache de eventos del calendario.
    
    Útil cuando se necesita forzar una actualización desde la API.
    """
    global _events_cache
    _events_cache["data"] = None
    _events_cache["timestamp"] = 0
    _events_cache["key"] = None
    current_app.logger.info("Cache del calendario limpiada")


def get_upcoming_events(limit: int = 10) -> list[dict]:
    """
    Obtiene los próximos N eventos desde hoy.
    
    Función de conveniencia para el frontend.
    """
    result = get_calendar_events(max_results=limit)
    if result.get("ok"):
        return result.get("eventos", [])
    return []


def regenerate_token_with_calendar_scope() -> dict:
    """
    Regenera el token OAuth incluyendo el scope de Calendar.
    
    IMPORTANTE: Esta función debe ejecutarse UNA SOLA VEZ en local
    para generar un token con los permisos de Calendar.
    Después, el token resultante debe subirse a Render.
    
    Returns:
        {"ok": True/False, "message": str, "token_path": str}
    """
    try:
        credentials_path = Path(current_app.root_path) / "credentials_drive_oauth.json"
        token_path = Path(current_app.root_path) / "token_drive.json"
        
        if not credentials_path.exists():
            return {
                "ok": False,
                "message": "No se encontró el archivo de credenciales OAuth",
            }
        
        # Eliminar token existente si existe
        if token_path.exists():
            token_path.unlink()
            current_app.logger.info("Token existente eliminado")
        
        # Crear nuevo flujo con scopes unificados
        flow = InstalledAppFlow.from_client_secrets_file(
            str(credentials_path),
            UNIFIED_SCOPES,
        )
        
        # Ejecutar autorización local
        creds = flow.run_local_server(port=0)
        
        # Guardar nuevo token
        with open(token_path, "w", encoding="utf-8") as token:
            token.write(creds.to_json())
        
        current_app.logger.info(
            "Token regenerado con scopes: %s", UNIFIED_SCOPES
        )
        
        return {
            "ok": True,
            "message": "Token regenerado exitosamente con permisos de Calendar",
            "token_path": str(token_path),
            "scopes": UNIFIED_SCOPES,
        }
        
    except Exception as exc:
        error_msg = f"Error regenerando token: {exc}"
        current_app.logger.error(error_msg)
        return {
            "ok": False,
            "message": error_msg,
        }
