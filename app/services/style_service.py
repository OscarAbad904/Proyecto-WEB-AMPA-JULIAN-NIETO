"""
Servicio de gestión de estilos dinámicos para la web AMPA.

Permite cargar CSS e imágenes desde Google Drive con caché local,
gestionando perfiles de estilo (Navidad, General, etc.).
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import shutil
import time
from io import BytesIO
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple

from flask import current_app
from PIL import Image
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseUpload

from app.media_utils import (
    _get_user_drive_service,
    _find_folder_id,
    ensure_folder,
    resolve_drive_root_folder_id,
)


CURRENT_STYLE_DIRNAME = "current"
CURRENT_STYLE_CSS_FILENAME = "style.css"  # en assets/css/


def _get_current_style_images_dir() -> Path:
    """Directorio fijo donde se copian las imágenes del estilo activo."""
    images_dir = Path(current_app.static_folder) / "images" / CURRENT_STYLE_DIRNAME
    images_dir.mkdir(parents=True, exist_ok=True)
    return images_dir


def _get_current_style_css_path() -> Path:
    css_path = Path(current_app.static_folder) / "css" / CURRENT_STYLE_CSS_FILENAME
    css_path.parent.mkdir(parents=True, exist_ok=True)
    return css_path


def _rewrite_style_css_for_static(css_text: str) -> str:
    """Reescribe url('./X') para que apunte a ../images/current/X desde assets/css/style.css."""
    # Soportar url(./x), url('./x'), url("./x")
    def _repl(match: re.Match) -> str:
        quote = match.group(1) or ""
        path = match.group(2)
        return f"url({quote}../images/{CURRENT_STYLE_DIRNAME}/{path}{quote})"

    return re.sub(r"url\(\s*(['\"]?)\./([^'\"\)]+)\1\s*\)", _repl, css_text)


def get_active_style_version() -> str:
    """Versión (cache-bust) del estilo activo para forzar recarga de assets estáticos."""
    from app.models import SiteSetting
    try:
        v = SiteSetting.get("active_style_version")
        if v:
            return str(v)
    except Exception:
        pass
    return "0"


def _bump_active_style_version() -> None:
    from app.models import SiteSetting
    from app.extensions import db
    try:
        SiteSetting.set("active_style_version", str(int(time.time())))
        db.session.commit()
    except Exception:
        db.session.rollback()


def sync_active_style_to_static() -> Dict[str, Any]:
    """Sincroniza el estilo activo (Drive o fallback local) a rutas fijas en /assets."""
    active = get_active_style_with_fallback()
    return sync_style_to_static(active)


def sync_style_to_static(style_name: str) -> Dict[str, Any]:
    """Copia imágenes y CSS del estilo dado a assets/images/current y assets/css/style.css."""
    sanitized = _sanitize_style_name(style_name)
    if not sanitized:
        return {"ok": False, "error": "Nombre de estilo inválido"}

    images_dir = _get_current_style_images_dir()
    css_path = _get_current_style_css_path()

    base_images = Path(current_app.static_folder) / "images"
    tmp_dir = base_images / f"_{CURRENT_STYLE_DIRNAME}_tmp"

    if tmp_dir.exists():
        shutil.rmtree(tmp_dir, ignore_errors=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    copied: List[str] = []
    errors: List[str] = []

    # 1) Intentar listar/descargar desde Drive (si falla, se usará fallback local)
    try:
        files = get_style_files(sanitized)
    except Exception as exc:
        files = []
        errors.append(f"No se pudieron listar archivos en Drive: {exc}")

    css_bytes: Optional[bytes] = None

    # Si hay lista de archivos (Drive o local), copiar todo lo que sea relevante
    for f in files or []:
        name = f.get("name")
        if not name:
            continue

        if name == STYLE_CSS_FILENAME:
            try:
                res = download_style_file(sanitized, name)
                if res:
                    css_bytes = res[0]
            except Exception as exc:
                errors.append(f"No se pudo descargar CSS: {exc}")
            continue

        # Copiamos imágenes/otros assets tal cual a current
        try:
            res = download_style_file(sanitized, name)
            if not res:
                continue
            content, _mime = res
            (tmp_dir / name).write_bytes(content)
            copied.append(name)
        except Exception as exc:
            errors.append(f"No se pudo copiar {name}: {exc}")

    # 2) Asegurar al menos los archivos clave
    required = set(STYLE_KEY_FILES.values())
    for filename in required:
        if (tmp_dir / filename).exists():
            continue
        res: Optional[Tuple[bytes, str]] = None

        # Intentar Drive (si está disponible) y, si no, local estricto del estilo.
        try:
            res = download_style_file(sanitized, filename)
        except Exception:
            res = None

        if res is None:
            res = _download_local_style_file_strict(sanitized, filename)

        if not res:
            continue

        try:
            (tmp_dir / filename).write_bytes(res[0])
            copied.append(filename)
        except Exception as exc:
            errors.append(f"No se pudo escribir {filename}: {exc}")

    # 3) Escribir CSS local (si no hay en Drive, generarlo)
    try:
        if css_bytes is None:
            # Fallback: generar uno mínimo
            css_text = _generate_style_css(sanitized)
        else:
            css_text = css_bytes.decode("utf-8", errors="replace")

        css_text = _rewrite_style_css_for_static(css_text)
        css_path.write_text(css_text, encoding="utf-8")
    except Exception as exc:
        errors.append(f"No se pudo escribir CSS local: {exc}")

    # 4) Swap atómico del directorio current
    try:
        if images_dir.exists():
            shutil.rmtree(images_dir, ignore_errors=True)
        tmp_dir.rename(images_dir)
    except Exception as exc:
        errors.append(f"No se pudo activar el directorio current: {exc}")

    # 5) Bump versión para bustear caché
    _bump_active_style_version()

    return {
        "ok": True,
        "style": sanitized,
        "copied": sorted(set(copied)),
        "errors": errors,
    }

# Nombres de archivo estándar para estilos
STYLE_KEY_FILES = {
    "logo_header": "Logo_AMPA_64x64.png",
    "logo_hero": "Logo_AMPA_400x400.png",
    "placeholder": "Logo_AMPA.png",
    "background": "Fondo Pagina Principal.png",
    "shape_orange": "Globo_shape_Naranja.png",
    "shape_green": "Globo_shape_Verde.png",
}

# Nombre de la carpeta raíz de estilos en Drive
STYLES_FOLDER_NAME = "Estilos"

# Nombre del archivo CSS de cada estilo
STYLE_CSS_FILENAME = "style.css"

# Especificaciones de tamaños (derivadas del estilo "General")
# Regla: siempre se escala por el lado más pequeño (cover) y se recorta al tamaño exacto.
STYLE_IMAGE_SPECS: Dict[str, Tuple[int, int]] = {
    "Fondo Pagina Principal.png": (1344, 768),
    "Globo_shape_Naranja.png": (256, 356),
    "Globo_shape_Verde.png": (256, 356),
    "Logo_AMPA.png": (1024, 1024),
    "Logo_AMPA_400x400.png": (400, 400),
    "Logo_AMPA_64x64.png": (64, 64),
}

# Slots permitidos para drag&drop (los otros se generan automáticamente)
STYLE_DROPPABLE_SLOTS = {
    "Fondo Pagina Principal.png",
    "Globo_shape_Naranja.png",
    "Globo_shape_Verde.png",
    "Logo_AMPA.png",
}

# Caché de archivos en memoria con TTL
_style_cache: Dict[str, Dict[str, Any]] = {}
_cache_lock = Lock()

# Caché del ID de la carpeta raíz de estilos
_styles_folder_id_cache: Optional[str] = None

# TTL de caché en segundos (5 minutos por defecto)
DEFAULT_CACHE_TTL = 300


def _resize_cover_center_crop(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """Escala la imagen para cubrir (sin bandas) y recorta centrado al tamaño objetivo."""
    if target_w <= 0 or target_h <= 0:
        raise ValueError("Target size inválido")

    src_w, src_h = img.size
    if src_w <= 0 or src_h <= 0:
        raise ValueError("Imagen origen inválida")

    scale = max(target_w / src_w, target_h / src_h)
    new_w = int(round(src_w * scale))
    new_h = int(round(src_h * scale))

    resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

    left = max(0, (new_w - target_w) // 2)
    top = max(0, (new_h - target_h) // 2)
    right = left + target_w
    bottom = top + target_h

    return resized.crop((left, top, right, bottom))


def _resize_fit_contain(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """Escala la imagen para que quepa entera en el tamaño objetivo, sin recortar, con fondo transparente."""
    if target_w <= 0 or target_h <= 0:
        raise ValueError("Target size inválido")
    
    src_w, src_h = img.size
    if src_w <= 0 or src_h <= 0:
        raise ValueError("Imagen origen inválida")

    # Copia para no modificar original
    img_copy = img.copy()
    img_copy.thumbnail((target_w, target_h), Image.Resampling.LANCZOS)
    
    # Crear lienzo transparente del tamaño exacto
    new_img = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
    left = (target_w - img_copy.width) // 2
    top = (target_h - img_copy.height) // 2
    new_img.paste(img_copy, (left, top))
    return new_img


def prepare_style_slot_upload(slot_filename: str, content: bytes) -> List[Tuple[str, bytes, str]]:
    """
    Prepara (redimensiona/recorta) la imagen subida para un slot.

    - Para "Logo_AMPA.png": genera también "Logo_AMPA_400x400.png" y "Logo_AMPA_64x64.png".
    - Para el resto: genera solo el archivo del slot.

    Returns:
        Lista de tuplas (filename_objetivo, bytes_png, mime_type)
    """
    if slot_filename not in STYLE_IMAGE_SPECS:
        raise ValueError("Nombre de slot no reconocido")

    try:
        with Image.open(BytesIO(content)) as img:
            img = img.convert("RGBA")
            outputs: List[Tuple[str, bytes, str]] = []

            def _make(target_name: str):
                w, h = STYLE_IMAGE_SPECS[target_name]
                # Globos y Logos se escalan para caber (contain) sin recortar
                if "Globo_shape" in target_name or "Logo_AMPA" in target_name:
                    processed = _resize_fit_contain(img, w, h)
                else:
                    # Fondos siguen usando cover/crop para evitar bandas
                    processed = _resize_cover_center_crop(img, w, h)
                out = BytesIO()
                processed.save(out, format="PNG", optimize=True)
                outputs.append((target_name, out.getvalue(), "image/png"))

            if slot_filename == "Logo_AMPA.png":
                _make("Logo_AMPA.png")
                _make("Logo_AMPA_400x400.png")
                _make("Logo_AMPA_64x64.png")
            else:
                _make(slot_filename)

            return outputs
    except Exception as exc:
        raise ValueError(f"No se pudo procesar la imagen: {exc}")


def _sanitize_style_name(name: str) -> str:
    """
    Sanitiza el nombre de un estilo para evitar path traversal y caracteres inválidos.
    Solo permite letras, números, guiones, espacios y guiones bajos.
    """
    if not name:
        return ""
    # Eliminar caracteres peligrosos
    sanitized = re.sub(r"[^\w\s\-áéíóúñÁÉÍÓÚÑ]", "", name, flags=re.UNICODE)
    # Colapsar múltiples espacios
    sanitized = re.sub(r"\s+", " ", sanitized).strip()
    # Prevenir path traversal
    sanitized = sanitized.replace("..", "").replace("/", "").replace("\\", "")
    return sanitized[:64]  # Limitar longitud


def _get_cache_dir() -> Path:
    """Obtiene el directorio de caché local para estilos."""
    base_path = Path(current_app.config.get("ROOT_PATH") or current_app.root_path)
    cache_dir = base_path / "cache" / "styles"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _get_style_cache_dir(style_name: str) -> Path:
    """Obtiene el directorio de caché para un estilo específico."""
    sanitized = _sanitize_style_name(style_name)
    if not sanitized:
        raise ValueError("Nombre de estilo inválido")
    cache_dir = _get_cache_dir() / sanitized
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _get_cache_metadata_path(style_name: str) -> Path:
    """Obtiene la ruta del archivo de metadatos de caché para un estilo."""
    return _get_style_cache_dir(style_name) / "_metadata.json"


def _load_cache_metadata(style_name: str) -> Dict[str, Any]:
    """Carga los metadatos de caché de un estilo."""
    path = _get_cache_metadata_path(style_name)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"files": {}, "last_sync": 0}


def _save_cache_metadata(style_name: str, metadata: Dict[str, Any]) -> None:
    """Guarda los metadatos de caché de un estilo."""
    path = _get_cache_metadata_path(style_name)
    path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")


def _is_cache_valid(style_name: str, filename: str) -> bool:
    """Verifica si un archivo en caché sigue siendo válido."""
    metadata = _load_cache_metadata(style_name)
    file_meta = metadata.get("files", {}).get(filename, {})
    if not file_meta:
        return False
    
    cached_at = file_meta.get("cached_at", 0)
    ttl = current_app.config.get("STYLE_CACHE_TTL", DEFAULT_CACHE_TTL)
    return (time.time() - cached_at) < ttl


def _get_cached_file(style_name: str, filename: str) -> Optional[bytes]:
    """Obtiene un archivo desde la caché local si existe y es válido."""
    if not _is_cache_valid(style_name, filename):
        return None
    
    cache_path = _get_style_cache_dir(style_name) / filename
    if cache_path.exists():
        try:
            return cache_path.read_bytes()
        except Exception:
            pass
    return None


def _cache_file(style_name: str, filename: str, content: bytes, drive_file_id: str = "") -> None:
    """Guarda un archivo en la caché local."""
    cache_dir = _get_style_cache_dir(style_name)
    cache_path = cache_dir / filename
    
    try:
        cache_path.write_bytes(content)
        
        # Actualizar metadatos
        metadata = _load_cache_metadata(style_name)
        metadata["files"][filename] = {
            "cached_at": time.time(),
            "size": len(content),
            "drive_file_id": drive_file_id,
            "etag": hashlib.md5(content).hexdigest(),
        }
        _save_cache_metadata(style_name, metadata)
    except Exception as e:
        current_app.logger.warning(f"Error cacheando archivo {filename}: {e}")


def invalidate_style_cache(style_name: str) -> None:
    """Invalida la caché de un estilo completo."""
    try:
        cache_dir = _get_style_cache_dir(style_name)
        if cache_dir.exists():
            shutil.rmtree(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        current_app.logger.warning(f"Error invalidando caché de estilo {style_name}: {e}")


def get_styles_folder_id(drive_service=None) -> Optional[str]:
    """
    Obtiene el ID de la carpeta 'Estilos' en Drive.
    La crea si no existe.
    """
    global _styles_folder_id_cache
    if _styles_folder_id_cache:
        return _styles_folder_id_cache

    if drive_service is None:
        drive_service = _get_user_drive_service()
    if drive_service is None:
        return None
    
    try:
        drive_id = current_app.config.get("GOOGLE_DRIVE_SHARED_DRIVE_ID") or None
        root_folder_id = resolve_drive_root_folder_id(drive_service, drive_id=drive_id)
        
        # Buscar o crear carpeta Estilos
        styles_folder_id = _find_folder_id(
            drive_service, 
            STYLES_FOLDER_NAME, 
            parent_id=root_folder_id,
            drive_id=drive_id
        )
        
        if not styles_folder_id:
            styles_folder_id = ensure_folder(
                STYLES_FOLDER_NAME,
                parent_id=root_folder_id,
                drive_id=drive_id
            )
        
        _styles_folder_id_cache = styles_folder_id
        return styles_folder_id
    except Exception as e:
        current_app.logger.error(f"Error obteniendo carpeta de estilos: {e}")
        return None


def list_styles() -> List[Dict[str, Any]]:
    """
    Lista todos los estilos disponibles en Drive.
    Devuelve lista de diccionarios con nombre, id y si está activo.
    """
    drive_service = _get_user_drive_service()
    if drive_service is None:
        # Fallback: estilos locales
        return _list_local_styles()
    
    try:
        styles_folder_id = get_styles_folder_id(drive_service)
        if not styles_folder_id:
            return _list_local_styles()
        
        drive_id = current_app.config.get("GOOGLE_DRIVE_SHARED_DRIVE_ID") or None
        
        # Listar subcarpetas en Estilos
        query = f"'{styles_folder_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
        
        list_kwargs = {
            "q": query,
            "spaces": "drive",
            "fields": "files(id,name,createdTime,modifiedTime)",
            "pageSize": 100,
            "supportsAllDrives": True,
            "includeItemsFromAllDrives": True,
        }
        if drive_id:
            list_kwargs["corpora"] = "drive"
            list_kwargs["driveId"] = drive_id
        
        resp = drive_service.files().list(**list_kwargs).execute()
        files = resp.get("files", [])
        
        active_style = get_active_style_name()
        
        styles = []
        for f in files:
            styles.append({
                "name": f["name"],
                "id": f["id"],
                "created_at": f.get("createdTime"),
                "modified_at": f.get("modifiedTime"),
                "is_active": f["name"] == active_style,
            })
        
        return sorted(styles, key=lambda s: s["name"])
    except Exception as e:
        current_app.logger.error(f"Error listando estilos desde Drive: {e}")
        return _list_local_styles()


def _list_local_styles() -> List[Dict[str, Any]]:
    """Lista estilos disponibles localmente (fallback)."""
    styles = []
    static_images = Path(current_app.static_folder) / "images"
    
    for folder in ["navidad", "general"]:
        folder_path = static_images / folder
        if folder_path.exists():
            styles.append({
                "name": folder.capitalize(),
                "id": f"local_{folder}",
                "created_at": None,
                "modified_at": None,
                "is_active": folder.lower() == get_active_style_name().lower(),
                "is_local": True,
            })
    
    return styles


def get_style_folder_id(style_name: str, drive_service=None) -> Optional[str]:
    """Obtiene el ID de la carpeta de un estilo específico."""
    sanitized = _sanitize_style_name(style_name)
    if not sanitized:
        return None
    
    if drive_service is None:
        drive_service = _get_user_drive_service()
    if drive_service is None:
        return None
    
    try:
        styles_folder_id = get_styles_folder_id(drive_service)
        if not styles_folder_id:
            return None
        
        drive_id = current_app.config.get("GOOGLE_DRIVE_SHARED_DRIVE_ID") or None
        return _find_folder_id(
            drive_service,
            sanitized,
            parent_id=styles_folder_id,
            drive_id=drive_id
        )
    except Exception as e:
        current_app.logger.error(f"Error obteniendo carpeta de estilo {style_name}: {e}")
        return None


def get_style_files(style_name: str) -> List[Dict[str, Any]]:
    """
    Lista todos los archivos de un estilo.
    """
    drive_service = _get_user_drive_service()
    if drive_service is None:
        return _get_local_style_files(style_name)
    
    try:
        folder_id = get_style_folder_id(style_name, drive_service)
        if not folder_id:
            return _get_local_style_files(style_name)
        
        drive_id = current_app.config.get("GOOGLE_DRIVE_SHARED_DRIVE_ID") or None
        
        query = f"'{folder_id}' in parents and trashed=false"
        list_kwargs = {
            "q": query,
            "spaces": "drive",
            "fields": "files(id,name,mimeType,size,modifiedTime)",
            "pageSize": 100,
            "supportsAllDrives": True,
            "includeItemsFromAllDrives": True,
        }
        if drive_id:
            list_kwargs["corpora"] = "drive"
            list_kwargs["driveId"] = drive_id
        
        resp = drive_service.files().list(**list_kwargs).execute()
        return resp.get("files", [])
    except Exception as e:
        current_app.logger.error(f"Error listando archivos de estilo {style_name}: {e}")
        return _get_local_style_files(style_name)


def _get_local_style_files(style_name: str) -> List[Dict[str, Any]]:
    """Lista archivos de un estilo local (fallback)."""
    folder_name = style_name.lower()
    folder_path = Path(current_app.static_folder) / "images" / folder_name
    
    if not folder_path.exists():
        return []
    
    files = []
    for f in folder_path.iterdir():
        if f.is_file():
            mime_type, _ = mimetypes.guess_type(str(f))
            files.append({
                "id": f"local_{f.name}",
                "name": f.name,
                "mimeType": mime_type or "application/octet-stream",
                "size": f.stat().st_size,
                "is_local": True,
            })
    
    return files


def download_style_file(style_name: str, filename: str) -> Optional[Tuple[bytes, str]]:
    """
    Descarga un archivo de un estilo desde Drive o caché.
    
    Returns:
        Tupla (contenido_bytes, mime_type) o None si no se encuentra.
    """
    sanitized_name = _sanitize_style_name(style_name)
    if not sanitized_name:
        return None
    
    # Verificar caché primero
    cached = _get_cached_file(sanitized_name, filename)
    if cached:
        mime_type, _ = mimetypes.guess_type(filename)
        return cached, mime_type or "application/octet-stream"
    
    drive_service = _get_user_drive_service()
    if drive_service is None:
        # Fallback local
        return _download_local_style_file(sanitized_name, filename)
    
    try:
        folder_id = get_style_folder_id(sanitized_name, drive_service)
        if not folder_id:
            return _download_local_style_file(sanitized_name, filename)
        
        drive_id = current_app.config.get("GOOGLE_DRIVE_SHARED_DRIVE_ID") or None
        
        # Buscar archivo por nombre
        query = f"'{folder_id}' in parents and name='{filename}' and trashed=false"
        list_kwargs = {
            "q": query,
            "spaces": "drive",
            "fields": "files(id,name,mimeType)",
            "pageSize": 1,
            "supportsAllDrives": True,
            "includeItemsFromAllDrives": True,
        }
        if drive_id:
            list_kwargs["corpora"] = "drive"
            list_kwargs["driveId"] = drive_id
        
        resp = drive_service.files().list(**list_kwargs).execute()
        files = resp.get("files", [])
        
        if not files:
            return _download_local_style_file(sanitized_name, filename)
        
        file_info = files[0]
        file_id = file_info["id"]
        mime_type = file_info.get("mimeType", "application/octet-stream")
        
        # Descargar contenido
        request = drive_service.files().get_media(fileId=file_id)
        content = request.execute()
        
        # Cachear
        _cache_file(sanitized_name, filename, content, file_id)
        
        return content, mime_type
    except Exception as e:
        current_app.logger.error(f"Error descargando {filename} de estilo {style_name}: {e}")
        return _download_local_style_file(sanitized_name, filename)


def _download_local_style_file(style_name: str, filename: str) -> Optional[Tuple[bytes, str]]:
    """Descarga un archivo de estilo local (fallback)."""
    folder_name = style_name.lower()
    file_path = Path(current_app.static_folder) / "images" / folder_name / filename
    
    if not file_path.exists():
        # Intentar con nombre alternativo
        for alt_folder in ["navidad", "general"]:
            alt_path = Path(current_app.static_folder) / "images" / alt_folder / filename
            if alt_path.exists():
                file_path = alt_path
                break
    
    if not file_path.exists():
        # Si es style.css, generar uno por defecto
        if filename == STYLE_CSS_FILENAME:
            css_content = _generate_style_css(style_name)
            return css_content.encode("utf-8"), "text/css; charset=utf-8"
        return None
    
    try:
        content = file_path.read_bytes()
        mime_type, _ = mimetypes.guess_type(str(file_path))
        return content, mime_type or "application/octet-stream"
    except Exception:
        return None


def _download_local_style_file_strict(style_name: str, filename: str) -> Optional[Tuple[bytes, str]]:
    """Descarga un archivo de estilo local SOLO del estilo indicado (sin fallbacks a otros estilos)."""
    folder_name = style_name.lower()
    file_path = Path(current_app.static_folder) / "images" / folder_name / filename
    if not file_path.exists():
        return None
    try:
        content = file_path.read_bytes()
        mime_type, _ = mimetypes.guess_type(str(file_path))
        return content, mime_type or "application/octet-stream"
    except Exception:
        return None


def upload_style_file(
    style_name: str,
    filename: str,
    content: bytes,
    mime_type: str = None
) -> bool:
    """
    Sube un archivo a la carpeta de un estilo en Drive.
    Si el archivo ya existe, lo reemplaza.
    """
    sanitized = _sanitize_style_name(style_name)
    if not sanitized:
        return False
    
    if mime_type is None:
        mime_type, _ = mimetypes.guess_type(filename)
        mime_type = mime_type or "application/octet-stream"
    
    drive_service = _get_user_drive_service()
    if drive_service is None:
        current_app.logger.warning("No hay servicio de Drive disponible")
        return False
    
    try:
        folder_id = get_style_folder_id(sanitized, drive_service)
        if not folder_id:
            # Crear carpeta del estilo si no existe
            styles_folder_id = get_styles_folder_id(drive_service)
            if not styles_folder_id:
                return False
            
            drive_id = current_app.config.get("GOOGLE_DRIVE_SHARED_DRIVE_ID") or None
            folder_id = ensure_folder(sanitized, parent_id=styles_folder_id, drive_id=drive_id)
        
        drive_id = current_app.config.get("GOOGLE_DRIVE_SHARED_DRIVE_ID") or None
        
        # Buscar archivo existente
        query = f"'{folder_id}' in parents and name='{filename}' and trashed=false"
        list_kwargs = {
            "q": query,
            "spaces": "drive",
            "fields": "files(id)",
            "pageSize": 1,
            "supportsAllDrives": True,
            "includeItemsFromAllDrives": True,
        }
        if drive_id:
            list_kwargs["corpora"] = "drive"
            list_kwargs["driveId"] = drive_id
        
        resp = drive_service.files().list(**list_kwargs).execute()
        existing = resp.get("files", [])
        
        media = MediaIoBaseUpload(BytesIO(content), mimetype=mime_type, resumable=False)
        
        if existing:
            # Actualizar archivo existente
            file_id = existing[0]["id"]
            drive_service.files().update(
                fileId=file_id,
                media_body=media,
                supportsAllDrives=True,
            ).execute()
        else:
            # Crear nuevo archivo
            metadata = {
                "name": filename,
                "parents": [folder_id],
            }
            created = drive_service.files().create(
                body=metadata,
                media_body=media,
                fields="id",
                supportsAllDrives=True,
            ).execute()
            file_id = created.get("id")
            
            # Hacer público
            drive_service.permissions().create(
                fileId=file_id,
                body={"type": "anyone", "role": "reader"},
                fields="id",
            ).execute()
        
        # Invalidar caché
        invalidate_style_cache(sanitized)
        
        return True
    except Exception as e:
        current_app.logger.error(f"Error subiendo {filename} a estilo {style_name}: {e}")
        return False


def delete_style_file(style_name: str, filename: str) -> bool:
    """Elimina un archivo de un estilo en Drive."""
    sanitized = _sanitize_style_name(style_name)
    if not sanitized:
        return False
    
    drive_service = _get_user_drive_service()
    if drive_service is None:
        return False
    
    try:
        folder_id = get_style_folder_id(sanitized, drive_service)
        if not folder_id:
            return False
        
        drive_id = current_app.config.get("GOOGLE_DRIVE_SHARED_DRIVE_ID") or None
        
        # Buscar archivo
        query = f"'{folder_id}' in parents and name='{filename}' and trashed=false"
        list_kwargs = {
            "q": query,
            "spaces": "drive",
            "fields": "files(id)",
            "pageSize": 1,
            "supportsAllDrives": True,
            "includeItemsFromAllDrives": True,
        }
        if drive_id:
            list_kwargs["corpora"] = "drive"
            list_kwargs["driveId"] = drive_id
        
        resp = drive_service.files().list(**list_kwargs).execute()
        files = resp.get("files", [])
        
        if files:
            drive_service.files().delete(
                fileId=files[0]["id"],
                supportsAllDrives=True,
            ).execute()
        
        invalidate_style_cache(sanitized)
        return True
    except Exception as e:
        current_app.logger.error(f"Error eliminando {filename} de estilo {style_name}: {e}")
        return False


def create_style(style_name: str) -> bool:
    """Crea una nueva carpeta de estilo en Drive."""
    sanitized = _sanitize_style_name(style_name)
    if not sanitized:
        return False
    
    drive_service = _get_user_drive_service()
    if drive_service is None:
        return False
    
    try:
        styles_folder_id = get_styles_folder_id(drive_service)
        if not styles_folder_id:
            return False
        
        drive_id = current_app.config.get("GOOGLE_DRIVE_SHARED_DRIVE_ID") or None
        
        # Verificar que no exista
        existing = _find_folder_id(
            drive_service,
            sanitized,
            parent_id=styles_folder_id,
            drive_id=drive_id
        )
        if existing:
            return False
        
        # Crear carpeta
        ensure_folder(sanitized, parent_id=styles_folder_id, drive_id=drive_id)
        return True
    except Exception as e:
        current_app.logger.error(f"Error creando estilo {style_name}: {e}")
        return False


def delete_style(style_name: str) -> bool:
    """Elimina un estilo completo de Drive (carpeta y contenidos)."""
    sanitized = _sanitize_style_name(style_name)
    if not sanitized:
        return False
    
    # No permitir eliminar estilos por defecto
    if sanitized.lower() in ["navidad", "general"]:
        current_app.logger.warning(f"No se puede eliminar el estilo por defecto: {sanitized}")
        return False
    
    drive_service = _get_user_drive_service()
    if drive_service is None:
        return False
    
    try:
        folder_id = get_style_folder_id(sanitized, drive_service)
        if not folder_id:
            return False
        
        # Eliminar carpeta (y todo su contenido)
        drive_service.files().delete(
            fileId=folder_id,
            supportsAllDrives=True,
        ).execute()
        
        # Limpiar caché
        invalidate_style_cache(sanitized)
        
        return True
    except Exception as e:
        current_app.logger.error(f"Error eliminando estilo {style_name}: {e}")
        return False


def duplicate_style(source_name: str, target_name: str) -> bool:
    """Duplica un estilo existente con un nuevo nombre."""
    source_sanitized = _sanitize_style_name(source_name)
    target_sanitized = _sanitize_style_name(target_name)
    
    if not source_sanitized or not target_sanitized:
        return False
    
    if source_sanitized.lower() == target_sanitized.lower():
        return False
    
    drive_service = _get_user_drive_service()
    if drive_service is None:
        return False
    
    try:
        # Crear carpeta destino
        if not create_style(target_sanitized):
            return False
        
        # Copiar archivos
        source_files = get_style_files(source_sanitized)
        for file_info in source_files:
            result = download_style_file(source_sanitized, file_info["name"])
            if result:
                content, mime_type = result
                upload_style_file(target_sanitized, file_info["name"], content, mime_type)
        
        return True
    except Exception as e:
        current_app.logger.error(f"Error duplicando estilo {source_name} a {target_name}: {e}")
        return False


def rename_style(old_name: str, new_name: str) -> bool:
    """Renombra un estilo (carpeta en Drive)."""
    old_sanitized = _sanitize_style_name(old_name)
    new_sanitized = _sanitize_style_name(new_name)
    
    if not old_sanitized or not new_sanitized:
        return False
    
    # No permitir renombrar estilos por defecto
    if old_sanitized.lower() in ["navidad", "general"]:
        return False
    
    drive_service = _get_user_drive_service()
    if drive_service is None:
        return False
    
    try:
        folder_id = get_style_folder_id(old_sanitized, drive_service)
        if not folder_id:
            return False
        
        # Renombrar carpeta
        drive_service.files().update(
            fileId=folder_id,
            body={"name": new_sanitized},
            supportsAllDrives=True,
        ).execute()
        
        # Actualizar caché
        invalidate_style_cache(old_sanitized)
        
        # Si era el estilo activo, actualizar referencia
        from app.services.style_service import get_active_style_name, set_active_style
        if get_active_style_name().lower() == old_sanitized.lower():
            set_active_style(new_sanitized)
        
        return True
    except Exception as e:
        current_app.logger.error(f"Error renombrando estilo {old_name} a {new_name}: {e}")
        return False


# ============== Gestión del estilo activo ==============

def get_scheduled_style_name() -> Optional[str]:
    """
    Busca si hay algún estilo programado para la fecha actual.
    """
    from app.models import StyleSchedule
    from datetime import date
    
    try:
        today = date.today()
        # Buscamos el primer estilo habilitado cuyo rango incluya hoy
        schedule = StyleSchedule.query.filter(
            StyleSchedule.is_enabled == True,
            StyleSchedule.start_date <= today,
            StyleSchedule.end_date >= today
        ).first()
        
        if schedule:
            return schedule.style_name
    except Exception as e:
        # Evitar logs excesivos si la tabla no existe aún
        if "no such table" not in str(e).lower():
            current_app.logger.error(f"Error obteniendo estilo programado: {e}")
        
    return None


def ensure_active_style_synced() -> None:
    """
    Asegura que el estilo activo (manual o programado) esté sincronizado en assets/static.
    Se debe llamar en cada request (vía context processor o similar) para detectar cambios automáticos.
    """
    try:
        active_style = get_active_style_name()
        
        from app.models import SiteSetting
        from app.extensions import db
        
        last_synced = SiteSetting.get("last_synced_style")
        
        if active_style != last_synced:
            current_app.logger.info(f"Cambiando estilo sincronizado automáticamente: {last_synced} -> {active_style}")
            sync_style_to_static(active_style)
            SiteSetting.set("last_synced_style", active_style)
            db.session.commit()
    except Exception as e:
        if "no such table" not in str(e).lower():
            current_app.logger.error(f"Error en ensure_active_style_synced: {e}")


def get_active_style_name() -> str:
    """
    Obtiene el nombre del estilo activo.
    Prioriza el estilo programado sobre el manual configurado en SiteSetting.
    """
    scheduled = get_scheduled_style_name()
    if scheduled:
        return scheduled

    from app.models import SiteSetting
    
    try:
        setting = SiteSetting.get("active_style")
        if setting:
            return setting
    except Exception:
        pass
    
    return "Navidad"


def set_active_style(style_name: str) -> bool:
    """
    Establece el estilo activo en la BD.
    """
    sanitized = _sanitize_style_name(style_name)
    if not sanitized:
        return False
    
    from app.models import SiteSetting
    from app.extensions import db
    
    try:
        SiteSetting.set("active_style", sanitized)
        db.session.commit()
        
        # Invalidar caché del estilo anterior (si hubiera)
        invalidate_style_cache(sanitized)

        # Sincronizar a rutas fijas en /assets (best-effort)
        try:
            sync_style_to_static(sanitized)
        except Exception as exc:
            current_app.logger.warning(f"No se pudo sincronizar estilo a assets: {exc}")
        
        return True
    except Exception as e:
        current_app.logger.error(f"Error estableciendo estilo activo {style_name}: {e}")
        db.session.rollback()
        return False


def list_style_schedules() -> List[Dict[str, Any]]:
    """Lista todas las programaciones de estilos."""
    from app.models import StyleSchedule
    try:
        schedules = StyleSchedule.query.order_by(StyleSchedule.start_date).all()
        return [
            {
                "id": s.id,
                "style_name": s.style_name,
                "start_date": s.start_date.isoformat() if s.start_date else None,
                "end_date": s.end_date.isoformat() if s.end_date else None,
                "is_enabled": s.is_enabled,
            }
            for s in schedules
        ]
    except Exception:
        return []


def add_style_schedule(style_name: str, start_date, end_date, is_enabled: bool = True) -> Tuple[bool, str]:
    """Añade una nueva programación de estilo."""
    from app.models import StyleSchedule
    from app.extensions import db
    
    # Validar solapamiento
    overlap = check_style_schedule_overlap(style_name, start_date, end_date)
    if overlap:
        return False, f"El rango de fechas solapa con el estilo '{overlap}'."
    
    try:
        schedule = StyleSchedule(
            style_name=style_name,
            start_date=start_date,
            end_date=end_date,
            is_enabled=is_enabled
        )
        db.session.add(schedule)
        db.session.commit()
        return True, "Programación añadida correctamente."
    except Exception as e:
        db.session.rollback()
        return False, f"Error al añadir programación: {e}"


def delete_style_schedule(schedule_id: int) -> bool:
    """Elimina una programación de estilo."""
    from app.models import StyleSchedule
    from app.extensions import db
    try:
        schedule = StyleSchedule.query.get(schedule_id)
        if schedule:
            db.session.delete(schedule)
            db.session.commit()
            return True
    except Exception:
        db.session.rollback()
    return False


def check_style_schedule_overlap(style_name: str, start_date, end_date, exclude_id=None) -> Optional[str]:
    """
    Verifica si un rango de fechas solapa con alguna programación existente.
    Retorna el nombre del estilo que solapa, o None.
    """
    from app.models import StyleSchedule
    from sqlalchemy import or_, and_
    
    try:
        query = StyleSchedule.query.filter(
            StyleSchedule.is_enabled == True,
            or_(
                and_(StyleSchedule.start_date <= start_date, StyleSchedule.end_date >= start_date),
                and_(StyleSchedule.start_date <= end_date, StyleSchedule.end_date >= end_date),
                and_(StyleSchedule.start_date >= start_date, StyleSchedule.end_date <= end_date)
            )
        )
        
        if exclude_id:
            query = query.filter(StyleSchedule.id != exclude_id)
            
        overlap = query.first()
        if overlap:
            return overlap.style_name
    except Exception:
        pass
        
    return None


def style_exists(style_name: str) -> bool:
    """Verifica si un estilo existe en Drive o localmente."""
    sanitized = _sanitize_style_name(style_name)
    if not sanitized:
        return False
    
    # Verificar localmente primero
    local_path = Path(current_app.static_folder) / "images" / sanitized.lower()
    if local_path.exists():
        return True
    
    # Verificar en Drive
    drive_service = _get_user_drive_service()
    if drive_service:
        folder_id = get_style_folder_id(sanitized, drive_service)
        if folder_id:
            return True
    
    return False


def get_active_style_with_fallback() -> str:
    """
    Obtiene el estilo activo con fallback automático si no existe.
    """
    active = get_active_style_name()
    
    if style_exists(active):
        return active
    
    # Fallbacks ordenados
    fallbacks = ["Navidad", "General"]
    for fb in fallbacks:
        if style_exists(fb):
            set_active_style(fb)
            return fb
    
    # Último recurso: primer estilo disponible
    styles = list_styles()
    if styles:
        first_style = styles[0]["name"]
        set_active_style(first_style)
        return first_style
    
    return "Navidad"  # Default absoluto


# ============== Migración inicial de estilos ==============

def _generate_style_css(style_name: str) -> str:
    """
    Genera el contenido CSS de override para un estilo.
    Usa rutas relativas para que funcione desde /style/current/
    """
    css_template = """/* 
 * Estilo: {style_name}
 * CSS de override para personalización visual
 * Generado automáticamente - Editable desde el panel admin
 */

