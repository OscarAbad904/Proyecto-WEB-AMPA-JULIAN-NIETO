import hashlib
import unicodedata
import re
import secrets
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs
from flask import current_app
from itsdangerous import URLSafeTimedSerializer
from typing import Any

def normalize_lookup(value: str | None) -> str:
    if not value:
        return ""
    return value.strip().lower()


def make_lookup_hash(value: str | None) -> str:
    normalized = normalize_lookup(value)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def slugify(value: str) -> str:
    """Crea un slug URL-safe a partir de un título."""
    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_text).strip("-").lower()
    return slug or "noticia"


def _normalize_drive_url(url: str | None) -> str | None:
    """Convierte enlaces de Drive en URLs de visualización directa."""
    if not url or "drive.google.com" not in url:
        return url

    patterns = [
        r"drive\.google\.com/file/d/([^/]+)/",
        r"drive\.google\.com/file/d/([^/]+)/view",
        r"drive\.google\.com/open\?id=([^&]+)",
        r"drive\.google\.com/uc\?id=([^&]+)",
        r"drive\.googleusercontent\.com/d/([^/]+)",
        r"drive\.google\.com/uc\?export=view&id=([^&]+)",
    ]
    for pat in patterns:
        match = re.search(pat, url)
        if match:
            return f"https://drive.google.com/uc?export=view&id={match.group(1)}"
    try:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        if qs.get("id"):
            return f"https://drive.google.com/uc?export=view&id={qs['id'][0]}"
    except Exception:
        return url
    return url


def _parse_datetime_local(value: str | None) -> datetime | None:
    """Parsea valores de <input type="datetime-local"> en UTC naive."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def generate_confirmation_token(email: str) -> str:
    serializer = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
    return serializer.dumps(email, salt=current_app.config["SECURITY_PASSWORD_SALT"])


def confirm_token(token: str, expiration: int = 3600) -> str | bool:
    serializer = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
    try:
        email = serializer.loads(
            token,
            salt=current_app.config["SECURITY_PASSWORD_SALT"],
            max_age=expiration,
        )
    except Exception:  # noqa: BLE001
        return False
    return email


def generate_email_verification_token(user_id: int, email_lookup: str) -> str:
    serializer = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
    salt = current_app.config.get("EMAIL_VERIFICATION_SALT") or current_app.config["SECURITY_PASSWORD_SALT"]
    payload = {"user_id": int(user_id), "email_lookup": str(email_lookup)}
    return serializer.dumps(payload, salt=salt)


def confirm_email_verification_token(token: str, expiration: int) -> dict[str, Any] | None:
    serializer = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
    salt = current_app.config.get("EMAIL_VERIFICATION_SALT") or current_app.config["SECURITY_PASSWORD_SALT"]
    try:
        data = serializer.loads(token, salt=salt, max_age=expiration)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(data, dict):
        return None
    return data


def generate_set_password_token(user_id: int, password_hash: str) -> str:
    serializer = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
    salt = current_app.config.get("SET_PASSWORD_SALT") or current_app.config["SECURITY_PASSWORD_SALT"]
    payload = {"user_id": int(user_id), "ph": str(password_hash or "")}
    return serializer.dumps(payload, salt=salt)


def confirm_set_password_token(token: str, expiration: int) -> dict[str, Any] | None:
    serializer = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
    salt = current_app.config.get("SET_PASSWORD_SALT") or current_app.config["SECURITY_PASSWORD_SALT"]
    try:
        data = serializer.loads(token, salt=salt, max_age=expiration)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(data, dict):
        return None
    return data


def _generate_password(length: int = 10) -> str:
    return secrets.token_urlsafe(length)[:length]


def _generate_member_number(year: int) -> str:
    return f"{year}-SOC-{secrets.randbelow(9999):04}"


def _send_sms_code(phone: str, code: str) -> None:
    print(f"[SMS] Enviar código {code} a {phone}")
