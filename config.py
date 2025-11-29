"""Carga y utilidades de configuración del proyecto.

Permite desencriptar variables sensibles del entorno utilizando una clave
Fernet almacenada en `fernet.key` en la raíz del proyecto.
"""

from dotenv import load_dotenv
import os
import sys
from cryptography.fernet import Fernet
from pathlib import Path

load_dotenv()

def _resolve_key_file() -> str:
    """Determina la ubicación de `fernet.key` en ejecución local o congelada."""
    base_dir = Path(__file__).resolve().parent
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
        return decrypt_value(encrypted_value)
    except Exception as e:
        print(f"Error desencriptando {var_name}: {e}")
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


# Variables de entorno principales
SECRET_KEY = decrypt_env_var('SECRET_KEY')
SHUTDOWN_SECRET_KEY = decrypt_env_var('SHUTDOWN_SECRET_KEY')


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
        creds_json = decrypt_value(encrypted_creds)
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
        token_json = decrypt_value(encrypted_token)
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


