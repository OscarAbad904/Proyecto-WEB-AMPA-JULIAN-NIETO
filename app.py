# ====================================================================================
# IMPORTACIONES Y CONFIGURACIÓN
# ====================================================================================
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_jwt_extended  import (JWTManager, create_access_token,jwt_required, get_jwt_identity)
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import timedelta
import sqlite3
import pyodbc
from functools import wraps
import os, sys
import json
import threading
import socket

from config import DB_USER, DB_PASSWORD, SECRET_KEY, SHUTDOWN_SECRET_KEY

# ====================================================================================
# CLASE DE CONEXIÓN ODBC
# ====================================================================================
class ConexionODBC:
    # Maneja la conexión a una base de datos externa via ODBC (ej: SQL Server).
    def __init__(self, database=None, servidor='EMEBIDWH'):
        try:
            # Tomar valores por defecto del config.ini si no se proporcionan
            hostname = socket.gethostname()

            if hostname == 'PortatilOscar':
                driver = 'ODBC Driver 17 for SQL Server'
                servidor = 'localhost\\EMEBIDWH'
            else:
                driver = 'SQL Server'

            self.driver = driver
            self.server = servidor
            self.database = database
            self.conn = None

        except Exception as e:
            print(f"Error en ConexionODBC / __init__: {str(e)}")

    def __enter__(self):
        try:
            # Construir cadena de conexión ODBC y abrir conexión
            if self.server == 'EMEBIDWH':
                conn_str = f"""DRIVER={{{self.driver}}};
                               SERVER={self.server};
                               DATABASE={self.database};
                               UID={DB_USER};
                               PWD={DB_PASSWORD};
                               Trusted_Connection=no;"""
            else:
                conn_str = f"""DRIVER={{{self.driver}}};
                               SERVER={self.server};
                               Trusted_Connection=yes;"""
            
            self.conn = pyodbc.connect(conn_str)
            return self.conn

        except Exception as e:
            print(f"Error en ConexionODBC / __enter__: {str(e)}")            

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            # Cerrar conexión al salir del contexto
            if self.conn:
                self.conn.close()

        except Exception as e:
            print(f"Error en ConexionODBC / __exit__: {str(e)}")    


# ====================================================================================
# DECORADOR PARA RUTAS PROTEGIDAS
# ====================================================================================
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# ====================================================================================
# CONFIGURACIÓN DE LA APLICACIÓN
# ====================================================================================
if getattr(sys, 'frozen', False):
    # Cuando está empaquetado con PyInstaller
    base_dir = os.path.dirname(sys.executable)
else:
    # En modo desarrollo
    base_dir = os.path.abspath(os.path.dirname(__file__))

carpeta_plantillas = os.path.join(base_dir, 'templates')
carpeta_recursos_estaticos = os.path.join(base_dir, 'assets')

app = Flask(
    __name__,
    template_folder=carpeta_plantillas,
    static_folder=carpeta_recursos_estaticos,
    static_url_path='/assets'
)
app.secret_key = SECRET_KEY  # Clave secreta necesaria para sesiones seguras
# Duración por defecto del access token
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(minutes=30)
# (Opcional) Duración por defecto del refresh token
app.config['JWT_REFRESH_TOKEN_EXPIRES'] = timedelta(hours=8)

# El JWT solo vendrá en la cabecera Authorization
app.config["JWT_TOKEN_LOCATION"] = ["headers"]
# Desactiva la protección CSRF (solo necesaria si usaras JWT en cookies)
app.config["JWT_COOKIE_CSRF_PROTECT"] = False
# Si no tienes clave JWT explícita, reutiliza la de Flask
app.config["JWT_SECRET_KEY"] = app.secret_key

jwt = JWTManager(app)

# ====================================================================================
# MANEJADOR DE ERRORES JWT ÚTIL PARA DEPURAR
# ====================================================================================
@jwt.invalid_token_loader
def invalid_callback(err):
    print('INVALID JWT:', err)
    return jsonify(msg="Token inválido"), 401

# ====================================================================================
# RUTA DE LOGIN (MODAL)
# ====================================================================================
@app.route('/login_modal', methods=['POST'])
def login_modal():
    data = request.get_json()
    username = data.get('username')
    password_input = data.get('password')
  
    with ConexionODBC(database='Digitalizacion') as conn:
        cursor = conn.cursor()
        cursor.execute("""
                       SELECT A.password, C.Role
                       FROM WEB_User_Login A
                       LEFT JOIN WEB_User_Role B ON B.idUserName = A.id
                       LEFT JOIN WEB_Roles C ON B.idRole = C.id
                       WHERE A.username = ?"""
                       , (username,))
        result = cursor.fetchone()
        print("Conexión a SQL Server establecida correctamente.")

    if result and check_password_hash(result[0], password_input):
        session['username'] = username
        session['role'] = result[1]
        access_token = create_access_token(identity=[username, result[1]])

        return jsonify(success=True, access_token=access_token)
    else:
        return jsonify(success=False, message="Usuario o contraseña incorrectos.")

