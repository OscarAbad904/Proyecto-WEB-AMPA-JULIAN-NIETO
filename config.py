"""Carga y utilidades de configuración del proyecto.

Permite desencriptar variables sensibles del entorno utilizando una clave
Fernet almacenada en `fernet.key` en la raíz del proyecto.
"""

import json
from dotenv import load_dotenv
import os
import sys
from cryptography.fernet import Fernet
from pathlib import Path
from logging.handlers import RotatingFileHandler
import logging
from urllib.parse import quote_plus

# Cargar siempre el `.env` del proyecto (y hacer override en local) para que
# cambios del gestor se reflejen aunque existan variables ya exportadas.
ROOT_PATH = Path(__file__).resolve().parent
load_dotenv(ROOT_PATH / ".env", override=True)

def _resolve_key_file() -> str:
    """Determina la ubicación de `fernet.key` en ejecución local o congelada."""
    base_dir = ROOT_PATH
    candidates: list[Path] = [base_dir / 'fernet.key']

    if getattr(sys, 'frozen', False):
        # PyInstaller mantiene los assets dentro de _MEIPASS y el ejecutable final.
        meipass = Path(getattr(sys, '_MEIPASS', base_dir))
        candidates.append(meipass / 'fernet.key')
        candidates.append(Path(sys.executable).resolve().parent / 'fernet.key')

    # Directorio desde el que se lanzó el proceso (útil al empaquetar manualmente la clave).
    candidates.append(Path.cwd() / 'fernet.key')

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    formatted_candidates = ', '.join(str(path) for path in candidates)
    raise RuntimeError(f'No se encontró el archivo de clave Fernet en: {formatted_candidates}')


# Ruta de la clave Fernet
KEY_FILE = _resolve_key_file()


def _load_key() -> bytes:
    if not os.path.exists(KEY_FILE):
        raise RuntimeError(f'No se encontró el archivo de clave Fernet: {KEY_FILE}')
    with open(KEY_FILE, 'rb') as f:
        return f.read()


_FERNET = Fernet(_load_key())


def decrypt_env_var(var_name: str) -> str | None:
    """Desencripta el valor de una variable de entorno usando la clave Fernet.

    - Lee la clave desde `fernet.key`.
    - Devuelve `None` si no existe la variable o si falla el descifrado.
    """
    encrypted_value = os.getenv(var_name)
    if not encrypted_value:
        return None
    try:
        decrypted = decrypt_value(encrypted_value)
        if decrypted:
            # Silenciar logs de éxito para evitar ruido en consola
            pass
        return decrypted
    except Exception as e:
        print(f"[!] Error desencriptando {var_name}: {type(e).__name__} - {e}")
        print(f"  Usando valor sin encriptar como fallback")
        return None


def encrypt_value(value: str | bytes | None) -> str:
    """Encripta una cadena antes de guardarla en la base de datos."""
    if value is None:
        return ""
    payload = value.encode() if isinstance(value, str) else value
    return _FERNET.encrypt(payload).decode()


def decrypt_value(value: str | bytes | None) -> str | None:
    """Desencripta una cadena proveniente de la base de datos o del entorno."""
    if not value:
        return None
    payload = value.encode() if isinstance(value, str) else value
    return _FERNET.decrypt(payload).decode()


def _looks_like_fernet_token(text: str | None) -> bool:
    """Detecta si una cadena parece un token Fernet por su prefijo."""
    if not text:
        return False
    return text.lstrip().startswith("gAAAA")


def _valid_json(text: str) -> bool:
    """Comprueba si una cadena contiene JSON válido."""
    try:
        json.loads(text)
        return True
    except ValueError:
        return False


def unwrap_fernet_layers(value: str | None, *, max_layers: int = 5) -> str | None:
    """Desencripta hasta que el texto ya no parece un token Fernet."""
    candidate = value
    for _ in range(max_layers):
        if not candidate or not _looks_like_fernet_token(candidate):
            break
        try:
            candidate = decrypt_value(candidate)
        except Exception:
            return None
    return candidate


def unwrap_fernet_json_layers(value: str | None, *, max_layers: int = 5) -> str | None:
    """Desencripta repetidas capas de Fernet asegurando que el resultado sea JSON."""
    candidate = unwrap_fernet_layers(value, max_layers=max_layers)
    if candidate and _valid_json(candidate):
        return candidate
    return None


