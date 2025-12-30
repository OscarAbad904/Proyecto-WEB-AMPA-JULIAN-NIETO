"""
Servicio de Google Calendar para el AMPA Julián Nieto.

Proporciona acceso al calendario de Google del AMPA mediante OAuth,
con sistema de cache interno para optimizar llamadas a la API.
"""

from __future__ import annotations

import base64
import json
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from html import unescape
from urllib.parse import parse_qs, urlparse

from flask import current_app
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google_auth_oauthlib.flow import InstalledAppFlow

from config import unwrap_fernet_json_layers


# Scopes unificados para Drive, Calendar y Gmail (envío)
UNIFIED_SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/gmail.send",
]

# Cache interno para eventos del calendario
_events_cache: dict[str, Any] = {
    "data": None,
    "timestamp": 0,
    "ttl": 600,  # 10 minutos por defecto
}

_calendar_service = None


def _get_unified_credentials() -> Credentials | None:
    """Obtiene credenciales OAuth unificadas para Drive, Calendar y Gmail.

    - En producción (DEBUG=False) NO inicia flujos interactivos.
    - En Render debe existir GOOGLE_DRIVE_TOKEN_JSON con refresh_token.
    """
    try:
        base_path = Path(current_app.config.get("ROOT_PATH") or current_app.root_path)
        token_path = base_path / "token_drive.json"
        credentials_path = Path(
            current_app.config.get(
                "GOOGLE_DRIVE_OAUTH_CREDENTIALS_FILE",
                str(base_path / "credentials_drive_oauth.json"),
            )
        )

        token_env = (current_app.config.get("GOOGLE_DRIVE_TOKEN_JSON") or "").strip()
        creds_json = (current_app.config.get("GOOGLE_DRIVE_OAUTH_CREDENTIALS_JSON") or "").strip()

        # Materializar archivos desde variables de entorno (útil en Render con FS efímero)
        if token_env and not token_path.exists():
            try:
                token_path.parent.mkdir(parents=True, exist_ok=True)
                token_path.write_text(token_env, encoding="utf-8")
            except Exception as exc:
                current_app.logger.warning("No se pudo escribir token_drive.json: %s", exc)

        if creds_json and not credentials_path.exists():
            try:
                credentials_path.parent.mkdir(parents=True, exist_ok=True)
                credentials_path.write_text(creds_json, encoding="utf-8")
            except Exception as exc:
                current_app.logger.warning("No se pudo escribir credentials_drive_oauth.json: %s", exc)

        # Cargar token JSON (preferimos env; si no, disco). Si el env está cifrado o es inválido,
        # intentamos desencriptar o hacer fallback a token_drive.json.
        token_payload: dict[str, Any] | None = None
        token_env_json: str | None = None

        if token_env:
            token_env_json = token_env
            try:
                token_payload = json.loads(token_env_json)
            except Exception:
                # Puede venir encriptado por Fernet (p.ej. guardado desde el gestor)
                token_env_json = unwrap_fernet_json_layers(token_env)
                if token_env_json:
                    try:
                        token_payload = json.loads(token_env_json)
                    except Exception as exc:
                        current_app.logger.error(
                            "GOOGLE_DRIVE_TOKEN_JSON no es JSON válido (ni tras desencriptar): %s",
                            exc,
                        )
                        token_payload = None
                else:
                    current_app.logger.warning(
                        "GOOGLE_DRIVE_TOKEN_JSON no es JSON válido; intentando usar token_drive.json si existe."
                    )

        if token_payload is None and token_path.exists():
            try:
                token_payload = json.loads(token_path.read_text(encoding="utf-8"))
            except Exception as exc:
                current_app.logger.error("token_drive.json no es JSON válido: %s", exc)
                return None

        if token_payload:
            # Validar refresh_token (obligatorio en Render)
            if not token_payload.get("refresh_token"):
                current_app.logger.error(
                    "El token OAuth no incluye refresh_token. Regenera el token con "
                    "'flask regenerate-google-token' (acceso offline + consent) y actualiza "
                    "GOOGLE_DRIVE_TOKEN_JSON."
                )
                # Fallback: si existe token en disco, puede ser distinto y válido.
                if token_path.exists() and not token_env:
                    return None

                if token_path.exists():
                    try:
                        disk_payload = json.loads(token_path.read_text(encoding="utf-8"))
                        if disk_payload.get("refresh_token"):
                            token_payload = disk_payload
                    except Exception:
                        return None
                if not token_payload.get("refresh_token"):
                    return None

            # Validar scopes si vienen en el JSON
            token_scopes = token_payload.get("scopes")
            if isinstance(token_scopes, str):
                token_scopes_list = token_scopes.split()
            elif isinstance(token_scopes, list):
                token_scopes_list = token_scopes
            else:
                token_scopes_list = []

            if token_scopes_list:
                missing_scopes = sorted(set(UNIFIED_SCOPES) - set(token_scopes_list))
                if missing_scopes:
                    current_app.logger.error(
                        "El token OAuth no incluye los scopes requeridos (%s). Regenera el token "
                        "con 'flask regenerate-google-token' y actualiza GOOGLE_DRIVE_TOKEN_JSON.",
                        ", ".join(missing_scopes),
                    )

                    # Fallback: si el env trae un token viejo pero en disco hay uno nuevo, probarlo.
                    if token_path.exists():
                        try:
                            disk_payload = json.loads(token_path.read_text(encoding="utf-8"))
                            disk_scopes = disk_payload.get("scopes")
                            if isinstance(disk_scopes, str):
                                disk_scopes_list = disk_scopes.split()
                            elif isinstance(disk_scopes, list):
                                disk_scopes_list = disk_scopes
                            else:
                                disk_scopes_list = []

                            disk_missing = sorted(set(UNIFIED_SCOPES) - set(disk_scopes_list))
                            if not disk_missing and disk_payload.get("refresh_token"):
                                token_payload = disk_payload
                                missing_scopes = []
                        except Exception:
                            pass

                    if missing_scopes:
                        current_app.logger.warning(
                            "El token OAuth actual no tiene todos los scopes; algunas operaciones pueden fallar."
                        )
            else:
                current_app.logger.warning(
                    "El token OAuth no incluye el campo 'scopes'. Si hay errores 403, regenera el token."
                )

        creds: Credentials | None = None
        if token_payload:
            creds = Credentials.from_authorized_user_info(token_payload, UNIFIED_SCOPES)
        elif token_path.exists():
            creds = Credentials.from_authorized_user_file(str(token_path), UNIFIED_SCOPES)

        if creds and not creds.valid:
            if not creds.refresh_token:
                current_app.logger.error(
                    "El token OAuth no es válido y no tiene refresh_token. Regenera el token con "
                    "'flask regenerate-google-token'."
                )
                return None
            try:
                creds.refresh(Request())
            except RefreshError as exc:
                current_app.logger.error(
                    "No se pudo refrescar el token OAuth (posible revocación/invalid_grant). "
                    "Regenera el token con 'flask regenerate-google-token'. Detalle: %s",
                    exc,
                )
                if current_app.debug:
                    current_app.logger.warning(
                        "Token OAuth inválido; intentando reautorización interactiva en modo debug."
                    )
                    creds = None
                else:
                    return None
            except Exception as exc:
                current_app.logger.error("Error inesperado refrescando token OAuth: %s", exc)
                return None

            # Persistir token actualizado (best-effort)
            if creds:
                try:
                    with open(token_path, "w", encoding="utf-8") as token_file:
                        token_file.write(creds.to_json())
                except Exception as exc:
                    current_app.logger.warning("No se pudo persistir token_drive.json: %s", exc)

        if not creds:
            if not credentials_path.exists():
                current_app.logger.warning("No se encontró el archivo de credenciales OAuth.")
                return None

            # Verificar que las credenciales no son de demostración
            creds_content = credentials_path.read_text(encoding="utf-8")
            if "TU_CLIENT_ID" in creds_content or "TU_SECRET" in creds_content:
                current_app.logger.warning("Las credenciales contienen valores de demostración.")
                return None

            if not current_app.debug:
                current_app.logger.error(
                    "No hay un token OAuth válido para Google (Drive/Calendar/Gmail). En producción "
                    "no se puede iniciar el flujo interactivo. Configura GOOGLE_DRIVE_TOKEN_JSON "
                    "(con refresh_token) y GOOGLE_DRIVE_OAUTH_CREDENTIALS_JSON/FILE."
                )
                return None

            flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), UNIFIED_SCOPES)
            creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")

            if not getattr(creds, "refresh_token", None):
                current_app.logger.error(
                    "El token generado no incluye refresh_token. Revoca el acceso de la app en tu "
                    "cuenta Google y vuelve a ejecutar 'flask regenerate-google-token'."
                )
                return None

            try:
                with open(token_path, "w", encoding="utf-8") as token_file:
                    token_file.write(creds.to_json())
            except Exception as exc:
                current_app.logger.warning("No se pudo persistir token_drive.json: %s", exc)

        return creds

    except Exception as exc:
        current_app.logger.error("Error obteniendo credenciales unificadas: %s", exc)
        return None


