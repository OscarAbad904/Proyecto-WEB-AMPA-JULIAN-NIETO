"""
Utilidades de imagen y subida a Google Drive para las noticias.

Genera variantes optimizadas con Pillow y las envía a Drive usando
OAuth de usuario (token persistido en token_drive.json).
"""

from __future__ import annotations

import uuid
import time
import re
from pathlib import Path
from typing import Dict, Tuple
from io import BytesIO

from flask import current_app
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from googleapiclient.errors import HttpError
from google_auth_oauthlib.flow import InstalledAppFlow
from PIL import Image

import threading

# Tamaños solicitados para las noticias, por orientación
IMAGE_SIZES_NEWS: Dict[str, Dict[str, Tuple[int, int]]] = {
    "vertical": {
        "latest": (337, 552),   # últimas noticias / miniaturas
        "modal": (476, 663),    # modal vertical (mayor)
    },
    "horizontal": {
        "latest": (677, 382),   # últimas noticias / miniaturas
        "modal": (957, 537),    # modal horizontal (mayor)
    },
}

# Scopes unificados para Drive y Calendar (compartidos con calendar_service.py)
SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/calendar.events",
]

# Almacenamiento local al hilo para evitar problemas de SSL/concurrencia
_thread_local = threading.local()


def _get_user_drive_service():
    """
    Inicializa (o reutiliza) el cliente de Google Drive autenticado como usuario.
    Guarda/lee el token en token_drive.json.
    
    Usa threading.local() para evitar errores de SSL record layer failure
    al compartir el cliente entre hilos.
    """
    if hasattr(_thread_local, "drive_service") and _thread_local.drive_service is not None:
        return _thread_local.drive_service

    try:
        base_path = Path(current_app.config.get("ROOT_PATH") or current_app.root_path)
        token_path = base_path / "token_drive.json"
        token_env = current_app.config.get("GOOGLE_DRIVE_TOKEN_JSON")
        if token_env and not token_path.exists():
            try:
                token_path.parent.mkdir(parents=True, exist_ok=True)
                token_path.write_text(token_env, encoding="utf-8")
            except Exception as exc:  # noqa: BLE001
                current_app.logger.warning(
                    "No se pudo escribir token_drive.json desde GOOGLE_DRIVE_TOKEN_JSON: %s",
                    exc,
                )

        credentials_path = Path(current_app.config["GOOGLE_DRIVE_OAUTH_CREDENTIALS_FILE"])
        creds_json = current_app.config.get("GOOGLE_DRIVE_OAUTH_CREDENTIALS_JSON")
        if creds_json and not credentials_path.exists():
            try:
                credentials_path.parent.mkdir(parents=True, exist_ok=True)
                credentials_path.write_text(creds_json, encoding="utf-8")
            except Exception as exc:  # noqa: BLE001
                current_app.logger.warning(
                    "No se pudo escribir credentials_drive_oauth.json desde GOOGLE_DRIVE_OAUTH_CREDENTIALS_JSON: %s",
                    exc,
                )

        creds = None
        if token_path.exists():
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not credentials_path.exists():
                    current_app.logger.warning(
                        "No se encontro el archivo de credenciales de OAuth de Drive. "
                        "Las imágenes se guardarán localmente."
                    )
                    return None
                    
                # Verificar que las credenciales no sean valores de demostración
                creds_content = credentials_path.read_text(encoding="utf-8")
                if "TU_CLIENT_ID" in creds_content or "TU_SECRET" in creds_content:
                    current_app.logger.warning(
                        "Las credenciales de Google Drive contienen valores de demostración. "
                        "Las imágenes se guardarán localmente."
                    )
                    return None
                    
                flow = InstalledAppFlow.from_client_secrets_file(
                    current_app.config["GOOGLE_DRIVE_OAUTH_CREDENTIALS_FILE"],
                    SCOPES,
                )
                creds = flow.run_local_server(port=0)
            with open(token_path, "w", encoding="utf-8") as token:
                token.write(creds.to_json())

        _thread_local.drive_service = build("drive", "v3", credentials=creds)
        return _thread_local.drive_service
    except Exception as exc:  # noqa: BLE001
        current_app.logger.warning(
            "Error inicializando Google Drive service: %s. Las imágenes se guardarán localmente.",
            exc,
        )
        return None