# Variables de entorno principales
SECRET_KEY = decrypt_env_var('SECRET_KEY')
SHUTDOWN_SECRET_KEY = decrypt_env_var('SHUTDOWN_SECRET_KEY')

def get_int_env(key: str, default: int) -> int:
    """Obtiene una variable de entorno como entero, manejando valores vacíos o inválidos."""
    val = os.getenv(key)
    if not val:
        return default
    try:
        return int(val)
    except ValueError:
        return default

# Variables de entorno para Google Calendar
GOOGLE_CALENDAR_ID = os.getenv('GOOGLE_CALENDAR_ID', 'primary')
GOOGLE_CALENDAR_CACHE_TTL = get_int_env('GOOGLE_CALENDAR_CACHE_TTL', 600)  # 10 minutos


def ensure_google_drive_credentials_file(root_path: Path | str) -> str | None:
    """Desencripta GOOGLE_DRIVE_OAUTH_CREDENTIALS_JSON y crea el archivo si es necesario.
    
    Args:
        root_path: Ruta raíz de la aplicación (para guardar credentials_drive_oauth.json)
    
    Returns:
        Ruta al archivo de credenciales, o None si no está disponible.
    """
    root_path = Path(root_path)
    credentials_path = root_path / "credentials_drive_oauth.json"
    
    # Intentar obtener las credenciales encriptadas del entorno
    encrypted_creds = os.getenv("GOOGLE_DRIVE_OAUTH_CREDENTIALS_JSON")
    
    if not encrypted_creds:
        # Si no hay credenciales encriptadas, usar archivo existente si lo hay
        if credentials_path.exists():
            return str(credentials_path)
        return None
    
    # Desencriptar las credenciales
    try:
        creds_json = unwrap_fernet_json_layers(encrypted_creds)
        if not creds_json:
            return None
        
        # Crear el archivo si no existe o si el contenido cambió
        if not credentials_path.exists() or credentials_path.read_text(encoding="utf-8") != creds_json:
            credentials_path.parent.mkdir(parents=True, exist_ok=True)
            credentials_path.write_text(creds_json, encoding="utf-8")
        
        return str(credentials_path)
    except Exception as e:
        print(f"Error al desencriptar GOOGLE_DRIVE_OAUTH_CREDENTIALS_JSON: {e}")
        # Fallback: usar archivo existente si lo hay
        if credentials_path.exists():
            return str(credentials_path)
        return None


def ensure_google_drive_token_file(root_path: Path | str) -> str | None:
    """Desencripta GOOGLE_DRIVE_TOKEN_JSON y crea el archivo si es necesario.
    
    Args:
        root_path: Ruta raíz de la aplicación (para guardar token_drive.json)
    
    Returns:
        Ruta al archivo de token, o None si no está disponible.
    """
    root_path = Path(root_path)
    token_path = root_path / "token_drive.json"
    
    # Intentar obtener el token encriptado del entorno
    encrypted_token = os.getenv("GOOGLE_DRIVE_TOKEN_JSON")
    
    if not encrypted_token:
        # Si no hay token encriptado, usar archivo existente si lo hay
        if token_path.exists():
            return str(token_path)
        return None
    
    # Desencriptar el token
    try:
        token_json = unwrap_fernet_json_layers(encrypted_token)
        if not token_json:
            return None
        
        # Crear el archivo si no existe o si el contenido cambió
        if not token_path.exists() or token_path.read_text(encoding="utf-8") != token_json:
            token_path.parent.mkdir(parents=True, exist_ok=True)
            token_path.write_text(token_json, encoding="utf-8")
        
        return str(token_path)
    except Exception as e:
        print(f"Error al desencriptar GOOGLE_DRIVE_TOKEN_JSON: {e}")
        # Fallback: usar archivo existente si lo hay
        if token_path.exists():
            return str(token_path)
        return None


# --- Configuración Flask ---

def _get_env_with_optional_decrypt(var_name: str) -> str | None:
    """Return env var value, attempting Fernet decrypt when needed."""
    value = os.getenv(var_name)
    if not value:
        return None
    try:
        return decrypt_value(value)
    except Exception:
        return value