/* === Fondos y shapes === */
body.home-page {{
    background-image:
        linear-gradient(180deg, rgba(255, 255, 255, 0.12), rgba(255, 255, 255, 0.1)),
        url('./Fondo Pagina Principal.png');
    background-size: auto, cover;
    background-repeat: no-repeat, no-repeat;
    background-position: center center, 50% 45%;
    background-attachment: scroll, fixed;
}}

/* Shapes flotantes */
.hero-shape--orange {{
    background-image: url('./Globo_shape_Naranja.png');
}}

.hero-shape--green {{
    background-image: url('./Globo_shape_Verde.png');
}}

/* Fondos de eventos */
.event-cover-1 {{
    background-image: linear-gradient(135deg, rgba(126, 212, 255, 0.4), rgba(7, 17, 31, 0.9)), url('./Globo_shape_Verde.png');
}}

.event-cover-2 {{
    background-image: linear-gradient(135deg, rgba(255, 209, 102, 0.45), rgba(7, 17, 31, 0.9)), url('./Globo_shape_Naranja.png');
}}

.event-cover-3 {{
    background-image: linear-gradient(135deg, rgba(255, 138, 76, 0.35), rgba(7, 17, 31, 0.9)), url('./Globo_shape_Verde.png');
}}

/* === Variables de tema (editables) === */
:root {{
    /* Colores principales - personaliza según el estilo */
    --style-primary-color: #f97316;
    --style-secondary-color: #fbbf24;
    --style-accent-color: #0ea5e9;
    
    /* Puedes añadir más variables aquí */
}}