def get_unified_credentials() -> Credentials | None:
    """API pública para reutilizar credenciales unificadas en otros servicios."""
    return _get_unified_credentials()


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


def _is_commission_meeting_event(event: dict) -> bool:
    props = event.get("extendedProperties") or {}
    if not isinstance(props, dict):
        return False
    private = props.get("private") or {}
    if not isinstance(private, dict):
        return False
    if private.get("type") == "commission_meeting":
        return True
    return bool(private.get("commission_id"))


def _get_commission_calendar_id() -> str:
    return (
        current_app.config.get("GOOGLE_CALENDAR_COMMISSIONS_ID")
        or current_app.config.get("GOOGLE_CALENDAR_ID", "primary")
    )


def _get_calendar_timezone() -> str | None:
    tz = current_app.config.get("GOOGLE_CALENDAR_TIMEZONE")
    if not tz:
        return "Europe/Madrid"
    tz_value = str(tz).strip()
    return tz_value or "Europe/Madrid"


def _build_commission_meeting_payload(meeting, commission) -> dict:
    description = _clean_html(getattr(meeting, "description_html", None))
    commission_name = getattr(commission, "name", None) if commission else None
    project = getattr(meeting, "project", None)
    project_title = getattr(project, "title", None) if project else None
    header_parts = []
    if commission_name:
        header_parts.append(f"Comision: {commission_name}")
    if project_title:
        header_parts.append(f"Proyecto: {project_title}")
    if header_parts:
        header = "\n".join(header_parts)
        description = f"{header}\n\n{description}" if description else header

    start_at = getattr(meeting, "start_at", None)
    end_at = getattr(meeting, "end_at", None)
    payload = {
        "summary": getattr(meeting, "title", "") or "Reunion",
        "description": description or "",
        "location": getattr(meeting, "location", None) or "",
        "start": {"dateTime": start_at.isoformat()} if start_at else {},
        "end": {"dateTime": end_at.isoformat()} if end_at else {},
        "visibility": "private",
        "extendedProperties": {
            "private": {
                "type": "project_meeting" if project_title else "commission_meeting",
                "commission_id": str(getattr(commission, "id", "") or ""),
                "project_id": str(getattr(project, "id", "") or "") if project_title else "",
                "meeting_id": str(getattr(meeting, "id", "") or ""),
            }
        },
    }
    tz = _get_calendar_timezone()
    if tz:
        if payload["start"]:
            payload["start"]["timeZone"] = tz
        if payload["end"]:
            payload["end"]["timeZone"] = tz
    return payload


