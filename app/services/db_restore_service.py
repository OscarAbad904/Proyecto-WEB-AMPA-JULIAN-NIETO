"""
Restauración de base de datos desde backups almacenados en Google Drive.

Soporta:
- PostgreSQL: restaura un .sql.gz usando psql (requiere psql instalado).
- SQLite: restaura reemplazando el fichero (backup .gz del db file).
"""

from __future__ import annotations

import gzip
import io
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from flask import current_app
from googleapiclient.http import MediaIoBaseDownload
from sqlalchemy import text
from sqlalchemy.engine import URL, make_url

from app.extensions import db
from app.media_utils import _get_user_drive_service


@dataclass(frozen=True)
class RestoreResult:
    ok: bool
    message: str


def list_db_backups_from_drive(limit: int = 30) -> list[dict[str, Any]]:
    drive = _get_user_drive_service()
    if drive is None:
        raise RuntimeError("Google Drive no está configurado o no se pudo autenticar.")

    folder_id = (current_app.config.get("GOOGLE_DRIVE_DB_BACKUP_FOLDER_ID") or "").strip()
    if not folder_id:
        raise RuntimeError("Falta GOOGLE_DRIVE_DB_BACKUP_FOLDER_ID. Pulsa 'Configurar Drive'.")

    resp = (
        drive.files()
        .list(
            q=(f"'{folder_id}' in parents and trashed=false"),
            spaces="drive",
            fields="files(id,name,createdTime,size),nextPageToken",
            orderBy="createdTime desc",
            pageSize=max(1, min(100, int(limit))),
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        )
        .execute()
    )
    files = resp.get("files", []) or []
    return [
        {
            "id": f.get("id"),
            "name": f.get("name"),
            "createdTime": f.get("createdTime"),
            "size": f.get("size"),
        }
        for f in files
        if f.get("id") and f.get("name")
    ]


def _download_drive_file(file_id: str, dest_path: Path) -> None:
    drive = _get_user_drive_service()
    if drive is None:
        raise RuntimeError("Google Drive no está configurado o no se pudo autenticar.")

    request = drive.files().get_media(fileId=file_id, supportsAllDrives=True)
    with dest_path.open("wb") as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()


def _find_psql_executable() -> str | None:
    explicit = (os.getenv("DB_RESTORE_PSQL_PATH") or "").strip()
    if explicit:
        return explicit

    found = shutil.which("psql")
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
                candidate = ver_dir / "bin" / "psql.exe"
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

    for candidate in ("/usr/bin/psql", "/usr/local/bin/psql", "/opt/homebrew/bin/psql"):
        if Path(candidate).exists():
            return candidate

    return None


def _restore_sqlite(db_url: URL, backup_gz_path: Path) -> None:
    sqlite_path = (db_url.database or "").lstrip("/")
    if not sqlite_path:
        raise RuntimeError("SQLAlchemy SQLite URL inválida (sin ruta de archivo).")

    target = Path(sqlite_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    with gzip.open(backup_gz_path, "rb") as f_in, target.open("wb") as f_out:
        shutil.copyfileobj(f_in, f_out)


def _reset_public_schema() -> None:
    try:
        db.session.execute(text("DROP SCHEMA public CASCADE"))
        db.session.execute(text("CREATE SCHEMA public"))
        db.session.commit()
    except Exception:  # noqa: BLE001
        db.session.rollback()
        raise


def _restore_postgres(db_url: URL, backup_gz_path: Path) -> None:
    psql = _find_psql_executable()
    if not psql:
        raise RuntimeError(
            "No se encontró psql. Instala PostgreSQL (cliente) y añade su carpeta bin al PATH "
            "o define DB_RESTORE_PSQL_PATH con la ruta completa a psql."
        )

    # Dejar la BD en estado limpio para evitar conflictos con objetos existentes.
    _reset_public_schema()

    with tempfile.TemporaryDirectory(prefix="db_restore_") as tmp:
        sql_path = Path(tmp) / "restore.sql"
        with gzip.open(backup_gz_path, "rb") as f_in, sql_path.open("wb") as f_out:
            shutil.copyfileobj(f_in, f_out)

        env = os.environ.copy()
        if db_url.password is not None:
            env["PGPASSWORD"] = db_url.password

        try:
            sslmode = (db_url.query or {}).get("sslmode")  # type: ignore[union-attr]
        except Exception:
            sslmode = None
        if sslmode:
            env["PGSSLMODE"] = sslmode

        cmd = [
            psql,
            "--host",
            db_url.host or "localhost",
            "--port",
            str(db_url.port or 5432),
            "--username",
            db_url.username or "postgres",
            "--dbname",
            db_url.database or "",
            "--set",
            "ON_ERROR_STOP=on",
            "--single-transaction",
            "-f",
            str(sql_path),
        ]

        proc = subprocess.run(cmd, capture_output=True, text=True, env=env)  # noqa: S603
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout or "").strip() or f"psql falló (code {proc.returncode})")


def restore_db_from_drive_backup(file_id: str) -> RestoreResult:
    if not file_id:
        return RestoreResult(ok=False, message="Falta file_id.")

    uri = current_app.config.get("SQLALCHEMY_DATABASE_URI") or ""
    db_url = make_url(uri)

    drive = _get_user_drive_service()
    if drive is None:
        return RestoreResult(ok=False, message="Google Drive no está configurado o no se pudo autenticar.")

    try:
        meta = (
            drive.files()
            .get(fileId=file_id, fields="id,name,mimeType", supportsAllDrives=True)
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        return RestoreResult(ok=False, message=f"No se pudo acceder al backup en Drive: {exc}")

    name = meta.get("name") or ""
    if not name.endswith(".gz"):
        return RestoreResult(ok=False, message="El backup debe ser un archivo .gz (esperado .sql.gz).")

    try:
        with tempfile.TemporaryDirectory(prefix="drive_backup_") as tmp:
            gz_path = Path(tmp) / name
            _download_drive_file(file_id, gz_path)

            if db_url.drivername.startswith("sqlite"):
                _restore_sqlite(db_url, gz_path)
                return RestoreResult(ok=True, message="SQLite restaurado correctamente.")

            if db_url.drivername.startswith("postgresql"):
                _restore_postgres(db_url, gz_path)
                return RestoreResult(ok=True, message="PostgreSQL restaurado correctamente.")

            return RestoreResult(ok=False, message=f"Driver no soportado para restauración: {db_url.drivername}")
    except Exception as exc:  # noqa: BLE001
        current_app.logger.exception("Error restaurando la base de datos desde backup")
        return RestoreResult(ok=False, message=str(exc))
