from __future__ import annotations

from io import BytesIO
import mimetypes
from typing import Any

from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

from app.media_utils import _get_user_drive_service


def list_drive_files(folder_id: str, *, drive_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    drive = _get_user_drive_service()
    if drive is None:
        raise RuntimeError("Google Drive no esta configurado o no se pudo autenticar.")

    kwargs: dict[str, Any] = {
        "q": (
            f"'{folder_id}' in parents and trashed=false and "
            "mimeType!='application/vnd.google-apps.folder'"
        ),
        "spaces": "drive",
        "fields": "files(id,name,createdTime,modifiedTime,mimeType,size),nextPageToken",
        "orderBy": "modifiedTime desc",
        "pageSize": max(1, min(200, int(limit))),
        "supportsAllDrives": True,
        "includeItemsFromAllDrives": True,
    }
    if drive_id:
        kwargs["corpora"] = "drive"
        kwargs["driveId"] = drive_id

    resp = drive.files().list(**kwargs).execute()
    files = resp.get("files", []) or []
    return [
        {
            "id": f.get("id"),
            "name": f.get("name"),
            "createdTime": f.get("createdTime"),
            "modifiedTime": f.get("modifiedTime"),
            "mimeType": f.get("mimeType"),
            "size": f.get("size"),
        }
        for f in files
        if f.get("id")
        and f.get("name")
        and f.get("mimeType") != "application/vnd.google-apps.folder"
    ]


def delete_drive_file(file_id: str) -> None:
    drive = _get_user_drive_service()
    if drive is None:
        raise RuntimeError("Google Drive no esta configurado o no se pudo autenticar.")

    drive.files().delete(fileId=file_id, supportsAllDrives=True).execute()


def find_drive_file_by_name(
    folder_id: str,
    name: str,
    *,
    drive_id: str | None = None,
) -> dict[str, Any] | None:
    drive = _get_user_drive_service()
    if drive is None:
        raise RuntimeError("Google Drive no esta configurado o no se pudo autenticar.")

    safe_name = name.replace("'", "\\'")
    kwargs: dict[str, Any] = {
        "q": f"'{folder_id}' in parents and trashed=false and name='{safe_name}'",
        "spaces": "drive",
        "fields": "files(id,name,createdTime,modifiedTime,mimeType,size)",
        "pageSize": 1,
        "supportsAllDrives": True,
        "includeItemsFromAllDrives": True,
    }
    if drive_id:
        kwargs["corpora"] = "drive"
        kwargs["driveId"] = drive_id

    resp = drive.files().list(**kwargs).execute()
    files = resp.get("files", []) or []
    if not files:
        return None
    return files[0]


def upload_drive_file(
    folder_id: str,
    file_storage,
    *,
    name: str | None = None,
    drive_id: str | None = None,
    overwrite_file_id: str | None = None,
) -> dict[str, Any]:
    drive = _get_user_drive_service()
    if drive is None:
        raise RuntimeError("Google Drive no esta configurado o no se pudo autenticar.")

    filename = (name or getattr(file_storage, "filename", "") or "").strip()
    if not filename:
        raise ValueError("Nombre de archivo invalido.")

    mime_type = (
        getattr(file_storage, "mimetype", None)
        or mimetypes.guess_type(filename)[0]
        or "application/octet-stream"
    )
    media = MediaIoBaseUpload(file_storage.stream, mimetype=mime_type, resumable=False)

    if overwrite_file_id:
        request = drive.files().update(
            fileId=overwrite_file_id,
            media_body=media,
            fields="id,name,createdTime,modifiedTime",
            supportsAllDrives=True,
        )
    else:
        body = {"name": filename, "parents": [folder_id]}
        if drive_id:
            body["driveId"] = drive_id
        request = drive.files().create(
            body=body,
            media_body=media,
            fields="id,name,createdTime,modifiedTime",
            supportsAllDrives=True,
        )
    return request.execute()


def get_drive_file_meta(file_id: str) -> dict[str, Any]:
    drive = _get_user_drive_service()
    if drive is None:
        raise RuntimeError("Google Drive no esta configurado o no se pudo autenticar.")

    return (
        drive.files()
        .get(
            fileId=file_id,
            fields="id,name,parents,mimeType,createdTime,modifiedTime",
            supportsAllDrives=True,
        )
        .execute()
    )


def download_drive_file(file_id: str) -> tuple[BytesIO, dict[str, Any]]:
    drive = _get_user_drive_service()
    if drive is None:
        raise RuntimeError("Google Drive no esta configurado o no se pudo autenticar.")

    meta = get_drive_file_meta(file_id)
    request = drive.files().get_media(fileId=file_id, supportsAllDrives=True)
    buffer = BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    buffer.seek(0)
    return buffer, meta