def _normalize_db_uri(uri: str | None) -> str | None:
    """Ensure postgres URLs use the SQLAlchemy psycopg2 prefix and require SSL."""
    if not uri:
        return None
    
    # Normalizar prefijo
    if uri.startswith("postgres://"):
        uri = "postgresql+psycopg2://" + uri[len("postgres://"):]
    elif uri.startswith("postgresql://"):
        uri = "postgresql+psycopg2://" + uri[len("postgresql://") :]
    
    # Asegurar sslmode=require para PostgreSQL en entornos como Render
    if "postgresql" in uri and "sslmode=" not in uri:
        separator = "&" if "?" in uri else "?"
        uri += f"{separator}sslmode=require"
        
    return uri

DATA_PATH = Path(os.getenv("AMPA_DATA_DIR", ROOT_PATH / "Data"))
# Usar 'or' para manejar cadenas vacías que os.getenv devuelve si la variable existe pero está vacía
DEFAULT_SQLALCHEMY_URI = (
    _normalize_db_uri(
        _get_env_with_optional_decrypt("SQLALCHEMY_DATABASE_URI")
        or _get_env_with_optional_decrypt("DATABASE_URL")
    )
    or "postgresql+psycopg2://user:password@localhost:5432/ampa_db"
)

PRIVILEGED_ROLES = {
    "admin",
    "administrador",
    "presidencia",
    "vicepresidencia",
    "presidente",
    "vicepresidente",
    "secretaria",
    "secretario",
    "vicesecretaria",
    "vicesecretario",
}


def _build_sqlalchemy_uri() -> str:
    """Obtiene la URI de base de datos priorizando PostgreSQL."""
    uri = _normalize_db_uri(
        _get_env_with_optional_decrypt("SQLALCHEMY_DATABASE_URI")
        or _get_env_with_optional_decrypt("DATABASE_URL")
    )

    # Permite configurar PostgreSQL mediante variables POSTGRES_/PG*.
    if not uri:
        pg_host = os.getenv("POSTGRES_HOST") or os.getenv("PGHOST")
        pg_port = os.getenv("POSTGRES_PORT") or os.getenv("PGPORT") or "5432"
        pg_user = os.getenv("POSTGRES_USER") or os.getenv("PGUSER")
        pg_password = _get_env_with_optional_decrypt("POSTGRES_PASSWORD")
        if pg_password is None:
            pg_password = _get_env_with_optional_decrypt("PGPASSWORD")
        pg_db = os.getenv("POSTGRES_DB") or os.getenv("PGDATABASE")
        if pg_host and pg_user and pg_db and pg_password is not None:
            uri = (
                "postgresql+psycopg2://"
                f"{quote_plus(pg_user)}:{quote_plus(pg_password)}@{pg_host}:{pg_port}/{quote_plus(pg_db)}"
            )

    if not uri:
        uri = DEFAULT_SQLALCHEMY_URI
        
    # Asegurar que nunca devolvemos una cadena vacía
    if not uri:
        uri = "postgresql+psycopg2://user:password@localhost:5432/ampa_db"

    return uri


_SQLALCHEMY_URI = _build_sqlalchemy_uri()
os.environ["SQLALCHEMY_DATABASE_URI"] = _SQLALCHEMY_URI


