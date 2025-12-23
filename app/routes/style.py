"""
Blueprint para servir estilos dinámicos desde Google Drive.

Endpoints:
- /style/current/style.css - CSS del estilo activo
- /style/current/<filename> - Assets del estilo activo
- /style/<style_name>/<filename> - Assets de un estilo específico (para previsualización)
"""

from flask import Blueprint, Response, abort, current_app, send_file
from io import BytesIO
import mimetypes
import hashlib

from app.services.style_service import (
    download_style_file,
    get_active_style_with_fallback,
    style_exists,
    _sanitize_style_name,
    STYLE_CSS_FILENAME,
)

style_bp = Blueprint("style", __name__, url_prefix="/style")

# Cache headers (en segundos)
CACHE_MAX_AGE_CSS = 300  # 5 minutos para CSS (previsualización por style_name)
CACHE_MAX_AGE_IMAGES = 3600  # 1 hora para imágenes (previsualización por style_name)

# Para /style/current/* el URL NO cambia al cambiar de estilo,
# así que una caché larga impediría ver el cambio durante mucho tiempo.
CACHE_MAX_AGE_CURRENT_CSS = 0
CACHE_MAX_AGE_CURRENT_IMAGES = 0


def _get_mime_type(filename: str) -> str:
    """Determina el Content-Type correcto para un archivo."""
    mime_type, _ = mimetypes.guess_type(filename)
    if mime_type:
        return mime_type
    
    # Fallbacks para extensiones comunes
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    mime_map = {
        "css": "text/css; charset=utf-8",
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "gif": "image/gif",
        "svg": "image/svg+xml",
        "webp": "image/webp",
        "ico": "image/x-icon",
    }
    return mime_map.get(ext, "application/octet-stream")


def _generate_etag(content: bytes) -> str:
    """Genera un ETag basado en el contenido."""
    return f'"{hashlib.md5(content).hexdigest()}"'


def _serve_style_file(style_name: str, filename: str, cache_max_age: int = CACHE_MAX_AGE_IMAGES):
    """
    Sirve un archivo de estilo con headers apropiados.
    """
    sanitized = _sanitize_style_name(style_name)
    if not sanitized:
        abort(400, "Nombre de estilo inválido")
    
    result = download_style_file(sanitized, filename)
    
    if result is None:
        # Intentar fallback a assets locales
        from pathlib import Path

        # 1) Prioridad: carpeta local del estilo solicitado
        preferred_local = Path(current_app.static_folder) / "images" / sanitized.lower() / filename
        if preferred_local.exists():
            try:
                content = preferred_local.read_bytes()
                mime_type = _get_mime_type(filename)
                result = (content, mime_type)
            except Exception:
                result = None

        # 2) Último recurso: fallbacks por defecto (útil si el estilo activo no tiene asset local)
        if result is None:
            local_fallbacks = ["navidad", "general"]
            for fallback_folder in local_fallbacks:
                # Evitar repetir la misma carpeta
                if fallback_folder.lower() == sanitized.lower():
                    continue
                local_path = Path(current_app.static_folder) / "images" / fallback_folder / filename
                if local_path.exists():
                    try:
                        content = local_path.read_bytes()
                        mime_type = _get_mime_type(filename)
                        result = (content, mime_type)
                        break
                    except Exception:
                        pass
    
    if result is None:
        abort(404, f"Archivo no encontrado: {filename}")
    
    content, mime_type = result
    
    # Corregir mime type si es necesario
    if not mime_type or mime_type == "application/octet-stream":
        mime_type = _get_mime_type(filename)
    
    # Generar ETag
    etag = _generate_etag(content)
    
    # Crear respuesta
    response = Response(content, mimetype=mime_type)
    response.headers["ETag"] = etag

    if cache_max_age <= 0:
        # Forzar revalidación (útil para /style/current/* cuando cambia el estilo activo)
        response.headers["Cache-Control"] = "no-cache, must-revalidate, max-age=0"
    else:
        response.headers["Cache-Control"] = f"public, max-age={cache_max_age}"

    response.headers["X-Content-Type-Options"] = "nosniff"
    
    # Permitir CORS para recursos de estilo
    response.headers["Access-Control-Allow-Origin"] = "*"
    
    return response


@style_bp.route("/current/style.css")
def current_style_css():
    """
    Sirve el CSS del estilo activo.
    Este endpoint es el principal para cargar estilos dinámicos.
    """
    active_style = get_active_style_with_fallback()
    return _serve_style_file(active_style, STYLE_CSS_FILENAME, CACHE_MAX_AGE_CURRENT_CSS)


@style_bp.route("/current/<path:filename>")
def current_style_file(filename: str):
    """
    Sirve un archivo del estilo activo.
    Usado para imágenes referenciadas en el style.css
    """
    # Validar filename para evitar path traversal
    if ".." in filename or filename.startswith("/") or filename.startswith("\\"):
        abort(400, "Nombre de archivo inválido")
    
    active_style = get_active_style_with_fallback()
    return _serve_style_file(active_style, filename, CACHE_MAX_AGE_CURRENT_IMAGES)


@style_bp.route("/<style_name>/style.css")
def preview_style_css(style_name: str):
    """
    Sirve el CSS de un estilo específico (para previsualización).
    """
    sanitized = _sanitize_style_name(style_name)
    if not sanitized or not style_exists(sanitized):
        abort(404, f"Estilo no encontrado: {style_name}")
    
    return _serve_style_file(sanitized, STYLE_CSS_FILENAME, CACHE_MAX_AGE_CSS)


@style_bp.route("/<style_name>/<path:filename>")
def preview_style_file(style_name: str, filename: str):
    """
    Sirve un archivo de un estilo específico (para previsualización).
    """
    # Validar filename
    if ".." in filename or filename.startswith("/") or filename.startswith("\\"):
        abort(400, "Nombre de archivo inválido")
    
    sanitized = _sanitize_style_name(style_name)
    if not sanitized:
        abort(400, "Nombre de estilo inválido")
    
    return _serve_style_file(sanitized, filename)


@style_bp.route("/logo/header")
def logo_header():
    """Sirve el logo de header del estilo activo."""
    active_style = get_active_style_with_fallback()
    return _serve_style_file(active_style, "Logo_AMPA_64x64.png", CACHE_MAX_AGE_CURRENT_IMAGES)


@style_bp.route("/logo/hero")
def logo_hero():
    """Sirve el logo hero del estilo activo."""
    active_style = get_active_style_with_fallback()
    return _serve_style_file(active_style, "Logo_AMPA_400x400.png", CACHE_MAX_AGE_CURRENT_IMAGES)


@style_bp.route("/logo/placeholder")
def logo_placeholder():
    """Sirve el placeholder por defecto del estilo activo."""
    active_style = get_active_style_with_fallback()
    return _serve_style_file(active_style, "Logo_AMPA.png", CACHE_MAX_AGE_CURRENT_IMAGES)


@style_bp.route("/info")
def style_info():
    """
    Devuelve información del estilo activo (para debugging/admin).
    Solo accesible con permisos de admin.
    """
    from flask_login import current_user
    from app.models import user_is_privileged
    
    if not current_user.is_authenticated:
        abort(401)
    
    if not (current_user.has_permission("manage_styles") or user_is_privileged(current_user)):
        abort(403)
    
    from app.services.style_service import (
        get_active_style_name,
        list_styles,
        get_style_files,
    )
    
    active = get_active_style_name()
    styles = list_styles()
    active_files = get_style_files(active)
    
    return {
        "active_style": active,
        "styles": styles,
        "active_files": active_files,
    }
