import os
import secrets
from pathlib import Path

from flask import current_app
from werkzeug.utils import secure_filename


class UploadService:
    ALLOWED_EXTENSIONS = {
        "image": {"jpg", "jpeg", "png", "gif", "webp"},
        "doc": {"pdf", "docx", "doc", "xlsx"},
        "video": {"mp4", "mov"},
    }
    MAX_BYTES = 8 * 1024 * 1024

    @classmethod
    def allowed(cls, filename: str, kind: str) -> bool:
        if "." not in filename:
            return False
        ext = filename.rsplit(".", 1)[1].lower()
        return ext in cls.ALLOWED_EXTENSIONS.get(kind, set())

    @classmethod
    def save(cls, file, kind="image"):
        filename = secure_filename(file.filename)
        if not cls.allowed(filename, kind):
            raise ValueError("Tipo de archivo no permitido")
        data = file.stream.read()
        file.stream.seek(0)
        if len(data) > cls.MAX_BYTES:
            raise ValueError("Archivo demasiado grande")
        asset_folder = os.path.join(current_app.static_folder, "uploads")
        os.makedirs(asset_folder, exist_ok=True)
        unique = secrets.token_hex(8)
        normalized = f"{Path(filename).stem}-{unique}.{filename.rsplit('.', 1)[1]}"
        full_path = os.path.join(asset_folder, normalized)
        file.save(full_path)
        relative = os.path.relpath(full_path, current_app.static_folder)
        return relative
