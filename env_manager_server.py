"""
Servidor Flask para el Gestor de Configuración AMPA.

Proporciona una interfaz web moderna para gestionar las variables de entorno
del proyecto de forma segura y centralizada.
"""

import os
import json
import webbrowser
import threading
import hashlib
from pathlib import Path
from functools import wraps

# Evitar que el gestor de entorno dispare tareas en segundo plano del servidor principal.
os.environ.setdefault("AMPA_DISABLE_BACKGROUND_JOBS", "1")

from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from dotenv import dotenv_values, load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash

# Importaciones del proyecto AMPA
from app import create_app as create_ampa_app
from app.extensions import db
from app.models import User, Role, user_is_privileged
from app.utils import normalize_lookup, make_lookup_hash
from config import (
    encrypt_value,
    decrypt_value,
    PRIVILEGED_ROLES,
    ensure_google_drive_credentials_file,
    ensure_google_drive_token_file,
    unwrap_fernet_layers,
)

# Configuración
ENV_PATH = ".env"
CONFIG_FILE = "gui_config.json"
AUTH_FILE = "env_manager_auth.json"
SERVER_PORT = 5050

# Definición de todas las variables del proyecto organizadas por grupos
ENV_VARIABLES = {
    "seguridad": {
        "title": "🔐 Seguridad y Autenticación",
        "description": "Variables críticas para la seguridad de la aplicación",
        "vars": {
            "SECRET_KEY": {
                "label": "Clave Secreta",
                "sensitive": True,
                "required": True,
                "default": "",
                "help": {
                    "description": "Clave secreta utilizada por Flask para firmar cookies de sesión y tokens CSRF. Debe ser una cadena larga, aleatoria y única.",
                    "how_to_get": "Genera una clave segura ejecutando en Python:\n\nimport secrets\nprint(secrets.token_hex(32))\n\nO usa: openssl rand -hex 32",
                    "example": "a1b2c3d4e5f6789...",
                    "warning": "Nunca compartas esta clave. Si se compromete, regenera inmediatamente."
                }
            },
            "SECURITY_PASSWORD_SALT": {
                "label": "Salt de Contraseñas",
                "sensitive": True,
                "required": True,
                "default": "",
                "help": {
                    "description": "Salt adicional usado para generar tokens de confirmación de email y recuperación de contraseña.",
                    "how_to_get": "Genera un salt ejecutando:\n\nimport secrets\nprint(secrets.token_hex(16))",
                    "example": "my-security-salt-123",
                    "warning": "Cambiar este valor invalidará todos los tokens de recuperación pendientes."
                }
            },
        }
    },
    "flask": {
        "title": "⚙️ Configuración Flask",
        "description": "Variables de configuración del framework Flask",
        "vars": {
            "FLASK_ENV": {
                "label": "Entorno Flask",
                "sensitive": False,
                "required": False,
                "default": "development",
                "options": ["development", "production", "testing"],
                "help": {
                    "description": "Define el entorno de ejecución de Flask. Afecta al modo debug, logs y optimizaciones.",
                    "how_to_get": "Selecciona 'development' para desarrollo local, 'production' para Render/producción.",
                    "example": "production",
                    "warning": "Nunca uses 'development' en producción."
                }
            },
            "PORT": {
                "label": "Puerto del Servidor",
                "sensitive": False,
                "required": False,
                "default": "3000",
                "help": {
                    "description": "Puerto en el que se ejecuta el servidor Flask.",
                    "how_to_get": "En Render se asigna automáticamente. Para local usa 3000, 5000, u 8080.",
                    "example": "3000",
                    "warning": "Render ignora este valor y usa su puerto interno."
                }
            },
            "LOG_LEVEL": {
                "label": "Nivel de Logs",
                "sensitive": False,
                "required": False,
                "default": "INFO",
                "options": ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
                "help": {
                    "description": "Nivel de detalle de los logs de la aplicación.",
                    "how_to_get": "Usa DEBUG para desarrollo, INFO o WARNING para producción.",
                    "example": "INFO",
                    "warning": "DEBUG puede exponer información sensible en logs."
                }
            }
        }
    },
    "database": {
        "title": "🗄️ Base de Datos",
        "description": "Configuración de conexión a la base de datos",
        "vars": {
            "SQLALCHEMY_DATABASE_URI": {
                "label": "URI Completa de BD",
                "sensitive": True,
                "required": False,
                "default": "",
                "help": {
                    "description": "URI completa de conexión a PostgreSQL.",
                    "how_to_get": "En Render, copia la 'Internal Database URL' de tu base de datos PostgreSQL.",
                    "example": "postgresql+psycopg2://user:pass@host:5432/dbname",
                    "warning": "Contiene credenciales. No lo compartas."
                }
            },
        }
    },
    "mail": {
        "title": "📧 Configuración de Correo",
        "description": "Configuración SMTP para envío de emails",
        "vars": {
            "MAIL_SERVER": {
                "label": "Servidor SMTP",
                "sensitive": False,
                "required": True,
                "default": "smtp.gmail.com",
                "help": {
                    "description": "Servidor SMTP para envío de correos.",
                    "how_to_get": "Para Gmail: smtp.gmail.com\nPara Outlook: smtp.office365.com\nPara Yahoo: smtp.mail.yahoo.com",
                    "example": "smtp.gmail.com",
                    "warning": ""
                }
            },
            "MAIL_PORT": {
                "label": "Puerto SMTP",
                "sensitive": False,
                "required": True,
                "default": "587",
                "help": {
                    "description": "Puerto del servidor SMTP. Usa 587 para TLS o 465 para SSL.",
                    "how_to_get": "TLS (recomendado): 587\nSSL: 465\nSin cifrado: 25",
                    "example": "587",
                    "warning": "Usa siempre conexión cifrada (TLS/SSL)."
                }
            },
            "MAIL_USE_TLS": {
                "label": "Usar TLS",
                "sensitive": False,
                "required": False,
                "default": "true",
                "options": ["true", "false"],
                "help": {
                    "description": "Activa el cifrado TLS para la conexión SMTP.",
                    "how_to_get": "Usa 'true' con puerto 587, 'false' con puerto 465 (SSL).",
                    "example": "true",
                    "warning": ""
                }
            },
            "MAIL_USERNAME": {
                "label": "Usuario de Correo",
                "sensitive": False,
                "required": True,
                "default": "",
                "help": {
                    "description": "Dirección de email para autenticación SMTP.",
                    "how_to_get": "Tu dirección de correo completa, ej: ampaceipjnt@gmail.com",
                    "example": "ampaceipjnt@gmail.com",
                    "warning": ""
                }
            },
            "MAIL_PASSWORD": {
                "label": "Contraseña de Correo",
                "sensitive": True,
                "required": True,
                "default": "",
                "help": {
                    "description": "Contraseña o App Password para autenticación SMTP.",
                    "how_to_get": "Para Gmail:\n1. Ve a myaccount.google.com\n2. Seguridad → Verificación en 2 pasos (activar)\n3. Contraseñas de aplicaciones\n4. Genera una para 'Correo' en 'Otro (AMPA)'",
                    "example": "xxxx xxxx xxxx xxxx",
                    "warning": "Usa una 'Contraseña de aplicación', no tu contraseña normal de Gmail."
                }
            },
            "MAIL_DEFAULT_SENDER": {
                "label": "Remitente por Defecto",
                "sensitive": False,
                "required": True,
                "default": "",
                "help": {
                    "description": "Dirección que aparece como remitente en los emails enviados.",
                    "how_to_get": "Normalmente igual que MAIL_USERNAME, o con formato: 'AMPA JNT <ampaceipjnt@gmail.com>'",
                    "example": "AMPA JNT <ampaceipjnt@gmail.com>",
                    "warning": ""
                }
            },
            "MAIL_CONTACT_RECIPIENT": {
                "label": "Destinatario de Contacto",
                "sensitive": False,
                "required": False,
                "default": "",
                "help": {
                    "description": "Email que recibe los mensajes del formulario de contacto.",
                    "how_to_get": "El email del AMPA donde quieres recibir consultas.",
                    "example": "ampaceipjnt@gmail.com",
                    "warning": ""
                }
            }
        }
    },
    "google_drive": {
        "title": "📁 Google Drive",
        "description": "Configuración de integración con Google Drive para almacenamiento de imágenes",
        "vars": {
            "GOOGLE_DRIVE_OAUTH_CREDENTIALS_FILE": {
                "label": "Archivo de Credenciales",
                "sensitive": False,
                "required": False,
                "default": "credentials_drive_oauth.json",
                "help": {
                    "description": "Ruta al archivo JSON de credenciales OAuth de Google.",
                    "how_to_get": "Por defecto es 'credentials_drive_oauth.json' en la raíz del proyecto.",
                    "example": "credentials_drive_oauth.json",
                    "warning": "No cambies a menos que muevas el archivo."
                }
            },
            "GOOGLE_DRIVE_OAUTH_CREDENTIALS_JSON": {
                "label": "Credenciales OAuth (JSON)",
                "sensitive": True,
                "required": True,
                "multiline": True,
                "default": "",
                "help": {
                    "description": "Contenido JSON de las credenciales OAuth de Google Cloud Console, encriptado con Fernet.",
                    "how_to_get": "1. Ve a console.cloud.google.com\n2. APIs y Servicios → Credenciales\n3. Crear credenciales → ID de cliente OAuth\n4. Tipo: Aplicación de escritorio\n5. Descarga el JSON\n6. Pega el contenido aquí (se encriptará automáticamente)",
                    "example": '{"installed":{"client_id":"...","client_secret":"..."}}',
                    "warning": "Este valor se encripta automáticamente al guardar."
                }
            },
            "GOOGLE_DRIVE_TOKEN_JSON": {
                "label": "Token OAuth (JSON)",
                "sensitive": True,
                "required": True,
                "multiline": True,
                "default": "",
                "help": {
                    "description": "Token de acceso OAuth generado tras la autorización, encriptado con Fernet.",
                    "how_to_get": "1. Ejecuta: flask regenerate-google-token\n2. Autoriza en el navegador\n3. El token se guarda en token_drive.json\n4. Copia su contenido aquí (se encriptará)",
                    "example": '{"token":"...","refresh_token":"..."}',
                    "warning": "Regenerar el token requiere reautorización de Google."
                }
            },
            "GOOGLE_DRIVE_ROOT_FOLDER_ID": {
                "label": "ID Carpeta Raíz (Drive)",
                "sensitive": False,
                "required": False,
                "default": "",
                "help": {
                    "description": "ID de la carpeta raíz (p.ej. 'WEB Ampa') donde se crean las subcarpetas de Noticias/Eventos/Documentos.",
                    "how_to_get": "Renombra o crea la carpeta en Drive y copia el ID de la URL. También puedes ejecutar: flask setup-drive-folders",
                    "example": "1a2b3c4d...",
                    "warning": "Si lo dejas vacío se buscará/creará por nombre."
                }
            },
            "GOOGLE_DRIVE_ROOT_FOLDER_NAME": {
                "label": "Nombre Carpeta Raíz",
                "sensitive": False,
                "required": False,
                "default": "WEB Ampa",
                "help": {
                    "description": "Nombre de la carpeta raíz en Google Drive donde se crearán/colgarán las subcarpetas (Noticias, Eventos, Documentos, backups).",
                    "how_to_get": "Crea o renombra la carpeta en Google Drive (por ejemplo: '3.1_WEB Ampa') y escribe aquí exactamente el mismo nombre. Luego ejecuta: flask setup-drive-folders.",
                    "example": "3.1_WEB Ampa",
                    "warning": "Si cambias este nombre y no existe una carpeta con ese nombre, se creará una nueva carpeta raíz."
                }
            },
            "GOOGLE_DRIVE_COMMISSIONS_FOLDER_ID": {
                "label": "ID Carpeta Comisiones",
                "sensitive": False,
                "required": False,
                "default": "",
                "help": {
                    "description": "ID de la carpeta de Drive donde se crean las subcarpetas de cada comision.",
                    "how_to_get": "Ejecuta: flask setup-drive-folders",
                    "example": "1a2b3c4d...",
                    "warning": ""
                }
            },
            "GOOGLE_DRIVE_COMMISSIONS_FOLDER_NAME": {
                "label": "Nombre Carpeta Comisiones",
                "sensitive": False,
                "required": False,
                "default": "Comisiones",
                "help": {
                    "description": "Nombre de la carpeta base para comisiones.",
                    "how_to_get": "Por defecto es 'Comisiones'.",
                    "example": "Comisiones",
                    "warning": ""
                }
            },
            "GOOGLE_DRIVE_NEWS_FOLDER_ID": {
                "label": "ID Carpeta Noticias",
                "sensitive": False,
                "required": False,
                "default": "",
                "help": {
                    "description": "ID de la carpeta de Drive donde se guardan las imágenes de noticias (normalmente 'WEB Ampa/Noticias').",
                    "how_to_get": "Ejecuta: flask setup-drive-folders\nO crea la carpeta manualmente y copia el ID de la URL.",
                    "example": "1a2b3c4d...",
                    "warning": ""
                }
            },
            "GOOGLE_DRIVE_NEWS_FOLDER_NAME": {
                "label": "Nombre Carpeta Noticias",
                "sensitive": False,
                "required": False,
                "default": "Noticias",
                "help": {
                    "description": "Nombre de la carpeta para imágenes de noticias (se crea si no existe).",
                    "how_to_get": "Por defecto es 'Noticias'. Cámbialo si prefieres otro nombre.",
                    "example": "Noticias",
                    "warning": ""
                }
            },
            "GOOGLE_DRIVE_EVENTS_FOLDER_ID": {
                "label": "ID Carpeta Eventos",
                "sensitive": False,
                "required": False,
                "default": "",
                "help": {
                    "description": "ID de la carpeta de Drive donde se guardan las imágenes de eventos.",
                    "how_to_get": "Ejecuta: flask setup-drive-folders",
                    "example": "1a2b3c4d...",
                    "warning": ""
                }
            },
            "GOOGLE_DRIVE_EVENTS_FOLDER_NAME": {
                "label": "Nombre Carpeta Eventos",
                "sensitive": False,
                "required": False,
                "default": "Eventos",
                "help": {
                    "description": "Nombre de la carpeta para imágenes de eventos.",
                    "how_to_get": "Por defecto es 'Eventos'.",
                    "example": "Eventos",
                    "warning": ""
                }
            },
            "GOOGLE_DRIVE_DOCS_FOLDER_ID": {
                "label": "ID Carpeta Documentos",
                "sensitive": False,
                "required": False,
                "default": "",
                "help": {
                    "description": "ID de la carpeta de Drive para documentos públicos del AMPA.",
                    "how_to_get": "Ejecuta: flask setup-drive-folders",
                    "example": "1a2b3c4d...",
                    "warning": ""
                }
            },
            "GOOGLE_DRIVE_DOCS_FOLDER_NAME": {
                "label": "Nombre Carpeta Documentos",
                "sensitive": False,
                "required": False,
                "default": "Documentos",
                "help": {
                    "description": "Nombre de la carpeta para documentos.",
                    "how_to_get": "Por defecto es 'Documentos'.",
                    "example": "Documentos",
                    "warning": ""
                }
            }
        }
    },
    "db_backup": {
        "title": "💾 Backup Base de Datos",
        "description": "Copia de seguridad automatica de la BD y subida a Google Drive",
        "vars": {
            "DB_BACKUP_TIME": {
                "label": "Hora (HH:MM)",
                "sensitive": False,
                "required": False,
                "default": "00:00",
                "help": {
                    "description": "Hora del backup para daily/weekly (formato 24h).",
                    "how_to_get": "Por ejemplo: 00:00.",
                    "example": "00:00",
                    "warning": ""
                }
            },
            "DB_BACKUP_FREQUENCY": {
                "label": "Frecuencia (dias)",
                "sensitive": False,
                "required": False,
                "default": "1",
                "help": {
                    "description": "Ejecuta un backup cada N dias a la hora indicada.",
                    "how_to_get": "Pon 1 para diario, 2 para cada dos dias, etc.",
                    "example": "1",
                    "warning": ""
                }
            },
            "GOOGLE_DRIVE_DB_BACKUP_FOLDER_NAME": {
                "label": "Carpeta en Drive",
                "sensitive": False,
                "required": False,
                "default": "Backup DB_WEB",
                "help": {
                    "description": "Nombre de la carpeta dentro de 'WEB Ampa' donde se guardan los backups.",
                    "how_to_get": "Por defecto: Backup DB_WEB.",
                    "example": "Backup DB_WEB",
                    "warning": ""
                }
            },
            "GOOGLE_DRIVE_DB_BACKUP_FOLDER_ID": {
                "label": "ID Carpeta Backup (Drive)",
                "sensitive": False,
                "required": False,
                "default": "",
                "help": {
                    "description": "ID de la carpeta de Drive donde se guardan los backups de la base de datos.",
                    "how_to_get": "Pulsa el botón 'Configurar Drive' para detectarla/crearla y guardar el ID automáticamente en el .env.",
                    "example": "1a2b3c4d...",
                    "warning": "Recomendado para evitar carpetas duplicadas con el mismo nombre."
                }
            },
            "DB_BACKUP_FILENAME_PREFIX": {
                "label": "Nombre de la copia (prefijo)",
                "sensitive": False,
                "required": False,
                "default": "BD_WEB_Ampa_Julian_Nieto",
                "help": {
                    "description": "Prefijo del archivo de backup. El nombre final es: PREFIJO_ddmmaaaa.sql.gz",
                    "how_to_get": "Por defecto: BD_WEB_Ampa_Julian_Nieto.",
                    "example": "BD_WEB_Ampa_Julian_Nieto",
                    "warning": ""
                }
            },
        }
    },
    "google_calendar": {
        "title": "📅 Google Calendar",
        "description": "Configuración de integración con Google Calendar para eventos",
        "vars": {
            "GOOGLE_CALENDAR_ID": {
                "label": "ID del Calendario",
                "sensitive": False,
                "required": True,
                "default": "primary",
                "help": {
                    "description": "ID del calendario de Google del AMPA. Puede ser 'primary' o el email del calendario.",
                    "how_to_get": "1. Ve a calendar.google.com\n2. Configuración del calendario\n3. Integrar el calendario\n4. Copia el 'ID del calendario'",
                    "example": "ampaceipjnt@gmail.com",
                    "warning": "Usa 'primary' para el calendario principal de la cuenta."
                }
            },
            "GOOGLE_CALENDAR_CACHE_TTL": {
                "label": "Tiempo de Caché (segundos)",
                "sensitive": False,
                "required": False,
                "default": "600",
                "help": {
                    "description": "Tiempo en segundos que se cachean los eventos del calendario para evitar llamadas excesivas a la API.",
                    "how_to_get": "Valor recomendado: 600 (10 minutos). Reduce para actualizaciones más frecuentes.",
                    "example": "600",
                    "warning": "Valores muy bajos pueden agotar la cuota de la API de Google."
                }
            }
        }
    },
    "images": {
        "title": "🖼️ Procesamiento de Imágenes",
        "description": "Configuración para el procesamiento de imágenes de noticias",
        "vars": {
            "NEWS_IMAGE_FORMAT": {
                "label": "Formato de Imagen",
                "sensitive": False,
                "required": False,
                "default": "JPEG",
                "options": ["JPEG", "PNG", "WEBP"],
                "help": {
                    "description": "Formato de salida para las imágenes procesadas de noticias.",
                    "how_to_get": "JPEG: Mejor compatibilidad, tamaño pequeño\nWEBP: Mejor calidad/tamaño pero menos compatible\nPNG: Sin pérdida pero más pesado",
                    "example": "JPEG",
                    "warning": ""
                }
            },
            "NEWS_IMAGE_QUALITY": {
                "label": "Calidad de Imagen",
                "sensitive": False,
                "required": False,
                "default": "80",
                "help": {
                    "description": "Calidad de compresión de imágenes (1-100). Mayor = mejor calidad pero más peso.",
                    "how_to_get": "Recomendado: 80 para buen equilibrio calidad/tamaño.",
                    "example": "80",
                    "warning": "Valores > 90 aumentan mucho el tamaño sin mejora visual notable."
                }
            }
        }
    },

}