def _slugify_name(value: str | None, default: str = "noticia") -> str:
    if not value:
        return default
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip().lower()).strip("-")
    return slug or default


def _find_folder_id(
    drive_service,
    name: str,
    parent_id: str | None = None,
    drive_id: str | None = None,
) -> str | None:
    # En Unidades compartidas (Shared Drives), para buscar en el "raíz" de la unidad
    # hay que usar como parent el propio `drive_id`.
    if drive_id and not parent_id:
        parent_id = drive_id
    elif not parent_id:
        parent_id = "root"

    query_parts = [
        "mimeType='application/vnd.google-apps.folder'",
        "trashed=false",
        f"name='{name}'",
    ]
    if parent_id:
        query_parts.append(f"'{parent_id}' in parents")
    query = " and ".join(query_parts)
    list_kwargs = {
        "q": query,
        "spaces": "drive",
        "fields": "files(id,name)",
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
        return files[0].get("id")
    return None


def ensure_folder(name: str, parent_id: str | None = None, drive_id: str | None = None) -> str:
    """Busca o crea una carpeta en Drive (o Shared Drive) y devuelve su id."""
    drive = _get_user_drive_service()
    if drive is None:
        raise RuntimeError("No se pudo inicializar Google Drive (credenciales/token no disponibles).")

    # En Unidades compartidas, si no se especifica parent, colgar del "raíz" de la unidad.
    if drive_id and not parent_id:
        parent_id = drive_id

    existing = _find_folder_id(drive, name, parent_id, drive_id)
    if existing:
        return existing
    metadata = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    if parent_id:
        metadata["parents"] = [parent_id]
    folder = drive.files().create(
        body=metadata,
        fields="id",
        supportsAllDrives=True,
    ).execute()
    return folder.get("id")


def _get_folder_name_by_id(drive_service, folder_id: str, drive_id: str | None = None) -> str | None:
    try:
        resp = (
            drive_service.files()
            .get(
                fileId=folder_id,
                fields="id,name,mimeType",
                supportsAllDrives=True,
            )
            .execute()
        )
    except Exception:  # noqa: BLE001
        return None
    if resp.get("mimeType") != "application/vnd.google-apps.folder":
        return None
    return resp.get("name")


def resolve_drive_root_folder_id(drive_service, drive_id: str | None = None) -> str:
    """
    Resuelve el ID de la carpeta raíz configurada para Drive.

    Prioriza `GOOGLE_DRIVE_ROOT_FOLDER_ID` cuando esta configurado. Si no existe o no es
    accesible, se busca/crea por nombre (`GOOGLE_DRIVE_ROOT_FOLDER_NAME`).
    """
    root_name = (current_app.config.get("GOOGLE_DRIVE_ROOT_FOLDER_NAME") or "WEB Ampa").strip()
    configured_root_id = (current_app.config.get("GOOGLE_DRIVE_ROOT_FOLDER_ID") or "").strip() or None

    if configured_root_id:
        try:
            meta = (
                drive_service.files()
                .get(
                    fileId=configured_root_id,
                    fields="id,name,mimeType,parents",
                    supportsAllDrives=True,
                )
                .execute()
            )
        except Exception:  # noqa: BLE001
            meta = None

        if not meta or meta.get("mimeType") != "application/vnd.google-apps.folder":
            configured_root_id = None
        else:
            resolved_name = (meta.get("name") or "").strip()
            parents = meta.get("parents") or []

            # Si la carpeta existe pero estÃ¡ "huÃ©rfana" (sin parents) en Mi unidad, colgarla de root.
            if not drive_id and not parents:
                try:
                    drive_service.files().update(
                        fileId=configured_root_id,
                        addParents="root",
                        fields="id,parents",
                        supportsAllDrives=True,
                    ).execute()
                except Exception:  # noqa: BLE001
                    pass

            # Si el ID estÃ¡ configurado pero el nombre no coincide con el .env, renombrar.
            if root_name and resolved_name and resolved_name != root_name:
                try:
                    drive_service.files().update(
                        fileId=configured_root_id,
                        body={"name": root_name},
                        fields="id,name",
                        supportsAllDrives=True,
                    ).execute()
                except Exception:  # noqa: BLE001
                    pass

    if configured_root_id:
        return configured_root_id

    legacy_root_name = "Imagenes WEB Ampa"
    root_parent = drive_id or "root"
    existing_root = _find_folder_id(drive_service, root_name, parent_id=root_parent, drive_id=drive_id)
    if not existing_root and root_name == "WEB Ampa":
        existing_root = _find_folder_id(drive_service, legacy_root_name, parent_id=root_parent, drive_id=drive_id)
    return existing_root or ensure_folder(root_name, parent_id=None, drive_id=drive_id)


def _crop_to_aspect(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """Recorta centrado para ajustar el aspect ratio antes de escalar.

    Nota: mantenemos la función por compatibilidad, pero las variantes de noticias/eventos
    ya no deben recortar (se usa escalado proporcional).
    """
    src_w, src_h = img.size
    src_ratio = src_w / src_h
    target_ratio = target_w / target_h

    if src_ratio > target_ratio:
        new_w = int(src_h * target_ratio)
        offset = (src_w - new_w) // 2
        box = (offset, 0, offset + new_w, src_h)
    else:
        new_h = int(src_w / target_ratio)
        offset = (src_h - new_h) // 2
        box = (0, offset, src_w, offset + new_h)

    return img.crop(box)


def _resize_contain(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """Escala proporcionalmente para que quepa en (target_w, target_h) sin recortar."""
    working = img.copy()
    working.thumbnail((int(target_w), int(target_h)), Image.LANCZOS)
    return working


def _export_to_bytes(img: Image.Image, fmt: str = "JPEG", quality: int = 80) -> bytes:
    """Convierte una imagen Pillow a bytes comprimidos."""
    buffer = BytesIO()
    save_kwargs = {"format": fmt.upper()}
    if fmt.upper() in ("JPEG", "WEBP"):
        save_kwargs["quality"] = quality
        save_kwargs["optimize"] = True
    img.save(buffer, **save_kwargs)
    buffer.seek(0)
    return buffer.read()


def generate_news_variants(file_storage, fmt: str = "JPEG", quality: int = 80) -> Dict[str, bytes]:
    """
    Crea las variantes para noticias a partir de un FileStorage.

    Devuelve un dict {clave: bytes_imagen}.
    """
    file_storage.stream.seek(0)
    with Image.open(file_storage.stream) as img:
        # Respetar orientación EXIF (móviles) para evitar "recortes" aparentes.
        try:
            from PIL import ImageOps

            img = ImageOps.exif_transpose(img)
        except Exception:  # noqa: BLE001
            pass

        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")

        is_vertical = img.height > img.width
        orientation = "vertical" if is_vertical else "horizontal"
        sizes = IMAGE_SIZES_NEWS[orientation]

        variants_bytes: Dict[str, bytes] = {}
        for key, (w, h) in sizes.items():
            resized = _resize_contain(img, w, h)
            variants_bytes[key] = _export_to_bytes(resized, fmt=fmt, quality=quality)

    file_storage.stream.seek(0)
    return variants_bytes


def upload_image_bytes_to_drive(
    image_bytes: bytes,
    filename: str,
    folder_id: str,
    mimetype: str,
    drive_id: str | None = None,
) -> str:
    """
    Sube bytes a una carpeta de Drive usando OAuth de usuario y devuelve el enlace público.
    """
    drive_service = _get_user_drive_service()
    metadata = {"name": filename}
    if folder_id:
        metadata["parents"] = [folder_id]
    if drive_id:
        metadata["driveId"] = drive_id

    media = MediaIoBaseUpload(BytesIO(image_bytes), mimetype=mimetype, resumable=False)

    created = _execute_with_retry(
        lambda: drive_service.files()
        .create(
            body=metadata,
            media_body=media,
            fields="id",
            supportsAllDrives=True,
        )
        .execute()
    )
    file_id = created.get("id")

    # Pausa ligera para evitar rate limits encadenados
    time.sleep(0.15)

    _execute_with_retry(
        lambda: drive_service.permissions()
        .create(
            fileId=file_id,
            body={"type": "anyone", "role": "reader"},
            fields="id",
        )
        .execute()
    )

    return f"https://drive.google.com/uc?id={file_id}"


def upload_news_image_variants(
    file_storage,
    base_name: str | None = None,
    parent_folder_id: str | None = None,
    folder_name: str | None = None,
    shared_drive_id: str | None = None,
) -> Dict[str, str]:
    """
    Genera y sube las variantes (latest/modal) a Drive o localmente.

    Si no hay credenciales válidas de Drive, guarda localmente.
    Devuelve un dict con las URLs públicas.
    """
    fmt = current_app.config.get("NEWS_IMAGE_FORMAT", "JPEG").upper()
    quality = int(current_app.config.get("NEWS_IMAGE_QUALITY", 80))
    mimetype = "image/jpeg" if fmt == "JPEG" else f"image/{fmt.lower()}"

    base_slug = _slugify_name(base_name)
    variants_bytes = generate_news_variants(file_storage, fmt=fmt, quality=quality)
    urls: Dict[str, str] = {}

    filename_map = {
        "latest": f"{base_slug}_Ultimas_noticias.{fmt.lower()}",
        "modal": f"{base_slug}_Modal.{fmt.lower()}",
    }

    # Intentar usar Google Drive, si no está disponible guardar localmente
    drive_service = _get_user_drive_service()
    
    if drive_service is None:
        # Guardar localmente en uploads/
        uploads_dir = Path(current_app.static_folder) / "uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)
        
        for key, img_bytes in variants_bytes.items():
            filename = filename_map.get(key, f"{base_slug}_{key}.{fmt.lower()}")
            file_path = uploads_dir / filename
            file_path.write_bytes(img_bytes)
            urls[key] = f"/assets/uploads/{filename}"
            current_app.logger.info(f"Imagen guardada localmente: {filename}")
    else:
        # Usar Google Drive
        default_folder_name = current_app.config.get("GOOGLE_DRIVE_NEWS_FOLDER_NAME", "Noticias")
        target_folder_name = folder_name or default_folder_name
        target_drive = shared_drive_id or current_app.config.get("GOOGLE_DRIVE_SHARED_DRIVE_ID", "") or None

        target_folder_id = None
        configured_news_id = current_app.config.get("GOOGLE_DRIVE_NEWS_FOLDER_ID", "") or None
        # Compatibilidad:
        # - Si `parent_folder_id` se pasa explícitamente, se interpreta como carpeta padre.
        # - Si `GOOGLE_DRIVE_NEWS_FOLDER_ID` apunta a la subcarpeta "Noticias", se usa directamente.
        # - Si `GOOGLE_DRIVE_NEWS_FOLDER_ID` apunta a la carpeta raíz, se cuelga "Noticias" dentro.
        if parent_folder_id:
            target_parent = parent_folder_id
        elif configured_news_id:
            configured_name = _get_folder_name_by_id(drive_service, configured_news_id, drive_id=target_drive)
            if not configured_name:
                target_parent = None
            elif configured_name == target_folder_name:
                target_folder_id = configured_news_id
                target_parent = None
            else:
                target_parent = configured_news_id
        else:
            target_parent = None

        if target_folder_id is None and not target_parent:
            target_parent = resolve_drive_root_folder_id(drive_service, drive_id=target_drive)
         
        try:
            if target_folder_id is None:
                target_folder_id = ensure_folder(target_folder_name, target_parent, target_drive)

            for key, img_bytes in variants_bytes.items():
                filename = filename_map.get(key, f"{base_slug}_{key}.{fmt.lower()}")
                urls[key] = upload_image_bytes_to_drive(
                    img_bytes,
                    filename,
                    target_folder_id,
                    mimetype=mimetype,
                    drive_id=target_drive,
                )
        except Exception as exc:  # noqa: BLE001
            current_app.logger.warning(
                "Error subiendo a Google Drive, guardando localmente: %s", exc
            )
            # Fallback a guardado local
            uploads_dir = Path(current_app.static_folder) / "uploads"
            uploads_dir.mkdir(parents=True, exist_ok=True)
            
            for key, img_bytes in variants_bytes.items():
                filename = filename_map.get(key, f"{base_slug}_{key}.{fmt.lower()}")
                file_path = uploads_dir / filename
                file_path.write_bytes(img_bytes)
                urls[key] = f"/assets/uploads/{filename}"

    return urls


def upload_event_image_variants(
    file_storage,
    base_name: str | None = None,
    parent_folder_id: str | None = None,
    folder_name: str | None = None,
    shared_drive_id: str | None = None,
) -> Dict[str, str]:
    """Igual que `upload_news_image_variants`, pero usando la carpeta de Eventos.

    Respeta la misma lógica de compatibilidad:
    - Si `parent_folder_id` se pasa explícitamente, se interpreta como carpeta padre.
    - Si `GOOGLE_DRIVE_EVENTS_FOLDER_ID` apunta a la subcarpeta "Eventos", se usa directamente.
    - Si `GOOGLE_DRIVE_EVENTS_FOLDER_ID` apunta a la carpeta raíz, se cuelga "Eventos" dentro.
    """

    fmt = current_app.config.get("NEWS_IMAGE_FORMAT", "JPEG").upper()
    quality = int(current_app.config.get("NEWS_IMAGE_QUALITY", 80))
    mimetype = "image/jpeg" if fmt == "JPEG" else f"image/{fmt.lower()}"

    base_slug = _slugify_name(base_name)
    variants_bytes = generate_news_variants(file_storage, fmt=fmt, quality=quality)
    urls: Dict[str, str] = {}

    filename_map = {
        "latest": f"{base_slug}_Evento.{fmt.lower()}",
        "modal": f"{base_slug}_Evento_Modal.{fmt.lower()}",
    }

    drive_service = _get_user_drive_service()
    if drive_service is None:
        uploads_dir = Path(current_app.static_folder) / "uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)

        for key, img_bytes in variants_bytes.items():
            filename = filename_map.get(key, f"{base_slug}_{key}.{fmt.lower()}")
            file_path = uploads_dir / filename
            file_path.write_bytes(img_bytes)
            urls[key] = f"/assets/uploads/{filename}"
            current_app.logger.info(f"Imagen de evento guardada localmente: {filename}")
        return urls

    default_folder_name = current_app.config.get("GOOGLE_DRIVE_EVENTS_FOLDER_NAME", "Eventos")
    target_folder_name = folder_name or default_folder_name
    target_drive = shared_drive_id or current_app.config.get("GOOGLE_DRIVE_SHARED_DRIVE_ID", "") or None

    target_folder_id = None
    configured_events_id = current_app.config.get("GOOGLE_DRIVE_EVENTS_FOLDER_ID", "") or None

    if parent_folder_id:
        target_parent = parent_folder_id
    elif configured_events_id:
        configured_name = _get_folder_name_by_id(drive_service, configured_events_id, drive_id=target_drive)
        if not configured_name:
            target_parent = None
        elif configured_name == target_folder_name:
            target_folder_id = configured_events_id
            target_parent = None
        else:
            target_parent = configured_events_id
    else:
        target_parent = None

    if target_folder_id is None and not target_parent:
        target_parent = resolve_drive_root_folder_id(drive_service, drive_id=target_drive)

    try:
        if target_folder_id is None:
            target_folder_id = ensure_folder(target_folder_name, target_parent, target_drive)

        for key, img_bytes in variants_bytes.items():
            filename = filename_map.get(key, f"{base_slug}_{key}.{fmt.lower()}")
            urls[key] = upload_image_bytes_to_drive(
                img_bytes,
                filename,
                target_folder_id,
                mimetype=mimetype,
                drive_id=target_drive,
            )
    except Exception as exc:  # noqa: BLE001
        current_app.logger.warning(
            "Error subiendo imagen de evento a Google Drive, guardando localmente: %s", exc
        )
        uploads_dir = Path(current_app.static_folder) / "uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)

        for key, img_bytes in variants_bytes.items():
            filename = filename_map.get(key, f"{base_slug}_{key}.{fmt.lower()}")
            file_path = uploads_dir / filename
            file_path.write_bytes(img_bytes)
            urls[key] = f"/assets/uploads/{filename}"

    return urls


def _is_rate_limit_error(err: HttpError) -> bool:
    """Detecta errores típicos de rate limit de Drive."""
    if err.resp is not None and err.resp.status in (403, 429):
        try:
            reason = err.error_details[0].get("reason") if err.error_details else ""
        except Exception:
            reason = ""
        if reason in {"userRateLimitExceeded", "rateLimitExceeded"}:
            return True
    return False


def _execute_with_retry(fn, retries: int = 3, base_sleep: float = 0.3):
    """Ejecuta una llamada a la API de Drive con reintentos sencillos."""
    for attempt in range(retries):
        try:
            return fn()
        except HttpError as err:
            if _is_rate_limit_error(err) and attempt < retries - 1:
                time.sleep(base_sleep * (attempt + 1))
                continue
            raise


def _extract_file_id_from_drive_url(url: str) -> str | None:
    """
    Extrae el ID de archivo de una URL de Google Drive.
    
    Soporta formatos:
    - https://drive.google.com/uc?id=FILE_ID
    - https://drive.google.com/file/d/FILE_ID/view
    """
    if not url or not isinstance(url, str):
        return None
    
    # Formato: https://drive.google.com/uc?id=FILE_ID
    if "id=" in url:
        try:
            return url.split("id=")[1].split("&")[0]
        except IndexError:
            pass
    
    # Formato: https://drive.google.com/file/d/FILE_ID/view
    if "/file/d/" in url:
        try:
            return url.split("/file/d/")[1].split("/")[0]
        except IndexError:
            pass
    
    return None


def delete_file_from_drive(file_id: str) -> bool:
    """
    Elimina un archivo de Google Drive por su ID.
    
    Devuelve True si se eliminó correctamente, False si hay error.
    """
    if not file_id:
        return False
    
    try:
        drive_service = _get_user_drive_service()
        if drive_service is None:
            current_app.logger.warning(
                "No se pudo obtener el servicio de Drive. El archivo %s no se eliminará.", file_id
            )
            return False
        
        _execute_with_retry(
            lambda: drive_service.files()
            .delete(fileId=file_id, supportsAllDrives=True)
            .execute()
        )
        current_app.logger.info(f"Archivo eliminado de Drive: {file_id}")
        return True
    except HttpError as err:
        if err.resp and err.resp.status == 404:
            # El archivo ya no existe en Drive
            current_app.logger.warning(f"Archivo no encontrado en Drive (ya eliminado): {file_id}")
            return True
        current_app.logger.error(f"Error eliminando archivo de Drive {file_id}: {err}")
        return False
    except Exception as exc:  # noqa: BLE001
        current_app.logger.error(f"Error eliminando archivo de Drive {file_id}: {exc}")
        return False


def delete_news_images(cover_image_url: str | None, image_variants: dict | None) -> None:
    """
    Elimina todas las imágenes de una noticia (cover_image + variantes) de Drive.
    
    Si las imágenes están en local (/assets/uploads/), las elimina del filesystem.
    Si están en Drive, las elimina de allí.
    """
    files_to_delete = []
    
    # Agregar cover_image
    if cover_image_url:
        files_to_delete.append(cover_image_url)
    
    # Agregar variantes (latest y modal)
    if image_variants and isinstance(image_variants, dict):
        for variant_url in image_variants.values():
            if variant_url:
                files_to_delete.append(variant_url)
    
    for file_url in files_to_delete:
        if not file_url:
            continue
        
        # Si es una URL local
        if file_url.startswith("/assets/uploads/"):
            try:
                file_path = Path(current_app.static_folder) / file_url.replace("/assets/", "")
                if file_path.exists():
                    file_path.unlink()
                    current_app.logger.info(f"Imagen local eliminada: {file_url}")
            except Exception as exc:  # noqa: BLE001
                current_app.logger.error(f"Error eliminando imagen local {file_url}: {exc}")
        # Si es una URL de Drive
        elif "drive.google.com" in file_url:
            file_id = _extract_file_id_from_drive_url(file_url)
            if file_id:
                delete_file_from_drive(file_id)