# ====================================================================================
# RUTA PARA CERRAR SESIÓN
# ====================================================================================
@app.route('/logout')
def logout():
    session.clear() 
    return redirect(url_for('main'))

# ====================================================================================
# RUTA DE REGISTRO (MODAL)
# ====================================================================================
@app.route('/register_modal', methods=['POST'])
def register_modal():
    try:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        role = data.get('role')
        password_hashed = generate_password_hash(password)

        print(f"Username: {username}, Password: {password_hashed}, Role: {role}")

        with ConexionODBC(database='Digitalizacion') as conn:
            cursor = conn.cursor()
            cursor.execute('INSERT INTO WEB_User_Login (UserName, password) VALUES (?, ?)', (username, password_hashed))
            conn.commit()
            cursor.execute('SELECT id FROM WEB_User_Login WHERE UserName = ?', (username,))
            idUserName = cursor.fetchone()[0]
            cursor.execute('SELECT id FROM WEB_Roles WHERE Role = ?', (role,))
            idRole = cursor.fetchone()[0]
            cursor.execute('INSERT INTO WEB_User_Role (idUserName, idRole) VALUES (?, ?)', (idUserName, idRole))
            conn.commit()            
            print("Insercion establecida correctamente.")
        
        return jsonify(success=True)
    except pyodbc.IntegrityError:
        return jsonify(success=False, message="El nombre de usuario ya existe.")

# ====================================================================================
# Endpoint para obtener los roles desde la base de datos para el registro
# ====================================================================================
@app.route('/Roles', methods=['GET'])
def Roles():
    with ConexionODBC(database='Digitalizacion') as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT role FROM WEB_Roles')
        result = cursor.fetchone()

        RolesList = []
        while result:
            RolesList.append(result[0])
            result = cursor.fetchone()

    return jsonify({ 'Roles': RolesList })

# ====================================================================================
# Ruta raiz (redirecion a /main)
# ====================================================================================
@app.route('/')
def redirigir_inicio():
    return redirect(url_for('vista_principal'))

# ====================================================================================
# Ruta principal (main)
# ====================================================================================
@app.route('/AMPA')
def vista_principal():
    nombre_usuario = session.get('username')
    rol_usuario = session.get('role')

    return render_template('index.html', nombre_usuario=nombre_usuario, rol_usuario=rol_usuario)

# ====================================================================================
# Endpoint para limpiar el mensaje del modal
# ====================================================================================
@app.route('/clear_modal_message', methods=['POST'])
def clear_modal_message():
    session.pop('modal_message', None)
    return ('', 204)

# ====================================================================================
# Funcion para cierre controlado de app.exe
# ====================================================================================
def shutdown_server_func():
    func = request.environ.get('werkzeug.server.shutdown')
    if func is None:
        # Esto podría pasar si no estás usando el servidor de desarrollo de Werkzeug
        # o si ya se está cerrando.
        print('Servidor no es Werkzeug o ya se está cerrando.')
        # En un servidor de producción (Gunicorn, uWSGI), el mecanismo es diferente
        # (ej: enviar una señal al proceso master).
        # Para un .exe empaquetado con PyInstaller, esto suele ser lo que se usa.
        # Como último recurso, el actualizador puede matar el proceso forzosamente.
        # Para un .exe simple, podrías intentar sys.exit() aquí, pero shutdown es mejor.
        # os._exit(0) # Forzaría la salida, pero menos limpio
        return
    print("Llamando a werkzeug.server.shutdown()...")
    func()

# ====================================================================================
# Endpoint para cerrar el servidor
# ====================================================================================
@app.route('/shutdown_api', methods=['POST'])
def shutdown_api():
    token = request.args.get('token')
    if token != SHUTDOWN_SECRET_KEY:
        print(f"Intento de shutdown no autorizado. Token recibido: {token}")
        return jsonify(message="No autorizado"), 401

    print("Solicitud de cierre recibida. Cerrando el servidor...")
    # Es mejor programar el cierre en un hilo separado para permitir que esta respuesta se envíe.
    # El cliente (actualizador) no debería esperar realmente a que esta respuesta se complete,
    # sino proceder a verificar si el proceso ha terminado.
    shutdown_thread = threading.Timer(1.0, shutdown_server_func)
    shutdown_thread.start()
    return jsonify(message="Servidor cerrándose..."), 200

# ====================================================================================
# EJECUCIÓN DE LA APLICACIÓN
# ====================================================================================
if __name__ == '__main__':
    print(f"API iniciada. Para cerrarla (si el actualizador lo necesita), usa el token: {SHUTDOWN_SECRET_KEY}")
    # Asegúrate que tu .env tiene SHUTDOWN_SECRET_KEY o cámbialo en el código.
    app.run(host='0.0.0.0', port=5000, debug=True) # debug=False en producción si no lo necesitas para el shutdown
    