# Variables sensibles que requieren encriptación
DECRYPT_ERROR_PLACEHOLDER = "[ERROR: No se pudo desencriptar]"

SENSITIVE_KEYS = {
    "SECRET_KEY",
    "SECURITY_PASSWORD_SALT",
    "MAIL_PASSWORD",
    "SQLALCHEMY_DATABASE_URI",
    "GOOGLE_DRIVE_OAUTH_CREDENTIALS_JSON",
    "GOOGLE_DRIVE_TOKEN_JSON",
}

# Crear aplicación Flask para el gestor
manager_app = Flask(
    __name__,
    template_folder="templates/env_manager",
    static_folder="assets",
    static_url_path="/assets"
)
manager_app.secret_key = os.urandom(24)


def load_env():
    """Carga las variables del archivo .env"""
    if os.path.exists(ENV_PATH):
        return dotenv_values(ENV_PATH)
    return {}


def save_env(env_dict):
    """Guarda las variables en el archivo .env"""
    lines = []
    for key, value in env_dict.items():
        if value is None:
            continue
        # Escapar comillas si es necesario
        if '"' in str(value) or "'" in str(value) or '\n' in str(value):
            value = value.replace('"', '\\"')
            lines.append(f'{key}="{value}"')
        else:
            lines.append(f"{key}={value}")
    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def load_last_user():
    """Carga el último usuario que inició sesión"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                data = json.load(f)
                return data.get("last_email", "")
        except:
            return ""
    return ""


def save_last_user(email):
    """Guarda el último usuario"""
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump({"last_email": email}, f)
    except:
        pass


def login_required(f):
    """Decorador para rutas que requieren autenticación"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("authenticated"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function