def _decode_calendar_eid(eid: str) -> tuple[str | None, str | None]:
    if not eid:
        return None, None
    try:
        padded = eid + "=" * (-len(eid) % 4)
        decoded = base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8")
        if " " in decoded:
            event_id, calendar_id = decoded.split(" ", 1)
            return event_id, calendar_id
        return decoded, None
    except Exception:
        return None, None


def _extract_calendar_event_id(raw_value: str | None) -> str | None:
    if not raw_value:
        return None
    value = raw_value.strip()
    if value.startswith(("http://", "https://")):
        parsed = urlparse(value)
        eid_values = parse_qs(parsed.query).get("eid") or []
        if not eid_values:
            return None
        event_id, _ = _decode_calendar_eid(eid_values[0])
        return event_id
    return value


def build_calendar_event_url(event_id: str | None, calendar_id: str | None = None) -> str | None:
    if not event_id:
        return None
    if event_id.startswith(("http://", "https://")):
        return event_id
    calendar_id = calendar_id or _get_commission_calendar_id()
    if not calendar_id:
        return None
    raw = f"{event_id} {calendar_id}"
    eid = base64.urlsafe_b64encode(raw.encode("utf-8")).decode("utf-8").rstrip("=")
    return f"https://calendar.google.com/calendar/event?eid={eid}"


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
        raw_events = [event for event in raw_events if not _is_commission_meeting_event(event)]
        
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


