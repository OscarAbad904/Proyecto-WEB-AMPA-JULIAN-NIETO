from __future__ import annotations

from flask import current_app

from app.extensions import db
from app.media_utils import (
    _get_folder_name_by_id,
    _get_user_drive_service,
    ensure_folder,
    resolve_drive_root_folder_id,
)
from app.models import Commission, CommissionProject


def _normalize_label(value: str | None, fallback: str) -> str:
    label = (value or "").strip()
    return label or fallback


def _get_drive_folder_meta(drive_service, folder_id: str) -> dict | None:
    try:
        meta = (
            drive_service.files()
            .get(
                fileId=folder_id,
                fields="id,name,mimeType",
                supportsAllDrives=True,
            )
            .execute()
        )
    except Exception:
        return None
    if meta.get("mimeType") != "application/vnd.google-apps.folder":
        return None
    return meta


def _rename_drive_folder(drive_service, folder_id: str, new_name: str, drive_id: str | None) -> bool:
    if not new_name:
        return False
    current_name = _get_folder_name_by_id(drive_service, folder_id, drive_id=drive_id)
    if not current_name:
        return False
    if current_name == new_name:
        return True
    try:
        drive_service.files().update(
            fileId=folder_id,
            body={"name": new_name},
            fields="id,name",
            supportsAllDrives=True,
        ).execute()
        return True
    except Exception as exc:
        current_app.logger.warning("No se pudo renombrar carpeta de Drive %s: %s", folder_id, exc)
        return False


def resolve_commissions_root_folder_id(drive_service=None) -> str | None:
    drive_service = drive_service or _get_user_drive_service()
    if drive_service is None:
        return None

    shared_drive_id = current_app.config.get("GOOGLE_DRIVE_SHARED_DRIVE_ID") or None
    root_id = resolve_drive_root_folder_id(drive_service, drive_id=shared_drive_id)
    commissions_name = _normalize_label(
        current_app.config.get("GOOGLE_DRIVE_COMMISSIONS_FOLDER_NAME"),
        "Comisiones",
    )
    commissions_id = (current_app.config.get("GOOGLE_DRIVE_COMMISSIONS_FOLDER_ID") or "").strip() or None

    if commissions_id:
        meta = _get_drive_folder_meta(drive_service, commissions_id)
        if not meta:
            commissions_id = None
        else:
            current_name = meta.get("name") or ""
            if commissions_name and current_name != commissions_name:
                _rename_drive_folder(drive_service, commissions_id, commissions_name, shared_drive_id)

    if not commissions_id:
        commissions_id = ensure_folder(commissions_name, parent_id=root_id, drive_id=shared_drive_id)

    return commissions_id


def ensure_commission_drive_folder(
    commission: Commission,
    *,
    drive_service=None,
    commit: bool = True,
) -> str | None:
    drive_service = drive_service or _get_user_drive_service()
    if drive_service is None:
        return None

    shared_drive_id = current_app.config.get("GOOGLE_DRIVE_SHARED_DRIVE_ID") or None
    try:
        commissions_root_id = resolve_commissions_root_folder_id(drive_service)
    except Exception as exc:
        current_app.logger.warning("No se pudo resolver carpeta Comisiones en Drive: %s", exc)
        return None

    fallback = f"Comision {commission.id}" if commission.id else "Comision"
    target_name = _normalize_label(getattr(commission, "name", None), fallback)
    folder_id = (getattr(commission, "drive_folder_id", None) or "").strip() or None
    updated = False

    if folder_id:
        meta = _get_drive_folder_meta(drive_service, folder_id)
        if not meta:
            folder_id = None
        else:
            current_name = meta.get("name") or ""
            if target_name and current_name != target_name:
                _rename_drive_folder(drive_service, folder_id, target_name, shared_drive_id)

    if not folder_id:
        folder_id = ensure_folder(target_name, parent_id=commissions_root_id, drive_id=shared_drive_id)
        commission.drive_folder_id = folder_id
        updated = True

    if updated and commit:
        db.session.commit()

    return folder_id


def ensure_project_drive_folder(
    project: CommissionProject,
    *,
    drive_service=None,
    commit: bool = True,
) -> str | None:
    drive_service = drive_service or _get_user_drive_service()
    if drive_service is None:
        return None

    shared_drive_id = current_app.config.get("GOOGLE_DRIVE_SHARED_DRIVE_ID") or None
    commission = project.commission or Commission.query.get(project.commission_id)
    if commission is None:
        return None

    commission_folder_id = commission.drive_folder_id or ensure_commission_drive_folder(
        commission,
        drive_service=drive_service,
        commit=commit,
    )
    if not commission_folder_id:
        return None

    title = (getattr(project, "title", None) or "").strip()
    target_name = f"Proyecto {title}" if title else f"Proyecto {project.id or ''}".strip()
    folder_id = (getattr(project, "drive_folder_id", None) or "").strip() or None
    updated = False

    if folder_id:
        meta = _get_drive_folder_meta(drive_service, folder_id)
        if not meta:
            folder_id = None
        else:
            current_name = meta.get("name") or ""
            if target_name and current_name != target_name:
                _rename_drive_folder(drive_service, folder_id, target_name, shared_drive_id)

    if not folder_id:
        folder_id = ensure_folder(target_name, parent_id=commission_folder_id, drive_id=shared_drive_id)
        project.drive_folder_id = folder_id
        updated = True

    if updated and commit:
        db.session.commit()

    return folder_id


def sync_commission_drive_folders() -> dict:
    drive_service = _get_user_drive_service()
    if drive_service is None:
        raise RuntimeError("No se pudo autenticar con Google Drive.")

    commissions = Commission.query.order_by(Commission.id.asc()).all()
    projects = CommissionProject.query.order_by(CommissionProject.id.asc()).all()

    result = {
        "commissions_total": len(commissions),
        "projects_total": len(projects),
        "commissions_created": 0,
        "projects_created": 0,
        "errors": [],
    }
    pending_updates = False

    for commission in commissions:
        try:
            before = (commission.drive_folder_id or "").strip()
            folder_id = ensure_commission_drive_folder(
                commission,
                drive_service=drive_service,
                commit=False,
            )
            if folder_id and not before:
                result["commissions_created"] += 1
                pending_updates = True
        except Exception as exc:
            result["errors"].append(f"Comision {commission.id}: {exc}")

    for project in projects:
        try:
            before = (project.drive_folder_id or "").strip()
            folder_id = ensure_project_drive_folder(
                project,
                drive_service=drive_service,
                commit=False,
            )
            if folder_id and not before:
                result["projects_created"] += 1
                pending_updates = True
        except Exception as exc:
            result["errors"].append(f"Proyecto {project.id}: {exc}")

    if pending_updates:
        db.session.commit()

    return result