class BaseConfig:
    SECRET_KEY = decrypt_env_var("SECRET_KEY") or os.getenv("SECRET_KEY", "changeme")
    SECURITY_PASSWORD_SALT = decrypt_env_var("SECURITY_PASSWORD_SALT") or os.getenv("SECURITY_PASSWORD_SALT", "salt-me")
    SQLALCHEMY_DATABASE_URI = _SQLALCHEMY_URI
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # Opciones del pool de conexiones para evitar errores SSL tras inactividad
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,   # Verificar conexión antes de usarla
        "pool_recycle": 180,     # Reciclar conexiones cada 3 minutos (antes 5)
        "pool_size": 10,         # Tamaño base del pool
        "max_overflow": 5,       # Conexiones extra permitidas
        "pool_timeout": 30,      # Tiempo de espera para obtener conexión
        "connect_args": {
            "sslmode": "require",
        }
    }
    MAIL_SERVER = os.getenv("MAIL_SERVER", "smtp.gmail.com")
    MAIL_PORT = get_int_env("MAIL_PORT", 587)
    MAIL_USE_TLS = os.getenv("MAIL_USE_TLS", "true").lower() in ("true", "1", "yes")
    MAIL_USERNAME = os.getenv("MAIL_USERNAME", "")
    # Intentar desencriptar la contraseña; si falla o no está encriptada, usar el valor directo
    _mail_password_encrypted = decrypt_env_var("MAIL_PASSWORD")
    MAIL_PASSWORD = _mail_password_encrypted if _mail_password_encrypted is not None else os.getenv("MAIL_PASSWORD", "")
    MAIL_DEFAULT_SENDER = os.getenv("MAIL_DEFAULT_SENDER", "")
    MAIL_CONTACT_RECIPIENT = os.getenv("MAIL_CONTACT_RECIPIENT", "")
    MAIL_AMPA_RECIPIENT = os.getenv("MAIL_AMPA_RECIPIENT", "")
    EMAIL_VERIFICATION_SALT = os.getenv("EMAIL_VERIFICATION_SALT") or f"{SECURITY_PASSWORD_SALT}:verify-email"
    SET_PASSWORD_SALT = os.getenv("SET_PASSWORD_SALT") or f"{SECURITY_PASSWORD_SALT}:set-password"
    EMAIL_VERIFICATION_TOKEN_MAX_AGE = get_int_env("EMAIL_VERIFICATION_TOKEN_MAX_AGE", 60 * 60 * 24)
    SET_PASSWORD_TOKEN_MAX_AGE = get_int_env("SET_PASSWORD_TOKEN_MAX_AGE", 60 * 60 * 24)
    PRIVACY_POLICY_VERSION = os.getenv("PRIVACY_POLICY_VERSION", "1")
    LOG_FILE = str(ROOT_PATH / "logs" / "ampa.log")
    LOG_LEVEL = os.getenv("LOG_LEVEL") or "INFO"
    # Carpeta raíz en Google Drive para agrupar recursos (e.g. "WEB Ampa/Noticias").
    GOOGLE_DRIVE_ROOT_FOLDER_ID = os.getenv("GOOGLE_DRIVE_ROOT_FOLDER_ID", "")
    GOOGLE_DRIVE_ROOT_FOLDER_NAME = os.getenv("GOOGLE_DRIVE_ROOT_FOLDER_NAME", "WEB Ampa")
    GOOGLE_DRIVE_NEWS_FOLDER_ID = os.getenv("GOOGLE_DRIVE_NEWS_FOLDER_ID", "")
    GOOGLE_DRIVE_NEWS_FOLDER_NAME = os.getenv("GOOGLE_DRIVE_NEWS_FOLDER_NAME", "Noticias")
    GOOGLE_DRIVE_EVENTS_FOLDER_ID = os.getenv("GOOGLE_DRIVE_EVENTS_FOLDER_ID", "")
    GOOGLE_DRIVE_EVENTS_FOLDER_NAME = os.getenv("GOOGLE_DRIVE_EVENTS_FOLDER_NAME", "Eventos")
    GOOGLE_DRIVE_DOCS_FOLDER_ID = os.getenv("GOOGLE_DRIVE_DOCS_FOLDER_ID", "")
    GOOGLE_DRIVE_DOCS_FOLDER_NAME = os.getenv("GOOGLE_DRIVE_DOCS_FOLDER_NAME", "Documentos")
    GOOGLE_DRIVE_DB_BACKUP_FOLDER_ID = os.getenv("GOOGLE_DRIVE_DB_BACKUP_FOLDER_ID", "")
    GOOGLE_DRIVE_SHARED_DRIVE_ID = os.getenv("GOOGLE_DRIVE_SHARED_DRIVE_ID", "")
    GOOGLE_DRIVE_OAUTH_CREDENTIALS_FILE = os.getenv(
        "GOOGLE_DRIVE_OAUTH_CREDENTIALS_FILE",
        str(ROOT_PATH / "credentials_drive_oauth.json"),
    )
    GOOGLE_DRIVE_OAUTH_CREDENTIALS_JSON = decrypt_env_var("GOOGLE_DRIVE_OAUTH_CREDENTIALS_JSON") or os.getenv(
        "GOOGLE_DRIVE_OAUTH_CREDENTIALS_JSON",
        "",
    )
    GOOGLE_DRIVE_TOKEN_JSON = decrypt_env_var("GOOGLE_DRIVE_TOKEN_JSON") or os.getenv(
        "GOOGLE_DRIVE_TOKEN_JSON",
        "",
    )
    NEWS_IMAGE_FORMAT = os.getenv("NEWS_IMAGE_FORMAT", "JPEG")
    NEWS_IMAGE_QUALITY = get_int_env("NEWS_IMAGE_QUALITY", 80)

    # --- Backups BD -> Google Drive ---
    DB_BACKUP_ENABLED = (os.getenv("DB_BACKUP_ENABLED", "true").lower() in ("1", "true", "yes", "on"))
    DB_BACKUP_TIME = os.getenv("DB_BACKUP_TIME", "00:00")  # HH:MM
    DB_BACKUP_FREQUENCY = get_int_env("DB_BACKUP_FREQUENCY", 1)  # cada cuántos días
    DB_BACKUP_FILENAME_PREFIX = os.getenv("DB_BACKUP_FILENAME_PREFIX", "BD_WEB_Ampa_Julian_Nieto")
    GOOGLE_DRIVE_DB_BACKUP_FOLDER_NAME = os.getenv("GOOGLE_DRIVE_DB_BACKUP_FOLDER_NAME", "Backup DB_WEB")
    
    # Google Calendar configuration
    GOOGLE_CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID", "primary")
    GOOGLE_CALENDAR_COMMISSIONS_ID = os.getenv("GOOGLE_CALENDAR_COMMISSIONS_ID", "")
    GOOGLE_CALENDAR_TIMEZONE = os.getenv("GOOGLE_CALENDAR_TIMEZONE", "")
    GOOGLE_CALENDAR_CACHE_TTL = get_int_env("GOOGLE_CALENDAR_CACHE_TTL", 600)  # 10 minutos

    @staticmethod
    def init_app(app):
        # Recalcular la URI en tiempo de ejecución para que cambios en `.env` tengan efecto
        # (por ejemplo, desde env_manager_server.py sin reiniciar proceso).
        try:
            runtime_uri = _build_sqlalchemy_uri()
            if runtime_uri:
                app.config["SQLALCHEMY_DATABASE_URI"] = runtime_uri
                os.environ["SQLALCHEMY_DATABASE_URI"] = runtime_uri
        except Exception:
            pass
        # Refrescar configuracion de Google Drive desde entorno (.env re-cargado por el gestor).
        drive_keys = [
            "GOOGLE_DRIVE_ROOT_FOLDER_ID",
            "GOOGLE_DRIVE_ROOT_FOLDER_NAME",
            "GOOGLE_DRIVE_NEWS_FOLDER_ID",
            "GOOGLE_DRIVE_NEWS_FOLDER_NAME",
            "GOOGLE_DRIVE_EVENTS_FOLDER_ID",
            "GOOGLE_DRIVE_EVENTS_FOLDER_NAME",
            "GOOGLE_DRIVE_DOCS_FOLDER_ID",
            "GOOGLE_DRIVE_DOCS_FOLDER_NAME",
            "GOOGLE_DRIVE_DB_BACKUP_FOLDER_ID",
            "GOOGLE_DRIVE_DB_BACKUP_FOLDER_NAME",
            "GOOGLE_DRIVE_SHARED_DRIVE_ID",
        ]
        for key in drive_keys:
            if key in os.environ:
                app.config[key] = os.environ.get(key, "")

        # Asegurar que los archivos de Google Drive existen y están desencriptados
        ensure_google_drive_credentials_file(ROOT_PATH)
        ensure_google_drive_token_file(ROOT_PATH)
        
        log_path = Path(BaseConfig.LOG_FILE)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            log_path,
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
        )
        
        # Configurar nivel de log de forma segura
        log_level = BaseConfig.LOG_LEVEL
        if not log_level or not isinstance(log_level, str) or not log_level.strip():
            log_level = "INFO"
        else:
            log_level = log_level.upper()
            
        # Validar que el nivel existe
        if log_level not in logging._nameToLevel:
            log_level = "INFO"
            
        handler.setLevel(log_level)
        app.logger.addHandler(handler)


class DevelopmentConfig(BaseConfig):
    DEBUG = True
    CACHE_TYPE = "SimpleCache"
    SEND_FILE_MAX_AGE_DEFAULT = 0


class ProductionConfig(BaseConfig):
    DEBUG = False
    CACHE_TYPE = "RedisCache"


class TestingConfig(BaseConfig):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = _SQLALCHEMY_URI
    WTF_CSRF_ENABLED = False


config_by_name = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}