def _load_auth():
    path = Path(AUTH_FILE)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _save_auth(email: str, password_hash: str) -> None:
    Path(AUTH_FILE).write_text(
        json.dumps({"email": email, "password_hash": password_hash}, ensure_ascii=False),
        encoding="utf-8",
    )


def _verify_password(stored_hash: str, password: str) -> bool:
    if not stored_hash:
        return False
    if ":" in stored_hash:
        return check_password_hash(stored_hash, password)
    try:
        if len(stored_hash) == 64 and all(c in "0123456789abcdef" for c in stored_hash.lower()):
            candidate = hashlib.sha256(password.encode("utf-8")).hexdigest()
            return candidate == stored_hash.lower()
    except Exception:
        return False
    return False


# Rutas de la aplicación

@manager_app.route("/")
def index():
    """Redirecciona al login o al panel según el estado de sesión"""
    if session.get("authenticated"):
        return redirect(url_for("panel"))
    return redirect(url_for("login"))


@manager_app.route("/login", methods=["GET", "POST"])
def login():
    """Página de login"""
    if request.method == "POST":
        data = request.get_json() if request.is_json else request.form
        email = data.get("email", "").strip()
        password = data.get("password", "")
        
        if not email or not password:
            return jsonify({"ok": False, "error": "Introduce correo y contraseña"})
        
        normalized_email = email.strip().lower()
        auth = _load_auth()

        if not auth:
            # Primera ejecución: credenciales locales.
            _save_auth(normalized_email, generate_password_hash(password))
        else:
            stored_email = (auth.get("email") or "").strip().lower()
            stored_hash = (auth.get("password_hash") or "").strip()

            if stored_email and stored_email != normalized_email:
                return jsonify({"ok": False, "error": "Ese correo no tiene permisos para el gestor."})

            if not _verify_password(stored_hash, password):
                return jsonify({"ok": False, "error": "Contraseña incorrecta"})

            # Migrar hash legacy sha256 -> werkzeug
            if ":" not in stored_hash:
                _save_auth(normalized_email, generate_password_hash(password))

        session["authenticated"] = True
        session["email"] = normalized_email
        save_last_user(normalized_email)
        return jsonify({"ok": True, "message": "Autenticación correcta"})
    
    # GET request
    return render_template("login.html", last_email=load_last_user())


