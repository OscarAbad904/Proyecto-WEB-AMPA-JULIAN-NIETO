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


def decrypt_env_var(var_name: str) -> str | None:
    """Desencripta el valor de una variable de entorno usando la clave Fernet.

    - Lee la clave desde `fernet.key`.
    - Devuelve `None` si no existe la variable o si falla el descifrado.
    """
    encrypted_value = os.getenv(var_name)
    if not encrypted_value:
        return None
    if not os.path.exists(KEY_FILE):
        raise RuntimeError(f'No se encontró el archivo de clave Fernet: {KEY_FILE}')
    with open(KEY_FILE, 'rb') as f:
        key = f.read()
    fernet = Fernet(key)
    try:
        return fernet.decrypt(encrypted_value.encode()).decode()
    except Exception as e:
        print(f"Error desencriptando {var_name}: {e}")
        return None


# Variables de entorno principales
SECRET_KEY = decrypt_env_var('SECRET_KEY')
SHUTDOWN_SECRET_KEY = decrypt_env_var('SHUTDOWN_SECRET_KEY')
DB_USER = os.getenv('DB_USER')
DB_PASSWORD = decrypt_env_var('DB_PASSWORD')