def create_commission_meeting_event(meeting, commission, calendar_id: str | None = None) -> dict:
    service = _get_calendar_service()
    if not service:
        return {"ok": False, "error": "Servicio de Google Calendar no disponible"}

    target_calendar_id = calendar_id or _get_commission_calendar_id()
    payload = _build_commission_meeting_payload(meeting, commission)
    try:
        created = service.events().insert(
            calendarId=target_calendar_id,
            body=payload,
        ).execute()
        event_id = created.get("id")
        if not event_id:
            return {"ok": False, "error": "Google Calendar no devolvio el ID del evento"}
        return {
            "ok": True,
            "event_id": event_id,
            "html_link": created.get("htmlLink"),
            "calendar_id": target_calendar_id,
        }
    except HttpError as error:
        current_app.logger.error("Error creando evento de comision en Google Calendar: %s", error)
        return {"ok": False, "error": str(error)}
    except Exception as exc:
        current_app.logger.error("Error inesperado creando evento de comision: %s", exc)
        return {"ok": False, "error": str(exc)}


def update_commission_meeting_event(
    event_id: str,
    meeting,
    commission,
    calendar_id: str | None = None,
) -> dict:
    service = _get_calendar_service()
    if not service:
        return {"ok": False, "error": "Servicio de Google Calendar no disponible"}

    target_calendar_id = calendar_id or _get_commission_calendar_id()
    payload = _build_commission_meeting_payload(meeting, commission)
    try:
        updated = service.events().patch(
            calendarId=target_calendar_id,
            eventId=event_id,
            body=payload,
        ).execute()
        return {
            "ok": True,
            "event_id": updated.get("id", event_id),
            "html_link": updated.get("htmlLink"),
            "calendar_id": target_calendar_id,
        }
    except HttpError as error:
        status = getattr(error, "status_code", None)
        if status is None:
            status = getattr(getattr(error, "resp", None), "status", None)
        current_app.logger.error("Error actualizando evento de comision en Google Calendar: %s", error)
        return {"ok": False, "error": str(error), "status": status}
    except Exception as exc:
        current_app.logger.error("Error inesperado actualizando evento de comision: %s", exc)
        return {"ok": False, "error": str(exc)}