@manager_app.route("/logout")
def logout():
    """Cerrar sesión"""
    session.clear()
    return redirect(url_for("login"))


@manager_app.route("/panel")
@login_required
def panel():
    """Panel principal de configuración"""
    return render_template("panel.html", 
                         groups=ENV_VARIABLES, 
                         email=session.get("email"))


@manager_app.route("/api/env", methods=["GET"])
@login_required
def get_env():
    """Obtiene todas las variables de entorno"""
    env = load_env()
    
    # Desencriptar variables sensibles para mostrar
    result = {}
    for key, value in env.items():
        if key in SENSITIVE_KEYS and value:
            decrypted = unwrap_fernet_layers(value)
            if decrypted is None:
                try:
                    decrypted = decrypt_value(value)
                except Exception:
                    decrypted = None
            if decrypted is None:
                result[key] = DECRYPT_ERROR_PLACEHOLDER
            else:
                result[key] = decrypted
        else:
            result[key] = value
    
    return jsonify({"ok": True, "env": result})


@manager_app.route("/api/env", methods=["POST"])
@login_required
def save_env_api():
    """Guarda las variables de entorno"""
    data = request.get_json()
    if not data or "env" not in data:
        return jsonify({"ok": False, "error": "Datos inválidos"})
    
    env_data = data["env"]
    current_env = load_env()
    processed = {}
    
    for key, value in env_data.items():
        if value == DECRYPT_ERROR_PLACEHOLDER:
            # Mantener el valor encriptado actual para evitar perder secretos
            processed[key] = current_env.get(key, "")
            continue

        if not value:
            processed[key] = ""
            continue
        
        # Encriptar variables sensibles
        if key in SENSITIVE_KEYS:
            try:
                processed[key] = encrypt_value(value)
            except Exception as e:
                return jsonify({"ok": False, "error": f"Error encriptando {key}: {str(e)}"})
        else:
            processed[key] = value
    
    try:
        save_env(processed)
        
        # Regenerar archivos de Google Drive si es necesario
        files_created = []
        errors = []
        
        if processed.get("GOOGLE_DRIVE_OAUTH_CREDENTIALS_JSON"):
            try:
                ensure_google_drive_credentials_file(os.getcwd())
                files_created.append("credentials_drive_oauth.json")
            except Exception as e:
                errors.append(f"credentials_drive_oauth.json: {e}")
        
        if processed.get("GOOGLE_DRIVE_TOKEN_JSON"):
            try:
                ensure_google_drive_token_file(os.getcwd())
                files_created.append("token_drive.json")
            except Exception as e:
                errors.append(f"token_drive.json: {e}")
        
        return jsonify({
            "ok": True,
            "message": "Configuración guardada correctamente",
            "files_created": files_created,
            "errors": errors
        })
        
    except Exception as e:
        return jsonify({"ok": False, "error": f"Error guardando: {str(e)}"})