/* === Personalizaciones adicionales === */
/* Añade aquí CSS personalizado para este estilo */

"""
    return css_template.format(style_name=style_name)


def initialize_default_styles(overwrite: bool = False) -> Dict[str, Any]:
    """
    Inicializa los estilos por defecto (Navidad y General) en Drive.
    Copia los assets locales y genera el CSS inicial.
    
    Args:
        overwrite: Si True, sobrescribe estilos existentes
    
    Returns:
        Dict con resultado: {"ok": bool, "message": str, "styles_created": [], "styles_skipped": [], "errors": []}
    """
    result = {
        "ok": True,
        "message": "",
        "styles_created": [],
        "styles_skipped": [],
        "errors": []
    }
    
    drive_service = _get_user_drive_service()
    if drive_service is None:
        result["ok"] = False
        result["message"] = "No hay servicio de Drive disponible"
        return result
    
    default_styles = ["Navidad", "General"]
    
    for style_name in default_styles:
        try:
            current_app.logger.info(f"Inicializando estilo: {style_name}")
            
            # Crear carpeta del estilo
            styles_folder_id = get_styles_folder_id(drive_service)
            if not styles_folder_id:
                result["errors"].append(f"No se pudo obtener carpeta Estilos para {style_name}")
                continue
            
            drive_id = current_app.config.get("GOOGLE_DRIVE_SHARED_DRIVE_ID") or None
            
            # Verificar si ya existe
            existing_folder = _find_folder_id(
                drive_service,
                style_name,
                parent_id=styles_folder_id,
                drive_id=drive_id
            )
            
            if existing_folder and not overwrite:
                result["styles_skipped"].append(style_name)
                current_app.logger.info(f"Estilo {style_name} ya existe, omitido")
                continue
            
            if not existing_folder:
                existing_folder = ensure_folder(
                    style_name,
                    parent_id=styles_folder_id,
                    drive_id=drive_id
                )
            
            # Subir imágenes desde assets locales
            local_folder = style_name.lower()
            local_path = Path(current_app.static_folder) / "images" / local_folder
            
            if local_path.exists():
                # Regla: Logo_AMPA.png es el origen; las variantes se generan.
                skipped_autogen = {"Logo_AMPA_400x400.png", "Logo_AMPA_64x64.png"}

                for img_file in local_path.iterdir():
                    if not (img_file.is_file() and img_file.suffix.lower() in [".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"]):
                        continue

                    if img_file.name in skipped_autogen:
                        continue

                    content = img_file.read_bytes()

                    # Normalizar tamaños si el archivo es un slot conocido
                    if img_file.name in STYLE_IMAGE_SPECS:
                        try:
                            outputs = prepare_style_slot_upload(img_file.name, content)
                            for target_name, out_bytes, mime in outputs:
                                upload_style_file(style_name, target_name, out_bytes, mime)
                                current_app.logger.info(f"  Subido (normalizado): {target_name}")
                        except Exception as exc:
                            current_app.logger.warning(f"  No se pudo normalizar {img_file.name}: {exc}")
                            mime_type, _ = mimetypes.guess_type(str(img_file))
                            upload_style_file(style_name, img_file.name, content, mime_type)
                            current_app.logger.info(f"  Subido: {img_file.name}")
                        continue

                    mime_type, _ = mimetypes.guess_type(str(img_file))
                    upload_style_file(style_name, img_file.name, content, mime_type)
                    current_app.logger.info(f"  Subido: {img_file.name}")
            
            # Generar y subir style.css
            css_content = _generate_style_css(style_name)
            upload_style_file(style_name, STYLE_CSS_FILENAME, css_content.encode("utf-8"), "text/css")
            current_app.logger.info(f"  Generado: {STYLE_CSS_FILENAME}")
            
            result["styles_created"].append(style_name)
            current_app.logger.info(f"Estilo {style_name} inicializado correctamente")
            
        except Exception as e:
            current_app.logger.error(f"Error inicializando estilo {style_name}: {e}")
            result["errors"].append(f"{style_name}: {str(e)}")
    
    if result["styles_created"]:
        result["message"] = f"Estilos inicializados: {', '.join(result['styles_created'])}"
    elif result["styles_skipped"]:
        result["message"] = "Todos los estilos ya existían"
    else:
        result["ok"] = False
        result["message"] = "No se pudo inicializar ningún estilo"
    
    return result


def get_style_css_content(style_name: str, with_fallback: bool = False) -> Optional[str]:
    """
    Obtiene el contenido del CSS de un estilo.
    
    Args:
        style_name: Nombre del estilo
        with_fallback: Si True, genera CSS por defecto cuando no se encuentra.
                      Usar False para el editor (para ver el contenido real).
                      Usar True para servir CSS público.
    """
    result = download_style_file(style_name, STYLE_CSS_FILENAME)
    if result:
        content, _ = result
        css_text = content.decode("utf-8")
        if css_text.strip():
            return css_text
    
    # Solo generar fallback si se solicita explícitamente
    if with_fallback:
        return _generate_style_css(style_name)
    
    return None


def save_style_css_content(style_name: str, css_content: str) -> bool:
    """Guarda el contenido del CSS de un estilo."""
    return upload_style_file(
        style_name,
        STYLE_CSS_FILENAME,
        css_content.encode("utf-8"),
        "text/css"
    )
