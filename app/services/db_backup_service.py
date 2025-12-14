"""
Backups de base de datos a Google Drive.

- Genera un dump (PostgreSQL vía pg_dump; SQLite copiando el fichero).
- Sube el backup a Drive dentro de: WEB Ampa/Backup DB_WEB
- Mantiene solo las N copias más recientes (por defecto 2).
"""

from __future__ import annotations

import gzip
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from flask import current_app
import pytz
from googleapiclient.http import MediaFileUpload
from sqlalchemy import text
from sqlalchemy.engine import URL, make_url

from app.extensions import db
from app.media_utils import _get_user_drive_service, ensure_folder


@dataclass(frozen=True)
class BackupResult:
    ok: bool
    message: str
    drive_file_id: str | None = None
    drive_folder_id: str | None = None
    local_path: str | None = None


def _bool_env(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _resolve_backup_filename(now: datetime) -> str:
    prefix = (current_app.config.get("DB_BACKUP_FILENAME_PREFIX") or "BD_WEB_Ampa_Julian_Nieto").strip()
    date_str = now.strftime("%d%m%Y")
    return f"{prefix}_{date_str}.sql.gz"


def _resolve_drive_backup_folder_id() -> tuple[str, str | None]:
    shared_drive_id = current_app.config.get("GOOGLE_DRIVE_SHARED_DRIVE_ID") or None
    root_name = (current_app.config.get("GOOGLE_DRIVE_ROOT_FOLDER_NAME") or "WEB Ampa").strip()
    root_id = current_app.config.get("GOOGLE_DRIVE_ROOT_FOLDER_ID") or None
    backup_id = (current_app.config.get("GOOGLE_DRIVE_DB_BACKUP_FOLDER_ID") or "").strip() or None
    backup_folder_name = (current_app.config.get("GOOGLE_DRIVE_DB_BACKUP_FOLDER_NAME") or "Backup DB_WEB").strip()

    if backup_id:
        return backup_id, shared_drive_id

    if root_id:
        root_folder_id = root_id
    else:
        root_folder_id = ensure_folder(root_name, parent_id=None, drive_id=shared_drive_id)

    backup_folder_id = ensure_folder(backup_folder_name, parent_id=root_folder_id, drive_id=shared_drive_id)
    return backup_folder_id, shared_drive_id


def _advisory_lock_postgres() -> bool:
    uri = current_app.config.get("SQLALCHEMY_DATABASE_URI") or ""
    if not str(uri).startswith("postgres"):
        return True

    # Clave estable (64-bit) para evitar ejecuciones duplicadas en varios workers.
    lock_key = 783_447_221_112_907_331
    try:
        got_lock = db.session.execute(
            text("SELECT pg_try_advisory_lock(:key)"),
            {"key": lock_key},
        ).scalar()
        return bool(got_lock)
    except Exception:  # noqa: BLE001
        return True


def _advisory_unlock_postgres() -> None:
    uri = current_app.config.get("SQLALCHEMY_DATABASE_URI") or ""
    if not str(uri).startswith("postgres"):
        return

    lock_key = 783_447_221_112_907_331
    try:
        db.session.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": lock_key})
        db.session.commit()
    except Exception:  # noqa: BLE001
        db.session.rollback()


def _dump_sqlite(db_url: URL, output_gz_path: Path) -> None:
    sqlite_path = (db_url.database or "").lstrip("/")
    if not sqlite_path:
        raise RuntimeError("SQLAlchemy SQLite URL inválida (sin ruta de archivo).")

    src = Path(sqlite_path)
    if not src.exists():
        raise FileNotFoundError(f"No existe el fichero SQLite: {src}")

    with src.open("rb") as f_in, gzip.open(output_gz_path, "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)


def _find_pg_dump_executable() -> str | None:
    explicit = (os.getenv("DB_BACKUP_PGDUMP_PATH") or "").strip()
    if explicit:
        return explicit

    found = shutil.which("pg_dump")
    if found:
        return found

    candidates: list[Path] = []
    if os.name == "nt":
        for env_key in ("ProgramFiles", "ProgramFiles(x86)"):
            base = os.environ.get(env_key)
            if not base:
                continue
            root = Path(base) / "PostgreSQL"
            if not root.exists():
                continue
            for ver_dir in root.iterdir():
                candidate = ver_dir / "bin" / "pg_dump.exe"
                if candidate.exists():
                    candidates.append(candidate)

        def _version_key(path: Path) -> tuple[int, ...]:
            try:
                return tuple(int(x) for x in path.parent.parent.name.split("."))
            except Exception:
                return (0,)

        if candidates:
            candidates.sort(key=_version_key, reverse=True)
            return str(candidates[0])

    for candidate in ("/usr/bin/pg_dump", "/usr/local/bin/pg_dump", "/opt/homebrew/bin/pg_dump"):
        if Path(candidate).exists():
            return candidate

    return None


def _dump_postgres(db_url: URL, output_gz_path: Path) -> None:
    pg_dump = _find_pg_dump_executable()
    if not pg_dump:
        raise RuntimeError(
            "No se encontró pg_dump. Instala PostgreSQL (cliente) y añade su carpeta bin al PATH "
            "o define DB_BACKUP_PGDUMP_PATH con la ruta completa a pg_dump."
        )

    sslmode = None
    try:
        sslmode = (db_url.query or {}).get("sslmode")  # type: ignore[union-attr]
    except Exception:
        sslmode = None

    env = os.environ.copy()
    if db_url.password is not None:
        env["PGPASSWORD"] = db_url.password
    if sslmode:
        env["PGSSLMODE"] = sslmode

    cmd = [
        pg_dump,
        "--host",
        db_url.host or "localhost",
        "--port",
        str(db_url.port or 5432),
        "--username",
        db_url.username or "postgres",
        "--dbname",
        db_url.database or "",
        "--no-owner",
        "--no-acl",
    ]

    with gzip.open(output_gz_path, "wb") as gz_out:
        proc = subprocess.Popen(  # noqa: S603
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        assert proc.stdout is not None
        assert proc.stderr is not None
        shutil.copyfileobj(proc.stdout, gz_out)
        _, stderr = proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError(f"pg_dump falló (code {proc.returncode}): {stderr.decode(errors='replace').strip()}")


def _create_db_backup_file(output_gz_path: Path) -> None:
    uri = current_app.config.get("SQLALCHEMY_DATABASE_URI") or ""
    db_url = make_url(uri)

    if db_url.drivername.startswith("sqlite"):
        _dump_sqlite(db_url, output_gz_path)
        return

    if db_url.drivername.startswith("postgresql"):
        _dump_postgres(db_url, output_gz_path)
        return

    raise RuntimeError(f"Driver de base de datos no soportado para backup: {db_url.drivername}")


def _upload_backup_to_drive(local_path: Path, filename: str) -> tuple[str, str]:
    drive_service = _get_user_drive_service()
    if drive_service is None:
        raise RuntimeError("Google Drive no está configurado o no se pudo autenticar.")

    folder_id, shared_drive_id = _resolve_drive_backup_folder_id()

    metadata: dict[str, Any] = {"name": filename, "parents": [folder_id]}
    if shared_drive_id:
        metadata["driveId"] = shared_drive_id

    media = MediaFileUpload(str(local_path), mimetype="application/gzip", resumable=True)
    created = (
        drive_service.files()
        .create(
            body=metadata,
            media_body=media,
            fields="id,name,createdTime",
            supportsAllDrives=True,
        )
        .execute()
    )
    file_id = created.get("id")
    if not file_id:
        raise RuntimeError("No se obtuvo ID del archivo creado en Drive.")

    return file_id, folder_id


def _enforce_retention(folder_id: str, *, keep: int) -> None:
    drive_service = _get_user_drive_service()
    if drive_service is None:
        return

    keep = max(1, int(keep))
    prefix = (current_app.config.get("DB_BACKUP_FILENAME_PREFIX") or "BD_WEB_Ampa_Julian_Nieto").strip() + "_"

    files: list[dict[str, Any]] = []
    page_token: str | None = None
    while True:
        resp = (
            drive_service.files()
            .list(
                q=(
                    f"'{folder_id}' in parents and trashed=false and "
                    f"mimeType!='application/vnd.google-apps.folder' and name contains '{prefix}'"
                ),
                spaces="drive",
                fields="nextPageToken,files(id,name,createdTime)",
                orderBy="createdTime asc",
                pageSize=100,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
                pageToken=page_token,
            )
            .execute()
        )
        files.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    if len(files) <= keep:
        return

    to_delete = files[: max(0, len(files) - keep)]
    for item in to_delete:
        file_id = item.get("id")
        if not file_id:
            continue
        try:
            drive_service.files().delete(fileId=file_id, supportsAllDrives=True).execute()
        except Exception as exc:  # noqa: BLE001
            current_app.logger.warning("No se pudo eliminar backup antiguo en Drive (%s): %s", file_id, exc)


def run_db_backup_to_drive(*, force: bool = False) -> BackupResult:
    if not force:
        if not _bool_env(current_app.config.get("DB_BACKUP_ENABLED")):
            return BackupResult(ok=False, message="Backup deshabilitado (DB_BACKUP_ENABLED=false).")

    if not _advisory_lock_postgres():
        return BackupResult(ok=True, message="Backup omitido: otro worker ya lo está ejecutando.")

    now = datetime.now(tz=pytz.timezone("Europe/Madrid"))
    filename = _resolve_backup_filename(now)
    keep = int(current_app.config.get("DB_BACKUP_RETENTION", 2) or 2)

    try:
        with tempfile.TemporaryDirectory(prefix="db_backup_") as tmp:
            output_path = Path(tmp) / filename
            _create_db_backup_file(output_path)
            file_id, folder_id = _upload_backup_to_drive(output_path, filename)
            _enforce_retention(folder_id, keep=keep)

        return BackupResult(
            ok=True,
            message="Backup subido a Drive correctamente.",
            drive_file_id=file_id,
            drive_folder_id=folder_id,
        )
    except Exception as exc:  # noqa: BLE001
        current_app.logger.exception("Error generando/subiendo backup BD a Drive")
        return BackupResult(ok=False, message=str(exc))
    finally:
        _advisory_unlock_postgres()