@manager_app.route("/api/change-password", methods=["POST"])
@login_required
def change_password():
    """Cambia la contraseña del gestor (credenciales locales)."""
    data = request.get_json()
    new_password = data.get("password", "")
    
    if not new_password or len(new_password) < 8:
        return jsonify({"ok": False, "error": "La contraseña debe tener al menos 8 caracteres"})
    
    try:
        email = (session.get("email") or "").strip().lower()
        if not email:
            return jsonify({"ok": False, "error": "Sesión inválida"})

        _save_auth(email, generate_password_hash(new_password))
        return jsonify({"ok": True, "message": "Contraseña actualizada"})
    except Exception as e:
        return jsonify({"ok": False, "error": f"Error: {str(e)}"})


@manager_app.route("/api/test-db")
@login_required
def test_db():
    """Prueba la conexión a la base de datos"""
    try:
        # Recargar variables de entorno para asegurar valores actualizados
        load_dotenv(ENV_PATH, override=True)
        app = create_ampa_app(os.getenv("FLASK_ENV", "development"))
        with app.app_context():
            # Intenta una consulta simple
            User.query.first()
            return jsonify({"ok": True, "message": "Conexión exitosa"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@manager_app.route("/api/setup-drive-folders", methods=["POST"])
@login_required
def setup_drive_folders():
    """Busca o crea las carpetas de Drive y guarda sus IDs en .env."""
    try:
        load_dotenv(ENV_PATH, override=True)
        app = create_ampa_app(os.getenv("FLASK_ENV", "development"))

        with app.app_context():
            from app.media_utils import _get_user_drive_service, ensure_folder

            drive_service = _get_user_drive_service()
            if drive_service is None:
                return jsonify(
                    {
                        "ok": False,
                        "error": "No se pudo autenticar con Google Drive. Revisa credenciales/token.",
                    }
                )

            shared_drive_id = app.config.get("GOOGLE_DRIVE_SHARED_DRIVE_ID") or None

            root_id = (app.config.get("GOOGLE_DRIVE_ROOT_FOLDER_ID") or "").strip() or None
            root_name = (app.config.get("GOOGLE_DRIVE_ROOT_FOLDER_NAME") or "WEB Ampa").strip()
            selected_root_reason = None

            if root_id:
                try:
                    meta = (
                        drive_service.files()
                        .get(fileId=root_id, fields="id,name,mimeType,parents", supportsAllDrives=True)
                        .execute()
                    )
                    if meta.get("mimeType") != "application/vnd.google-apps.folder":
                        return jsonify({"ok": False, "error": "GOOGLE_DRIVE_ROOT_FOLDER_ID no es una carpeta."})

                    # Si la carpeta existe pero no tiene parents, no se vera en "Mi unidad".
                    parents = meta.get("parents") or []
                    if not shared_drive_id and not parents:
                        try:
                            drive_service.files().update(
                                fileId=root_id,
                                addParents="root",
                                fields="id,parents",
                                supportsAllDrives=True,
                            ).execute()
                            selected_root_reason = selected_root_reason or (
                                "La carpeta raiz no tenia parents; se ha colgado de 'Mi unidad'."
                            )
                        except Exception:  # noqa: BLE001
                            pass

                    # Asegurar que el nombre coincide con GOOGLE_DRIVE_ROOT_FOLDER_NAME.
                    if root_name and meta.get("name") and meta.get("name") != root_name:
                        try:
                            drive_service.files().update(
                                fileId=root_id,
                                body={"name": root_name},
                                fields="id,name",
                                supportsAllDrives=True,
                            ).execute()
                            selected_root_reason = selected_root_reason or (
                                "La carpeta raiz se ha renombrado para coincidir con GOOGLE_DRIVE_ROOT_FOLDER_NAME."
                            )
                        except Exception:  # noqa: BLE001
                            pass
                except Exception as e:  # noqa: BLE001
                    # Drive responde 404 también cuando el usuario/app no tiene acceso al recurso.
                    # En vez de abortar, reintentamos detectando/creando una carpeta accesible.
                    root_id = None
                    selected_root_reason = (
                        "GOOGLE_DRIVE_ROOT_FOLDER_ID no es accesible con el token actual; "
                        "se buscará o creará una carpeta nueva."
                    )

            if not root_id:
                # Intentar seleccionar una carpeta existente en vez de crear duplicados.
                root_parent = "root"
                if shared_drive_id:
                    # En Unidades compartidas, el "raíz" se referencia por el id de la unidad.
                    root_parent = shared_drive_id
                list_kwargs = {
                    "q": (
                        "mimeType='application/vnd.google-apps.folder' and trashed=false and "
                        f"name='{root_name}' and '{root_parent}' in parents"
                    ),
                    "spaces": "drive",
                    "fields": "files(id,name,createdTime)",
                    "supportsAllDrives": True,
                    "includeItemsFromAllDrives": True,
                    "pageSize": 50,
                }
                if shared_drive_id:
                    list_kwargs["corpora"] = "drive"
                    list_kwargs["driveId"] = shared_drive_id
                candidates = drive_service.files().list(**list_kwargs).execute().get("files", [])

                def _score_root(folder_id: str) -> int:
                    try:
                        child_kwargs = {
                            "q": (
                                f"'{folder_id}' in parents and trashed=false and "
                                "mimeType='application/vnd.google-apps.folder'"
                            ),
                            "spaces": "drive",
                            "fields": "files(id,name)",
                            "pageSize": 200,
                            "supportsAllDrives": True,
                            "includeItemsFromAllDrives": True,
                        }
                        if shared_drive_id:
                            child_kwargs["corpora"] = "drive"
                            child_kwargs["driveId"] = shared_drive_id
                        children = drive_service.files().list(**child_kwargs).execute().get("files", [])
                    except Exception:
                        return 0
                    names = {c.get("name") for c in children}
                    expected = {"Noticias", "Eventos", "Documentos"}
                    return len(expected.intersection(names))

                if candidates:
                    scored = [(c.get("id"), _score_root(c.get("id"))) for c in candidates if c.get("id")]
                    scored.sort(key=lambda t: t[1], reverse=True)
                    best_id, best_score = scored[0]
                    if best_score > 0:
                        root_id = best_id
                        selected_root_reason = "Se detectó una carpeta existente por subcarpetas."
                    elif len(scored) == 1:
                        root_id = best_id
                        selected_root_reason = "Se detectó una carpeta existente por nombre."
                    else:
                        # Si hay varias y ninguna parece la correcta, crear una nueva puede duplicar; devolver error.
                        return jsonify(
                            {
                                "ok": False,
                                "error": (
                                    "Hay varias carpetas con el nombre de raíz y no se pudo determinar cuál usar. "
                                    "Configura GOOGLE_DRIVE_ROOT_FOLDER_ID manualmente y reintenta."
                                ),
                                "candidates": [{"id": fid, "score": score} for fid, score in scored],
                            }
                        )

                if not root_id:
                    root_id = ensure_folder(root_name, parent_id=None, drive_id=shared_drive_id)
                    selected_root_reason = selected_root_reason or "No existía carpeta; se creó una nueva."

            commissions_name = (app.config.get("GOOGLE_DRIVE_COMMISSIONS_FOLDER_NAME") or "Comisiones").strip()
            news_name = (app.config.get("GOOGLE_DRIVE_NEWS_FOLDER_NAME") or "Noticias").strip()
            events_name = (app.config.get("GOOGLE_DRIVE_EVENTS_FOLDER_NAME") or "Eventos").strip()
            docs_name = (app.config.get("GOOGLE_DRIVE_DOCS_FOLDER_NAME") or "Documentos").strip()
            backup_name = (app.config.get("GOOGLE_DRIVE_DB_BACKUP_FOLDER_NAME") or "Backup DB_WEB").strip()

            commissions_id = ensure_folder(commissions_name, parent_id=root_id, drive_id=shared_drive_id)
            news_id = ensure_folder(news_name, parent_id=root_id, drive_id=shared_drive_id)
            events_id = ensure_folder(events_name, parent_id=root_id, drive_id=shared_drive_id)
            docs_id = ensure_folder(docs_name, parent_id=root_id, drive_id=shared_drive_id)
            backup_id = ensure_folder(backup_name, parent_id=root_id, drive_id=shared_drive_id)

        env = load_env()
        env_updates = {
            "GOOGLE_DRIVE_ROOT_FOLDER_ID": root_id,
            "GOOGLE_DRIVE_COMMISSIONS_FOLDER_ID": commissions_id,
            "GOOGLE_DRIVE_NEWS_FOLDER_ID": news_id,
            "GOOGLE_DRIVE_EVENTS_FOLDER_ID": events_id,
            "GOOGLE_DRIVE_DOCS_FOLDER_ID": docs_id,
            "GOOGLE_DRIVE_DB_BACKUP_FOLDER_ID": backup_id,
        }
        env.update(env_updates)
        save_env(env)

        return jsonify(
            {
                "ok": True,
                "message": "Carpetas configuradas y IDs guardados en .env",
                "ids": env_updates,
                "root_selection": selected_root_reason,
            }
        )
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(e)})


