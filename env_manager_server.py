"""
Servidor Flask para el Gestor de Configuración AMPA.

Proporciona una interfaz web moderna para gestionar las variables de entorno
del proyecto de forma segura y centralizada.

Uso:
    python env_manager_gui.py
    
    Abrirá automáticamente el navegador en http://localhost:5050
"""

import os
import json
import webbrowser
import threading
from pathlib import Path
from functools import wraps

from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from dotenv import dotenv_values, load_dotenv

# Importaciones del proyecto AMPA
from Api_AMPA_WEB import create_app as create_ampa_app, db, User, Role, make_lookup_hash
from config import (
    encrypt_value,
    decrypt_value,
    ensure_google_drive_credentials_file,
    ensure_google_drive_token_file,
    unwrap_fernet_layers,
)

# Configuración
ENV_PATH = ".env"
CONFIG_FILE = "gui_config.json"
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
            "SHUTDOWN_SECRET_KEY": {
                "label": "Clave de Apagado",
                "sensitive": True,
                "required": False,
                "default": "",
                "help": {
                    "description": "Clave secreta para endpoints de administración como apagado remoto del servidor.",
                    "how_to_get": "Genera una clave única:\n\nimport secrets\nprint(secrets.token_urlsafe(32))",
                    "example": "shutdown-key-abc123",
                    "warning": "Solo necesaria si usas funciones de administración remota."
                }
            }
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
        "description": "Configuración de conexión a PostgreSQL",
        "vars": {
            "SQLALCHEMY_DATABASE_URI": {
                "label": "URI Completa de BD",
                "sensitive": True,
                "required": False,
                "default": "",
                "help": {
                    "description": "URI completa de conexión a PostgreSQL. Tiene prioridad sobre las variables individuales.",
                    "how_to_get": "En Render, copia la 'Internal Database URL' de tu base de datos PostgreSQL.",
                    "example": "postgresql+psycopg2://user:pass@host:5432/dbname",
                    "warning": "Contiene credenciales. Usar variables individuales es más seguro."
                }
            },
            "DATABASE_URL": {
                "label": "URL de Base de Datos",
                "sensitive": True,
                "required": False,
                "default": "",
                "help": {
                    "description": "URL alternativa de conexión (formato Heroku/Render). Se usa si SQLALCHEMY_DATABASE_URI no está definida.",
                    "how_to_get": "Render la proporciona automáticamente como variable de entorno.",
                    "example": "postgres://user:pass@host:5432/dbname",
                    "warning": "El prefijo 'postgres://' se convierte automáticamente a 'postgresql+psycopg2://'."
                }
            },
            "POSTGRES_HOST": {
                "label": "Host PostgreSQL",
                "sensitive": False,
                "required": False,
                "default": "localhost",
                "help": {
                    "description": "Servidor de la base de datos PostgreSQL.",
                    "how_to_get": "En Render es el hostname interno, ej: dpg-xxx-a.oregon-postgres.render.com",
                    "example": "localhost",
                    "warning": ""
                }
            },
            "POSTGRES_PORT": {
                "label": "Puerto PostgreSQL",
                "sensitive": False,
                "required": False,
                "default": "5432",
                "help": {
                    "description": "Puerto de conexión a PostgreSQL (por defecto 5432).",
                    "how_to_get": "Normalmente es 5432 a menos que tu servidor use otro.",
                    "example": "5432",
                    "warning": ""
                }
            },
            "POSTGRES_USER": {
                "label": "Usuario PostgreSQL",
                "sensitive": False,
                "required": False,
                "default": "",
                "help": {
                    "description": "Nombre de usuario para conectar a PostgreSQL.",
                    "how_to_get": "Lo define Render al crear la base de datos.",
                    "example": "ampa_user",
                    "warning": ""
                }
            },
            "POSTGRES_PASSWORD": {
                "label": "Contraseña PostgreSQL",
                "sensitive": True,
                "required": False,
                "default": "",
                "help": {
                    "description": "Contraseña del usuario de PostgreSQL.",
                    "how_to_get": "La genera Render automáticamente.",
                    "example": "",
                    "warning": "Nunca la compartas ni la incluyas en el código."
                }
            },
            "POSTGRES_DB": {
                "label": "Nombre de BD",
                "sensitive": False,
                "required": False,
                "default": "",
                "help": {
                    "description": "Nombre de la base de datos PostgreSQL.",
                    "how_to_get": "Lo defines al crear la base de datos en Render.",
                    "example": "ampa_db",
                    "warning": ""
                }
            }
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
            "GOOGLE_DRIVE_SHARED_DRIVE_ID": {
                "label": "ID de Unidad Compartida",
                "sensitive": False,
                "required": False,
                "default": "",
                "help": {
                    "description": "ID de la Unidad Compartida (Shared Drive) si usas una en lugar de Mi unidad.",
                    "how_to_get": "En Google Drive, abre la unidad compartida. El ID está en la URL después de /drive/folders/",
                    "example": "0AJ8Hx...",
                    "warning": "Déjalo vacío si usas Mi unidad personal."
                }
            },
            "GOOGLE_DRIVE_NEWS_FOLDER_ID": {
                "label": "ID Carpeta Noticias",
                "sensitive": False,
                "required": False,
                "default": "",
                "help": {
                    "description": "ID de la carpeta de Drive donde se guardan las imágenes de noticias.",
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
    "paths": {
        "title": "📂 Rutas y Directorios",
        "description": "Configuración de rutas del sistema",
        "vars": {
            "AMPA_DATA_DIR": {
                "label": "Directorio de Datos",
                "sensitive": False,
                "required": False,
                "default": "Data",
                "help": {
                    "description": "Directorio donde se almacenan datos locales de la aplicación.",
                    "how_to_get": "Por defecto es 'Data' en la raíz del proyecto.",
                    "example": "Data",
                    "warning": ""
                }
            }
        }
    }
}

# Variables sensibles que requieren encriptación
DECRYPT_ERROR_PLACEHOLDER = "[ERROR: No se pudo desencriptar]"

SENSITIVE_KEYS = {
    "SECRET_KEY",
    "SECURITY_PASSWORD_SALT",
    "SHUTDOWN_SECRET_KEY",
    "MAIL_PASSWORD",
    "POSTGRES_PASSWORD",
    "SQLALCHEMY_DATABASE_URI",
    "DATABASE_URL",
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
        
        try:
            app = create_ampa_app(os.getenv("FLASK_ENV", "development"))
            with app.app_context():
                admin = User.query.join(Role).filter(
                    Role.name_lookup == make_lookup_hash("admin")
                ).first()
                
                if admin:
                    if admin.email != email:
                        return jsonify({"ok": False, "error": "El administrador registrado usa otro correo"})
                    if not admin.check_password(password):
                        return jsonify({"ok": False, "error": "Contraseña incorrecta"})
                else:
                    # Crear nuevo admin
                    role = Role.query.filter_by(name_lookup=make_lookup_hash("admin")).first()
                    if not role:
                        role = Role(name="admin")
                        db.session.add(role)
                        db.session.commit()
                    admin = User(
                        username="admin",
                        email=email,
                        is_active=True,
                        email_verified=True,
                        role=role
                    )
                    admin.set_password(password)
                    db.session.add(admin)
                    db.session.commit()
                
                # Login exitoso
                session["authenticated"] = True
                session["email"] = email
                save_last_user(email)
                
                return jsonify({"ok": True, "message": "Autenticación correcta"})
                
        except Exception as e:
            return jsonify({"ok": False, "error": f"Error de conexión: {str(e)}"})
    
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
    """Cambia la contraseña del administrador"""
    data = request.get_json()
    new_password = data.get("password", "")
    
    if not new_password or len(new_password) < 8:
        return jsonify({"ok": False, "error": "La contraseña debe tener al menos 8 caracteres"})
    
    try:
        app = create_ampa_app(os.getenv("FLASK_ENV", "development"))
        with app.app_context():
            admin = User.query.join(Role).filter(
                Role.name_lookup == make_lookup_hash("admin")
            ).first()
            
            if admin and admin.email == session.get("email"):
                admin.set_password(new_password)
                db.session.commit()
                return jsonify({"ok": True, "message": "Contraseña actualizada"})
            else:
                return jsonify({"ok": False, "error": "Usuario no encontrado"})
                
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
    """Prueba el envío de correo electrónico"""
    try:
        # Leer la configuración directamente del .env y desencriptar
        env = load_env()
        
        mail_server = env.get("MAIL_SERVER", "smtp.gmail.com")
        mail_port = int(env.get("MAIL_PORT", "587"))
        mail_use_tls = env.get("MAIL_USE_TLS", "true").lower() in ("true", "1", "yes")
        mail_username = env.get("MAIL_USERNAME", "")
        
        # Desencriptar contraseña
        mail_password_raw = env.get("MAIL_PASSWORD", "")
        try:
            mail_password = decrypt_value(mail_password_raw) if mail_password_raw else ""
        except:
            mail_password = mail_password_raw  # Si no está encriptada, usar el valor directo
        
        mail_sender = env.get("MAIL_DEFAULT_SENDER", mail_username)
        # Priorizar MAIL_CONTACT_RECIPIENT, si no existe usar el email de la sesión
        recipient = env.get("MAIL_CONTACT_RECIPIENT") or session.get("email")
        
        if not recipient:
            return jsonify({"ok": False, "error": "No hay email de destinatario (MAIL_CONTACT_RECIPIENT no definido)"})
        
        if not mail_username or not mail_password:
            return jsonify({"ok": False, "error": "Falta configurar MAIL_USERNAME o MAIL_PASSWORD"})
        
        # Conectar directamente con smtplib
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        
        msg = MIMEMultipart('alternative')
        msg['Subject'] = "[AMPA] Prueba de configuración de correo"
        msg['From'] = mail_sender
        msg['To'] = recipient
        
        text_body = f"""¡Hola!

Este es un correo de prueba enviado desde el Gestor de Configuración AMPA.

Si recibes este mensaje, la configuración de correo es correcta.

Detalles de configuración:
- Servidor SMTP: {mail_server}
- Puerto: {mail_port}
- TLS: {'Sí' if mail_use_tls else 'No'}
- Usuario: {mail_username}
- Remitente: {mail_sender}

Saludos,
Gestor de Configuración AMPA
"""
        
        html_body = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <h2 style="color: #4f46e5;">✅ Prueba de Correo Exitosa</h2>
            <p>¡Hola!</p>
            <p>Este es un correo de prueba enviado desde el <strong>Gestor de Configuración AMPA</strong>.</p>
            <p>Si recibes este mensaje, la configuración de correo es correcta.</p>
            <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 20px 0;">
            <h4 style="color: #374151;">📧 Detalles de configuración:</h4>
            <ul style="color: #6b7280;">
                <li><strong>Servidor SMTP:</strong> {mail_server}</li>
                <li><strong>Puerto:</strong> {mail_port}</li>
                <li><strong>TLS:</strong> {'Sí' if mail_use_tls else 'No'}</li>
                <li><strong>Usuario:</strong> {mail_username}</li>
                <li><strong>Remitente:</strong> {mail_sender}</li>
            </ul>
            <p style="color: #9ca3af; font-size: 12px; margin-top: 30px;">Gestor de Configuración AMPA</p>
        </div>
        """
        
        msg.attach(MIMEText(text_body, 'plain'))
        msg.attach(MIMEText(html_body, 'html'))
        
        # Conectar y enviar
        if mail_use_tls:
            server = smtplib.SMTP(mail_server, mail_port)
            server.starttls()
        else:
            server = smtplib.SMTP_SSL(mail_server, mail_port)
        
        server.login(mail_username, mail_password)
        server.sendmail(mail_sender, [recipient], msg.as_string())
        server.quit()
        
        return jsonify({
            "ok": True, 
            "message": f"Correo de prueba enviado a {recipient}"
        })
            
    except Exception as e:
        import traceback
        error_msg = str(e)
        full_error = traceback.format_exc()
        print(f"Error en test_mail: {full_error}")  # Log para debug
        
        # Mensajes de error más amigables
        if "Authentication" in error_msg or "credentials" in error_msg.lower():
            error_msg = f"Error de autenticación. Verifica MAIL_USERNAME y MAIL_PASSWORD. Detalle: {error_msg}"
        elif "Connection" in error_msg or "connect" in error_msg.lower():
            error_msg = f"No se pudo conectar al servidor SMTP. Verifica MAIL_SERVER y MAIL_PORT. ({error_msg})"
        elif "timed out" in error_msg.lower():
            error_msg = "Tiempo de espera agotado. El servidor SMTP no responde."
        
        return jsonify({"ok": False, "error": error_msg})


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