def sync_commission_meeting_to_calendar(meeting, commission) -> dict:
    raw_value = getattr(meeting, "google_event_id", None)
    event_id = _extract_calendar_event_id(raw_value)
    if raw_value and not event_id:
        return {"ok": False, "error": "No se pudo extraer el ID del evento de Google Calendar"}
    if event_id:
        result = update_commission_meeting_event(event_id, meeting, commission)
        if result.get("ok"):
            return result
        if result.get("status") in {404, 410}:
            return create_commission_meeting_event(meeting, commission)
        return result
    return create_commission_meeting_event(meeting, commission)


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
    Regenera el token OAuth con scopes unificados (Drive/Calendar/Gmail send).
    
    IMPORTANTE: Esta función debe ejecutarse UNA SOLA VEZ en local
    para generar un token con refresh_token y los permisos unificados.
    Después, el token resultante debe subirse a Render.
    
    Returns:
        {"ok": True/False, "message": str, "token_path": str}
    """
    try:
        base_path = Path(current_app.config.get("ROOT_PATH") or current_app.root_path)
        token_path = base_path / "token_drive.json"

        credentials_cfg = current_app.config.get("GOOGLE_DRIVE_OAUTH_CREDENTIALS_FILE")
        if credentials_cfg:
            credentials_path = Path(credentials_cfg)
            if not credentials_path.is_absolute():
                credentials_path = base_path / credentials_path
        else:
            credentials_path = base_path / "credentials_drive_oauth.json"

        creds_json = current_app.config.get("GOOGLE_DRIVE_OAUTH_CREDENTIALS_JSON")
        if creds_json and not credentials_path.exists():
            try:
                credentials_path.parent.mkdir(parents=True, exist_ok=True)
                credentials_path.write_text(creds_json, encoding="utf-8")
            except Exception as exc:
                current_app.logger.warning(
                    "No se pudo escribir credentials_drive_oauth.json: %s", exc
                )
        
        if not credentials_path.exists():
            return {
                "ok": False,
                "message": (
                    "No se encontró el archivo de credenciales OAuth "
                    f"en {credentials_path} (configura GOOGLE_DRIVE_OAUTH_CREDENTIALS_FILE "
                    "o GOOGLE_DRIVE_OAUTH_CREDENTIALS_JSON)."
                ),
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
        
        # Ejecutar autorización local (forzar refresh_token con acceso offline)
        creds = flow.run_local_server(
            port=0,
            access_type="offline",
            prompt="consent",
            include_granted_scopes="true",
        )

        granted_scopes = sorted(list(getattr(creds, "scopes", None) or []))
        missing_scopes = sorted(set(UNIFIED_SCOPES) - set(granted_scopes))

        if not getattr(creds, "refresh_token", None):
            return {
                "ok": False,
                "message": (
                    "El token generado no incluye refresh_token. "
                    "Revoca el acceso de esta app en tu cuenta de Google y vuelve a ejecutar "
                    "'flask regenerate-google-token'."
                ),
            }
        
        # Guardar nuevo token (aunque falte algún scope, para facilitar diagnóstico)
        with open(token_path, "w", encoding="utf-8") as token:
            token.write(creds.to_json())

        if missing_scopes:
            return {
                "ok": False,
                "message": (
                    "El token se generó, pero Google NO concedió todos los scopes requeridos. "
                    f"Faltan: {', '.join(missing_scopes)}. "
                    "Revisa en Google Cloud Console: (1) que Gmail API esté habilitada, "
                    "(2) que tu OAuth Consent Screen permita el scope gmail.send (app en testing + usuario en Test users), "
                    "y (3) revoca el acceso de la app en tu cuenta Google y vuelve a autorizar."
                ),
                "token_path": str(token_path),
                "scopes_granted": granted_scopes,
                "scopes_required": UNIFIED_SCOPES,
            }
        
        current_app.logger.info(
            "Token regenerado. Scopes concedidos: %s", granted_scopes
        )
        
        return {
            "ok": True,
            "message": "Token regenerado exitosamente con scopes unificados (Drive/Calendar/Gmail send)",
            "token_path": str(token_path),
            "scopes_granted": granted_scopes,
            "scopes_required": UNIFIED_SCOPES,
        }
        
    except Exception as exc:
        error_msg = f"Error regenerando token: {exc}"
        current_app.logger.error(error_msg)
        return {
            "ok": False,
            "message": error_msg,
        }


def delete_commission_meeting_event(event_id: str, calendar_id: str | None = None) -> dict:
    """
    Elimina un evento de reunión de comisión del calendario de Google.
    
    Args:
        event_id: ID del evento a eliminar
        calendar_id: ID del calendario (por defecto, el configurado en GOOGLE_CALENDAR_ID)
    
    Returns:
        {"ok": True/False, "error": str (si ok=False)}
    """
    service = _get_calendar_service()
    if not service:
        return {"ok": False, "error": "Servicio de Google Calendar no disponible"}

    extracted = _extract_calendar_event_id(event_id)
    if not extracted:
        return {"ok": False, "error": "No se pudo extraer el ID del evento de Google Calendar"}

    target_calendar_id = calendar_id or _get_commission_calendar_id()
    
    try:
        service.events().delete(
            calendarId=target_calendar_id,
            eventId=extracted,
        ).execute()
        
        current_app.logger.info(
            "Evento de comisión eliminado del calendario de Google: %s", event_id
        )
        return {
            "ok": True,
            "event_id": extracted,
        }
    except HttpError as error:
        current_app.logger.error("Error eliminando evento de comisión de Google Calendar: %s", error)
        return {"ok": False, "error": str(error)}
    except Exception as exc:
        current_app.logger.error("Error inesperado eliminando evento de comisión: %s", exc)
        return {"ok": False, "error": str(exc)}