@manager_app.route("/api/db-backups", methods=["GET"])
@login_required
def list_db_backups():
    """Lista los backups disponibles en Drive (carpeta de backups)."""
    try:
        load_dotenv(ENV_PATH, override=True)
        app = create_ampa_app(os.getenv("FLASK_ENV", "development"))
        with app.app_context():
            from app.media_utils import _get_user_drive_service
            from app.services.db_restore_service import list_db_backups_from_drive

            try:
                files = list_db_backups_from_drive(limit=50)
            except Exception:
                files = []

            folder_id = (app.config.get("GOOGLE_DRIVE_DB_BACKUP_FOLDER_ID") or "").strip()
            root_id = (app.config.get("GOOGLE_DRIVE_ROOT_FOLDER_ID") or "").strip()
            backup_name = (app.config.get("GOOGLE_DRIVE_DB_BACKUP_FOLDER_NAME") or "Backup DB_WEB").strip()
            prefix = (app.config.get("DB_BACKUP_FILENAME_PREFIX") or "BD_WEB_Ampa_Julian_Nieto").strip() + "_"
            source = "folder"

            # Si no hay resultados, intentar autodetectar la carpeta por nombre bajo la raíz y guardar el ID.
            if (not files) and root_id:
                drive = _get_user_drive_service()
                if drive is not None:
                    resp = (
                        drive.files()
                        .list(
                            q=(
                                "mimeType='application/vnd.google-apps.folder' and trashed=false and "
                                f"name='{backup_name}' and '{root_id}' in parents"
                            ),
                            spaces="drive",
                            fields="files(id,name)",
                            pageSize=20,
                            supportsAllDrives=True,
                            includeItemsFromAllDrives=True,
                        )
                        .execute()
                    )
                    candidates = resp.get("files", []) or []
                    if candidates:
                        # Elegir la carpeta con más backups.
                        def _count_backups(fid: str) -> int:
                            try:
                                r = (
                                    drive.files()
                                    .list(
                                        q=(f"'{fid}' in parents and trashed=false and name contains '.sql.gz'"),
                                        spaces="drive",
                                        fields="files(id)",
                                        pageSize=100,
                                        supportsAllDrives=True,
                                        includeItemsFromAllDrives=True,
                                    )
                                    .execute()
                                )
                                return len(r.get("files", []) or [])
                            except Exception:
                                return 0

                        scored = [(c.get("id"), _count_backups(c.get("id"))) for c in candidates if c.get("id")]
                        scored.sort(key=lambda t: t[1], reverse=True)
                        best_id = scored[0][0] if scored else None
                        if best_id and best_id != folder_id:
                            env = load_env()
                            env["GOOGLE_DRIVE_DB_BACKUP_FOLDER_ID"] = best_id
                            save_env(env)
                            folder_id = best_id

                        # Reintentar listado
                        files = list_db_backups_from_drive(limit=50)
                        source = "auto_folder"

            # Último fallback: buscar backups por nombre en todo Drive (útil si hubo carpetas duplicadas).
            if not files:
                drive = _get_user_drive_service()
                if drive is not None:
                    resp = (
                        drive.files()
                        .list(
                            q=(f"trashed=false and name contains '{prefix}' and name contains '.sql.gz'"),
                            spaces="drive",
                            fields="files(id,name,createdTime,size)",
                            orderBy="createdTime desc",
                            pageSize=50,
                            supportsAllDrives=True,
                            includeItemsFromAllDrives=True,
                        )
                        .execute()
                    )
                    files = resp.get("files", []) or []
                    source = "global_search"

        return jsonify({"ok": True, "files": files, "folder_id": folder_id, "source": source})
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(e)})


@manager_app.route("/api/restore-db-backup", methods=["POST"])
@login_required
def restore_db_backup():
    """Restaura la base de datos desde un backup de Drive."""
    data = request.get_json() or {}
    file_id = (data.get("file_id") or "").strip()
    confirm = (data.get("confirm") or "").strip().upper()

    if confirm not in {"RESTORE", "RESTAURAR"}:
        return jsonify({"ok": False, "error": "Confirmación inválida. Escribe RESTAURAR para continuar."})

    try:
        load_dotenv(ENV_PATH, override=True)
        app = create_ampa_app(os.getenv("FLASK_ENV", "development"))
        with app.app_context():
            from app.services.db_restore_service import restore_db_from_drive_backup

            result = restore_db_from_drive_backup(file_id)
        if result.ok:
            return jsonify({"ok": True, "message": result.message})
        return jsonify({"ok": False, "error": result.message})
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(e)})


@manager_app.route("/api/force-db-backup", methods=["POST"])
@login_required
def force_db_backup():
    """Fuerza un backup de la BD y lo sube a Google Drive."""
    try:
        load_dotenv(ENV_PATH, override=True)
        app = create_ampa_app(os.getenv("FLASK_ENV", "development"))
        with app.app_context():
            from app.services.db_backup_service import run_db_backup_to_drive

            result = run_db_backup_to_drive(force=True)
            if result.ok:
                return jsonify(
                    {
                        "ok": True,
                        "message": result.message,
                        "drive_file_id": result.drive_file_id,
                        "drive_folder_id": result.drive_folder_id,
                    }
                )
            return jsonify({"ok": False, "error": result.message})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@manager_app.route("/api/test-calendar")
@login_required
def test_calendar():
    """Prueba la conexión con Google Calendar"""
    try:
        # Recargar variables de entorno para asegurar valores actualizados
        load_dotenv(ENV_PATH, override=True)
        app = create_ampa_app(os.getenv("FLASK_ENV", "development"))
        with app.app_context():
            from services.calendar_service import get_calendar_events
            result = get_calendar_events(max_results=5, use_cache=False)
            return jsonify(result)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@manager_app.route("/api/test-mail")
@login_required
def test_mail():
    """Prueba el envío de correo electrónico (Gmail API OAuth)."""
    try:
        # Recargar variables de entorno para asegurar valores actualizados
        load_dotenv(ENV_PATH, override=True)
        app = create_ampa_app(os.getenv("FLASK_ENV", "development"))

        with app.app_context():
            from app.services.mail_service import send_email_gmail_api

            # Priorizar MAIL_CONTACT_RECIPIENT, si no existe usar el email de la sesión
            recipient = app.config.get("MAIL_CONTACT_RECIPIENT") or session.get("email")
            if not recipient:
                return jsonify(
                    {
                        "ok": False,
                        "error": "No hay email de destinatario (MAIL_CONTACT_RECIPIENT no definido).",
                    }
                )

            text_body = (
                "¡Hola!\n\n"
                "Este es un correo de prueba enviado desde el Gestor de Configuración AMPA.\n"
                "Proveedor: Gmail API (OAuth 2.0)\n\n"
                "Si recibes este mensaje, la configuración de correo es correcta.\n\n"
                "Requisitos:\n"
                "- GOOGLE_DRIVE_TOKEN_JSON con refresh_token\n"
                "- Scopes unificados, incluyendo https://www.googleapis.com/auth/gmail.send\n"
            )

            html_body = """
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <h2 style="color: #4f46e5;">✅ Prueba de Correo (Gmail API) Exitosa</h2>
                <p>¡Hola!</p>
                <p>Este es un correo de prueba enviado desde el <strong>Gestor de Configuración AMPA</strong>.</p>
                <p>Proveedor: <strong>Gmail API (OAuth 2.0)</strong></p>
                <p>Si recibes este mensaje, la configuración de correo es correcta.</p>
                <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 20px 0;">
                <h4 style="color: #374151;">📌 Requisitos:</h4>
                <ul style="color: #6b7280;">
                    <li><code>GOOGLE_DRIVE_TOKEN_JSON</code> con <code>refresh_token</code></li>
                    <li>Scope <code>https://www.googleapis.com/auth/gmail.send</code> incluido</li>
                </ul>
                <p style="color: #9ca3af; font-size: 12px; margin-top: 30px;">Gestor de Configuración AMPA</p>
            </div>
            """

            result = send_email_gmail_api(
                subject="[AMPA] Prueba de configuración de correo (Gmail API)",
                body_text=text_body,
                body_html=html_body,
                recipient=recipient,
                app_config=app.config,
            )

            if result.get("ok"):
                return jsonify(
                    {
                        "ok": True,
                        "message": f"Correo de prueba enviado a {recipient}",
                        "provider": result.get("provider"),
                        "id": result.get("id"),
                    }
                )
            return jsonify({"ok": False, "error": result.get("error") or "Error desconocido"})

    except Exception as e:
        import traceback

        full_error = traceback.format_exc()
        print(f"Error en test_mail: {full_error}")  # Log para debug
        return jsonify({"ok": False, "error": str(e)})


@manager_app.route("/api/variables-info")
def variables_info():
    """Devuelve la información de todas las variables"""
    return jsonify(ENV_VARIABLES)


def open_browser():
    """Abre el navegador después de un breve retraso"""
    import time
    time.sleep(1)
    webbrowser.open(f"http://localhost:{SERVER_PORT}")


def run_server():
    """Inicia el servidor Flask"""
    print(f"\n🔧 Gestor de Configuración AMPA")
    print(f"   Abriendo navegador en http://localhost:{SERVER_PORT}")
    print(f"   Presiona Ctrl+C para cerrar\n")
    
    # Abrir navegador en un hilo separado
    threading.Thread(target=open_browser, daemon=True).start()
    
    # Ejecutar servidor
    manager_app.run(host="127.0.0.1", port=SERVER_PORT, debug=False, threaded=True)


if __name__ == "__main__":
    run_server()
