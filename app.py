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

template_dir = os.path.join(base_dir, 'templates')
static_dir = os.path.join(base_dir, 'static')

app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
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
def home():
    return redirect(url_for('main'))

# ====================================================================================
# Ruta principal (main)
# ====================================================================================
@app.route('/main')
def main():
    username = session.get('username')
    role = session.get('role')

    return render_template('main.html', username=username, role=role)

# ====================================================================================
# Ruta protegida con JWT: SECUENCIACIÓN EMESA
# ====================================================================================
@app.route('/SecuenciacionEMESA')
@login_required
def SecuenciacionEMESA():
    return render_template('SecuenciacionEMESA.html', username=session['username'], role=session['role'])

# ====================================================================================
# Ruta protegida con JWT: Tiempos Decoracion Clinchado EMESA
# ====================================================================================
@app.route('/TiemposDecoracionesClinchado')
@login_required
def TiemposDecoracionesClinchado():
    return render_template('TiemposDecoracionesClinchado.html', username=session['username'], role=session['role'])

# ====================================================================================
# Ruta protegida con JWT: VISOR DE PDF
# ====================================================================================
@app.route('/visor_PDF')
@login_required
def visor_PDF():
    if session['role'] == 'Administrador':
        return render_template('visor_PDF.html', username=session['username'], role=session['role'])
    else:
        session['modal_message'] = 'No tienes permisos para acceder a esta sección.'
        return redirect(url_for('main'))

# ====================================================================================
# Ruta protegida con JWT: EtiquetasV2 EMESA
# ====================================================================================
@app.route('/Configurador_Etiquetas')
@login_required
def Configurador_Etiquetas():
    return render_template('Configurador_Etiquetas.html', username=session['username'], role=session['role'])

# ====================================================================================
# Ruta protegida con JWT: Generador etiquetas impresoras EMESA
# ====================================================================================
@app.route('/EtiquetasV2')
@login_required
def EtiquetasV2():
    return render_template('EtiquetasV2.html', username=session['username'], role=session['role'])

# ====================================================================================
# Ruta protegida con JWT: FABRICA VISUAL EMESA
# ====================================================================================
@app.route('/FabricaVisual')
@login_required
def FabricaVisual():
    return redirect('http://emebidwh:100/')

# ====================================================================================
# Endpoint para obtener los trabajos desde la base de datos
# ====================================================================================
@app.route('/api/trabajos', methods=['GET'])
def api_trabajos():
    # 1) Abre la base de datos
    db_path    = os.path.join(base_dir, 'static', 'BaseDatos_Pruebas', 'Secuenciacion_Trabajos_Emesa.db')
    output_path= os.path.join(base_dir, 'static', 'data', 'TrabajosPendientes.json')
    conn       = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor     = conn.cursor()

    # 2) Ejecuta la consulta agregada con HAVING
    cursor.execute("""
        SELECT
          A.Trabajo,
          A.Maquina,
          SUM(A.TimPend * (A.QtyProg - A.QtyCort)) / 60       AS TiempoPendiente,
          SUM(A.QtyCort) * 100.0 / SUM(A.QtyProg)              AS EstadoCorte,
          MIN(C.FechaMaxFabricacion)                           AS FechaMaxima
        FROM CNCs_Pendientes_Corte_Semana A
        LEFT JOIN Datos_CNC_Lantek B ON B.Trabajo = A.Trabajo
        LEFT JOIN Pedidos_Trabajos_Lantek_Semana C ON C.CodLinea = B.CodLinea
        GROUP BY A.Trabajo, A.Maquina
        HAVING SUM(A.TimPend * (A.QtyProg - A.QtyCort)) > 0.00
        ORDER BY A.Trabajo;
    """)
    rows = cursor.fetchall()
    conn.close()

    # 3) Monta la lista con el formato exacto
    trabajos = []
    for idx, row in enumerate(rows, start=1):
        # tiempo con coma decimal
        tiempo = f"{float(row['TiempoPendiente']):.2f}".replace('.', ',')
        estado = f"{float(row['EstadoCorte']):.0f}%"

        # fecha en dd/mm/YYYY
        fecha = row['FechaMaxima']
        if fecha:
            y, m, d = fecha.split()[0].split('-')
            fecha_fmt = f"{d}/{m}/{y}"
        else:
            fecha_fmt = "Sin fecha"

        trabajos.append({
            'id':              str(idx),
            'Trabajo':         row['Trabajo'],
            'Maquina':         row['Maquina'],
            'TiempoPendiente': tiempo,
            'EstadoCorte':     estado,
            'FechaMaxima':     fecha_fmt
        })

    # 4) Vuelca el JSON a fichero
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump({ 'Trabajos': trabajos }, f, ensure_ascii=False, indent=2)

    # 5) Devuelve la misma estructura como respuesta
    return jsonify({ 'Trabajos': trabajos })

# ====================================================================================
# Endpoint para obtener los CNCs de trabajo desde la base de datos
# ====================================================================================
@app.route('/api/CNCsTrabajo/<string:trabajo>/<string:maquina>', methods=['GET'])
def api_CNCsTrabajo(trabajo, maquina):
    # 1) Abre la base de datos
    db_path     = os.path.join(base_dir, 'static', 'BaseDatos_Pruebas', 'Secuenciacion_Trabajos_Emesa.db')
    output_path = os.path.join(base_dir, 'static', 'data', 'CNCsTrabajo.json')
    conn        = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor      = conn.cursor()

    # 2) Ejecuta la consulta (fíjate en la coma tras B.Pedido)
    cursor.execute("""
        SELECT DISTINCT
            A.CNC,
            A.Material,
            A.EspMaterial,
            A.QtyCNCProg,
            A.CodMaterial,
            A.Referencia,
            A.LongReferencia,
            A.AnchoReferencia,
            A.Image,
            A.QtyPiezCNC,
            A.QtyPiezTrab,
            A.CodLinea,
            B.Pedido,
            COALESCE((SELECT SUM(QtyCort) FROM CNCs_Pendientes_Corte_Semana WHERE CNC = A.CNC), 0) AS Cort,
            COALESCE((SELECT TimPend FROM CNCs_Pendientes_Corte_Semana WHERE CNC = A.CNC), 0) AS TPend
        FROM Datos_CNC_Lantek A
        LEFT JOIN Pedidos_Trabajos_Lantek_Semana B ON A.CodLinea = B.CodLinea
        WHERE A.Trabajo = ? AND A.Maquina = ?
        ORDER BY A.CNC
    """, (trabajo, maquina))
    rows = cursor.fetchall()
    conn.close()

    # 3) Agrupa por CNC
    agrupado = {}
    for row in rows:
        cnc = row['CNC']
        if cnc not in agrupado:
            agrupado[cnc] = {
                "CNC": cnc,
                "CantidadCNC": row['QtyCNCProg'],
                "CantidadCortada": row['Cort'],
                "CodigoChapa": row['CodMaterial'],
                "Material": row['Material'],
                "Espesor": row['EspMaterial'],
                "RutaPDF_CNC": r'\\Servidor\pdfsemana\{}'.format(cnc),
                "Tiempo": row['TPend'],
                "Piezas": []
            }

        # Añade la pieza al array de este CNC
        agrupado[cnc]["Piezas"].append({
            "CodLinea": row['CodLinea'],
            "Pieza": row['Referencia'],
            "Largo": row['LongReferencia'],
            "Ancho": row['AnchoReferencia'],
            "RutaPNG_Pieza": row['Image'],
            "CantidadPiezasCNC": row['QtyPiezCNC'],
            "CantidadPiezasTrabajo": row['QtyPiezTrab'],
            "Pedido": row['Pedido']
        })

    # Convierte el dict a lista
    CNCs = list(agrupado.values())

    # 4) Vuelca el JSON a fichero
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump({'CNCs': CNCs}, f, ensure_ascii=False, indent=2)

    # 5) Devuelve la misma estructura como respuesta
    return jsonify({'CNCs': CNCs})


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
# Endpoint para obtener los años en TiemposDecoracionesClinchado
# ====================================================================================
@app.route('/TiemposDecoracionesClinchado_anos', methods=['GET'])
def TiemposDecoracionesClinchado_anos():
    with ConexionODBC(database='Digitalizacion') as conn:
        cursor = conn.cursor()
        cursor.execute("""SELECT año 
                          FROM Vista_Procesos_Tiempos_Decoracion_Clinchado_CABINAS_V2
                          GROUP BY año
                          ORDER BY año DESC
                       """)
        result = cursor.fetchone()

        RolesList = []
        while result:
            RolesList.append(result[0])
            result = cursor.fetchone()

    return jsonify({ 'TiemposDecoracionesClinchado_anos': RolesList })

# ====================================================================================
# Endpoint para obtener las semanas en TiemposDecoracionesClinchado
# ====================================================================================
@app.route('/TiemposDecoracionesClinchado_semanas/<string:ano>', methods=['GET'])
def TiemposDecoracionesClinchado_semanas(ano):
    with ConexionODBC(database='Digitalizacion') as conn:
        cursor = conn.cursor()
        cursor.execute("""SELECT NumSemana 
                          FROM Vista_Procesos_Tiempos_Decoracion_Clinchado_CABINAS_V2
                          WHERE año = ?
                          GROUP BY NumSemana
                          ORDER BY NumSemana DESC
                       """, (ano,))
        result = cursor.fetchone()

        RolesList = []
        while result:
            RolesList.append(result[0])
            result = cursor.fetchone()

    return jsonify({ 'TiemposDecoracionesClinchado_semanas': RolesList })

# ====================================================================================
# Endpoint para obtener los datos en TiemposDecoracionesClinchado
# ====================================================================================
@app.route('/TiemposDecoracionesClinchado_datos/<string:ano>/<string:semana>', methods=['GET'])
def TiemposDecoracionesClinchado_datos(ano, semana):
    with ConexionODBC(servidor='SQLSERVER') as conn:
        cursor = conn.cursor()
        semana_like = f"{semana}%"
        cursor.execute("""
                SELECT T.*
                    FROM (
                    SELECT Q.*,
                    (
                        (
                        TIEMPO_BASE
                        + Q.OPCION_TIRA_LED_ESQUINAS_TRASERAS
                        + Q.OPCION_TIRA_LED_BOTONERA
                        + Q.OPCION_TIRA_LED_ZOCALO_SUPERIOR
                        + Q.OPCION_TIRA_LED_ZOCALO_INFERIOR
                        + Q.OPCION_PASAMANOS
                        + Q.OPCION_PLANCHA_ANTIVIBRATORIA
                        + Q.OPCION_ZOCALOS_CON_TAPA
                        + Q.OPCION_CUBRECANTOS_L_ESPEJO
                        + Q.OPCION_BOTONERA_CON_ILUMINACION
                        + Q.OPCION_RINCONERA
                        + Q.OPCION_PROTECCIONES
                        + Q.OPCION_ENTRECALLES
                        + Q.OPCION_BOTONERA_SIN_ILUMINACION
                        + Q.OPCION_ESPEJO
                        + Q.OPCION_NORMA_NUEVA_CLINCHADO
                        + Q.OPCION_NORMA_NUEVA_DECORACION
                        + Q.OPCION_PELADO_CANTOS
                        + Q.OPCION_UNIONES_ATOR_CAT_1
                        + Q.OPCION_SUELO_PREPARADO
                        + Q.OPCION_SUELO_GOMA
                        + Q.OPCION_SUELO_CERAMICO
                        + Q.OPCION_SUELO_REVESTIMIENTO
                        )
                        * Q.OPCION_UNIONES_ATOR_CAT_2
                    ) AS TIEMPO_TOTAL
                    FROM (
                    SELECT 
                        A.Año,
                        A.NumSemana,
                        A.NumeroPedido,
                        A.CODPIEZA,
                        A.DESCRIPCIONPIEZA,
                        B.MODELO,
                        B.TIPOENVIO,
                        D.GFH,
                        ISNULL((SELECT E.CANTIDAD FROM CODIGOS_ESCANDALLO E WHERE E.CODIGOPADRE = A.CODPIEZA AND E.CODIGOHIJO = D.GFH),0) AS TIEMPO_BASE,
                        CASE
                        WHEN B.INCLUIRTIRASLEDESQUINASTRASERAS = 1 AND A.CodigoPieza = 'C010DECOPANO' THEN
                            ISNULL((SELECT E.CANTIDAD FROM CODIGOS_ESCANDALLO E WHERE E.CODIGOPADRE = 'C010OPC00001' AND E.CODIGOHIJO = D.GFH), 0)
                        ELSE
                            0
                        END AS OPCION_TIRA_LED_ESQUINAS_TRASERAS,
                        CASE 
                        WHEN B.INCLUIRTIRASLEDBOTONERA = 1 AND A.CodigoPieza = 'C010DECOPANO' THEN
                            ISNULL((SELECT E.CANTIDAD FROM CODIGOS_ESCANDALLO E WHERE E.CODIGOPADRE = 'C010OPC00002' AND E.CODIGOHIJO = D.GFH), 0)
                        ELSE
                            0
                        END AS OPCION_TIRA_LED_BOTONERA,
                        CASE
                        WHEN B.INCLUIRTIRASLEDZOCALOSUPERIOR = 1 AND A.CodigoPieza = 'C010DECOPANO' THEN
                            ISNULL((SELECT E.CANTIDAD FROM CODIGOS_ESCANDALLO E WHERE E.CODIGOPADRE = 'C010OPC00003' AND E.CODIGOHIJO = D.GFH), 0)
                        ELSE
                            0
                        END AS OPCION_TIRA_LED_ZOCALO_SUPERIOR,
                        CASE
                        WHEN B.INCLUIRTIRASLEDZOCALOINFERIOR = 1 AND A.CodigoPieza = 'C010DECOPANO' THEN
                            ISNULL((SELECT E.CANTIDAD FROM CODIGOS_ESCANDALLO E WHERE E.CODIGOPADRE = 'C010OPC00004' AND E.CODIGOHIJO = D.GFH), 0)
                        ELSE
                            0
                        END AS OPCION_TIRA_LED_ZOCALO_INFERIOR,
                        CASE
                        WHEN CHARINDEX('der.', A.DESCRIPCIONPIEZA) > 0 AND B.POSICIONPASAMANOS90 = 1 AND A.CodigoPieza = 'C010DECOPANO' THEN
                            ISNULL((SELECT E.CANTIDAD FROM CODIGOS_ESCANDALLO E WHERE E.CODIGOPADRE = 'C010OPC00005' AND E.CODIGOHIJO = D.GFH), 0)
                        WHEN CHARINDEX('posterior', A.DESCRIPCIONPIEZA) > 0 AND B.POSICIONPASAMANOS180 = 1 AND A.CodigoPieza = 'C010DECOPANO' THEN
                            ISNULL((SELECT E.CANTIDAD FROM CODIGOS_ESCANDALLO E WHERE E.CODIGOPADRE = 'C010OPC00005' AND E.CODIGOHIJO = D.GFH), 0)
                        WHEN CHARINDEX('izq.', A.DESCRIPCIONPIEZA) > 0 AND B.POSICIONPASAMANOS270 = 1 AND A.CodigoPieza = 'C010DECOPANO' THEN
                            ISNULL((SELECT E.CANTIDAD FROM CODIGOS_ESCANDALLO E WHERE E.CODIGOPADRE = 'C010OPC00005' AND E.CODIGOHIJO = D.GFH), 0)
                        ELSE 0
                        END AS OPCION_PASAMANOS,
                        CASE
                        WHEN B.PLANCHAANTIVIBRATORIA = 1 AND A.CodigoPieza = 'C010DECOPANO' THEN
                            ISNULL((SELECT E.CANTIDAD FROM CODIGOS_ESCANDALLO E WHERE E.CODIGOPADRE = 'C010OPC00006' AND E.CODIGOHIJO = D.GFH), 0)
                        ELSE
                            0
                        END AS OPCION_PLANCHA_ANTIVIBRATORIA,
                        CASE
                        WHEN (SELECT COUNT(DP_TEMP.NumeroPedido)
                        FROM DESPIECE_PEDIDOS DP_TEMP
                        WHERE DP_TEMP.CODPIEZA IN ('C01042T1XD00', 'C01042T1XX00', 'C01042T40X00') AND DP_TEMP.NumeroPedido=A.NumeroPedido
                        GROUP BY DP_TEMP.NumeroPedido) > 0 AND A.CodigoPieza = 'C010DECOPANO' THEN
                            ISNULL((SELECT E.CANTIDAD FROM CODIGOS_ESCANDALLO E WHERE E.CODIGOPADRE = 'C010OPC00007' AND E.CODIGOHIJO = D.GFH), 0)
                        ELSE 
                            0
                        END AS OPCION_ZOCALOS_CON_TAPA,
                        CASE
                        WHEN (SELECT COUNT(DP_TEMP.NumeroPedido)
                        FROM DESPIECE_PEDIDOS DP_TEMP
                        WHERE DP_TEMP.CODPIEZA IN ('C01042CL0SH4', 'C01042CL0SH5', 'C01042CL0SH9', 'C01042CL0X08', 'C01042CL0X12', 'C01042CU0DXX') AND DP_TEMP.NumeroPedido=A.NumeroPedido
                        GROUP BY DP_TEMP.NumeroPedido) > 0 AND A.CodigoPieza = 'C010DECOPANO' THEN
                            ISNULL((SELECT E.CANTIDAD FROM CODIGOS_ESCANDALLO E WHERE E.CODIGOPADRE = 'C010OPC00008' AND E.CODIGOHIJO = D.GFH), 0)
                        ELSE
                            0
                        END AS OPCION_CUBRECANTOS_L_ESPEJO,
                        CASE
                        WHEN CHARINDEX('der.', A.DESCRIPCIONPIEZA) > 0 AND B.POSICIONBOTONERA90 = 1 AND B.PERFILBOTONERA='ILUMINACION' AND A.CodigoPieza = 'C010DECOPANO' THEN
                            ISNULL((SELECT E.CANTIDAD FROM CODIGOS_ESCANDALLO E WHERE E.CODIGOPADRE = 'C010OPC00009' AND E.CODIGOHIJO = D.GFH), 0)
                        WHEN CHARINDEX('posterior', A.DESCRIPCIONPIEZA) > 0 AND B.POSICIONBOTONERA180 = 1 AND B.PERFILBOTONERA='ILUMINACION' AND A.CodigoPieza = 'C010DECOPANO' THEN
                            ISNULL((SELECT E.CANTIDAD FROM CODIGOS_ESCANDALLO E WHERE E.CODIGOPADRE = 'C010OPC00009' AND E.CODIGOHIJO = D.GFH), 0)
                        WHEN CHARINDEX('izq.', A.DESCRIPCIONPIEZA) > 0 AND B.POSICIONBOTONERA270 = 1 AND B.PERFILBOTONERA='ILUMINACION' AND A.CodigoPieza = 'C010DECOPANO' THEN
                            ISNULL((SELECT E.CANTIDAD FROM CODIGOS_ESCANDALLO E WHERE E.CODIGOPADRE = 'C010OPC00009' AND E.CODIGOHIJO = D.GFH), 0)
                        ELSE
                            0
                        END AS OPCION_BOTONERA_CON_ILUMINACION,
                        CASE
                        WHEN CHARINDEX('der.', A.DESCRIPCIONPIEZA) > 0 AND B.RINCONERA90180 <> '' AND A.CodigoPieza = 'C010DECOPANO' THEN
                            ISNULL((SELECT E.CANTIDAD FROM CODIGOS_ESCANDALLO E WHERE E.CODIGOPADRE = 'C010OPC00010' AND E.CODIGOHIJO = D.GFH), 0)
                        WHEN CHARINDEX('izq.', A.DESCRIPCIONPIEZA) > 0 AND B.RINCONERA180270 <> '' AND A.CodigoPieza = 'C010DECOPANO' THEN
                            ISNULL((SELECT E.CANTIDAD FROM CODIGOS_ESCANDALLO E WHERE E.CODIGOPADRE = 'C010OPC00010' AND E.CODIGOHIJO = D.GFH), 0)
                        ELSE
                            0
                        END AS OPCION_RINCONERA,
                        CASE
                        WHEN (B.PROTECCIONESPOSICIONINFERIOR IS NOT NULL OR B.PROTECCIONESPOSICIONSUPERIOR IS NOT NULL) AND A.CodigoPieza = 'C010DECOPANO' THEN
                            ISNULL((SELECT E.CANTIDAD FROM CODIGOS_ESCANDALLO E WHERE E.CODIGOPADRE = 'C010OPC00011' AND E.CODIGOHIJO = D.GFH), 0)
                        ELSE
                            0
                        END AS OPCION_PROTECCIONES,
                        CASE
                        WHEN B.UNIONPAÑOS = 'ENTRECALLES' AND A.CodigoPieza = 'C010DECOPANO' THEN
                            ISNULL((SELECT E.CANTIDAD FROM CODIGOS_ESCANDALLO E WHERE E.CODIGOPADRE = 'C010OPC00012' AND E.CODIGOHIJO = D.GFH), 0)
                        ELSE
                            0
                        END AS OPCION_ENTRECALLES,
                        CASE
                        WHEN CHARINDEX('der.', A.DESCRIPCIONPIEZA) > 0 AND B.POSICIONBOTONERA90 = 1 AND B.PERFILBOTONERA<>'ILUMINACION' AND A.CodigoPieza = 'C010DECOPANO' THEN
                            ISNULL((SELECT E.CANTIDAD FROM CODIGOS_ESCANDALLO E WHERE E.CODIGOPADRE = 'C010OPC00014' AND E.CODIGOHIJO = D.GFH), 0)
                        WHEN CHARINDEX('posterior', A.DESCRIPCIONPIEZA) > 0 AND B.POSICIONBOTONERA180 = 1 AND B.PERFILBOTONERA<>'ILUMINACION' AND A.CodigoPieza = 'C010DECOPANO' THEN
                            ISNULL((SELECT E.CANTIDAD FROM CODIGOS_ESCANDALLO E WHERE E.CODIGOPADRE = 'C010OPC00014' AND E.CODIGOHIJO = D.GFH), 0)
                        WHEN CHARINDEX('izq.', A.DESCRIPCIONPIEZA) > 0 AND B.POSICIONBOTONERA270 = 1 AND B.PERFILBOTONERA<>'ILUMINACION' AND A.CodigoPieza = 'C010DECOPANO' THEN
                            ISNULL((SELECT E.CANTIDAD FROM CODIGOS_ESCANDALLO E WHERE E.CODIGOPADRE = 'C010OPC00014' AND E.CODIGOHIJO = D.GFH), 0)
                        ELSE
                            0
                        END AS OPCION_BOTONERA_SIN_ILUMINACION,
                        CASE
                        WHEN CHARINDEX('der.', A.DESCRIPCIONPIEZA) > 0 AND B.POSICIONESPEJO90 = 1 AND A.CodigoPieza = 'C010DECOPANO' THEN
                            CASE
                            WHEN B.MODELO = 'IONCONFORT' THEN
                                ISNULL((SELECT E.CANTIDAD FROM CODIGOS_ESCANDALLO E WHERE E.CODIGOPADRE = 'C010OPC00013' AND E.CODIGOHIJO = D.GFH), 0)
                            ELSE
                                ISNULL((SELECT E.CANTIDAD FROM CODIGOS_ESCANDALLO E WHERE E.CODIGOPADRE = 'C010OPC00015' AND E.CODIGOHIJO = D.GFH), 0)
                            END
                        WHEN CHARINDEX('posterior', A.DESCRIPCIONPIEZA) > 0 AND B.POSICIONESPEJO180 = 1 AND A.CodigoPieza = 'C010DECOPANO' THEN
                            CASE
                            WHEN B.MODELO = 'IONCONFORT' THEN
                                ISNULL((SELECT E.CANTIDAD FROM CODIGOS_ESCANDALLO E WHERE E.CODIGOPADRE = 'C010OPC00013' AND E.CODIGOHIJO = D.GFH), 0)
                            ELSE
                                ISNULL((SELECT E.CANTIDAD FROM CODIGOS_ESCANDALLO E WHERE E.CODIGOPADRE = 'C010OPC00015' AND E.CODIGOHIJO = D.GFH), 0)
                            END
                        WHEN CHARINDEX('izq.', A.DESCRIPCIONPIEZA) > 0 AND B.POSICIONESPEJO270 = 1 AND A.CodigoPieza = 'C010DECOPANO' THEN
                            CASE
                            WHEN B.MODELO = 'IONCONFORT' THEN
                                ISNULL((SELECT E.CANTIDAD FROM CODIGOS_ESCANDALLO E WHERE E.CODIGOPADRE = 'C010OPC00013' AND E.CODIGOHIJO = D.GFH), 0)
                            ELSE
                                ISNULL((SELECT E.CANTIDAD FROM CODIGOS_ESCANDALLO E WHERE E.CODIGOPADRE = 'C010OPC00015' AND E.CODIGOHIJO = D.GFH), 0)
                            END
                        ELSE
                            0
                        END AS OPCION_ESPEJO,
                    CASE
                        WHEN C.SUBPRODUCTO = 'CAB EN81-20' AND A.CodigoPieza = 'C010DECOPANO' THEN
                        ISNULL((SELECT E.CANTIDAD FROM CODIGOS_ESCANDALLO E WHERE E.CODIGOPADRE = 'C010OPC00016' AND E.CODIGOHIJO = D.GFH), 0)
                        ELSE
                        0
                    END AS OPCION_NORMA_NUEVA_CLINCHADO,
                    CASE
                        WHEN C.SUBPRODUCTO = 'CAB EN81-20' AND B.MODELO IN ('SD', 'S01', 'I01D', 'CH', 'IONCONFORT') AND A.CodigoPieza = 'C010DECOPANO' THEN
                        ISNULL((SELECT E.CANTIDAD FROM CODIGOS_ESCANDALLO E WHERE E.CODIGOPADRE = 'C010OPC00023' AND E.CODIGOHIJO = D.GFH), 0)
                        ELSE
                        0
                    END AS OPCION_NORMA_NUEVA_DECORACION,
                        CASE
                        WHEN B.MODELO IN ('I01D','S01','IONCONFORT') AND A.CodigoPieza = 'C010DECOPANO' THEN
                            CASE
                            WHEN B.TIPOSKINPLATELATERALIZDO = '006900000000' THEN
                                CASE
                                WHEN C.SUBPRODUCTO <> 'CAB EN81-20' THEN 
                                    ISNULL((SELECT E.CANTIDAD FROM CODIGOS_ESCANDALLO E WHERE E.CODIGOPADRE = 'C010OPC00019' AND E.CODIGOHIJO = D.GFH), 0)
                                ELSE
                                    ISNULL((SELECT E.CANTIDAD FROM CODIGOS_ESCANDALLO E WHERE E.CODIGOPADRE = 'C010OPC00020' AND E.CODIGOHIJO = D.GFH), 0)
                                END
                            ELSE
                                ISNULL((SELECT E.CANTIDAD FROM CODIGOS_ESCANDALLO E WHERE E.CODIGOPADRE = 'C010OPC00018' AND E.CODIGOHIJO = D.GFH), 0)
                            END
                        ELSE
                            0
                        END AS OPCION_PELADO_CANTOS,
                        CASE
                        WHEN B.CABINAEN8171CAT1 = 1 AND A.CodigoPieza = 'C010DECOPANO' THEN
                            ISNULL((SELECT E.CANTIDAD FROM CODIGOS_ESCANDALLO E WHERE E.CODIGOPADRE = 'C010OPC00021' AND E.CODIGOHIJO = D.GFH), 0)
                        ELSE
                            0
                        END AS OPCION_UNIONES_ATOR_CAT_1,
                    CASE
                        WHEN B.CABINAEN8171CAT2 = 1 AND A.CodigoPieza = 'C010DECOPANO' THEN
                        0  -- SI LA OPCION_UNIONES_ATOR_CAT_2 SE CUPLE SE MULTIPLICA POR 0 PARA QUE EL TIEMPO TOTAL SEA 0, ESTAS CABINAS NO VAN CON EL RESTO
                        ELSE
                        1  -- SI LA OPCION_UNIONES_ATOR_CAT_2 NO SE CUPLE SE MULTIPLICA POR 1 PARA QUE EL TIEMPO TOTAL NO SEA 0
                    END AS OPCION_UNIONES_ATOR_CAT_2,
                    CASE
                        WHEN B.COLOCADOSUELO = 0 AND A.CodigoPieza = 'C010MTJESUEL' THEN
                        ISNULL((SELECT E.CANTIDAD FROM CODIGOS_ESCANDALLO E WHERE E.CODIGOPADRE = 'C010OPC00031' AND E.CODIGOHIJO = D.GFH), 0)
                        ELSE
                        0
                    END AS OPCION_SUELO_PREPARADO,
                    CASE
                        WHEN B.COLOCADOSUELO = 1 AND B.SUELO2 IN ('GOMA', 'GOMAANTIDESLIZANTE', 'LINOLEUM') AND A.CodigoPieza = 'C010MTJESUEL' THEN
                        ISNULL((SELECT E.CANTIDAD FROM CODIGOS_ESCANDALLO E WHERE E.CODIGOPADRE = 'C010OPC00032' AND E.CODIGOHIJO = D.GFH), 0)
                        ELSE
                        0
                    END AS OPCION_SUELO_GOMA,
                    CASE
                        WHEN B.COLOCADOSUELO = 1 AND B.SUELO2 IN ('GRANITO', 'SILESTONE') AND A.CodigoPieza = 'C010MTJESUEL' THEN
                        ISNULL((SELECT E.CANTIDAD FROM CODIGOS_ESCANDALLO E WHERE E.CODIGOPADRE = 'C010OPC00033' AND E.CODIGOHIJO = D.GFH), 0)
                        ELSE
                        0
                    END AS OPCION_SUELO_CERAMICO,
                    CASE
                        WHEN B.COLOCADOSUELO = 1 AND B.SUELO2 NOT IN ('GOMA', 'GOMAANTIDESLIZANTE', 'LINOLEUM', 'GRANITO', 'SILESTONE') AND A.CodigoPieza = 'C010MTJESUEL' THEN
                        ISNULL((SELECT E.CANTIDAD FROM CODIGOS_ESCANDALLO E WHERE E.CODIGOPADRE = 'C010OPC00034' AND E.CODIGOHIJO = D.GFH), 0)
                        ELSE
                        0
                    END AS OPCION_SUELO_REVESTIMIENTO

                    FROM DESPIECE_PEDIDOS AS A
                    LEFT OUTER JOIN Pedidos_Productos_Cab AS B ON A.NumeroPedido = B.NUM_PEDIDO
                    LEFT OUTER JOIN Pedidos_Productos AS C ON C.NUM_PEDIDO = B.NUM_PEDIDO
                    CROSS JOIN (
                        SELECT 'GF35MCA00DEC' AS GFH
                        UNION ALL
                        SELECT 'GF35CLI01CLI'
                        UNION ALL
                        SELECT 'GF3500000MTJ'
                    ) AS D
                    WHERE 
                        A.Año = ?
                        AND A.NumSemana LIKE ?
                        AND A.CodigoPieza IN ('C010DECOPANO', 'C010MTJESUEL')
                        AND A.REPROCESADA = 0
                    GROUP BY A.Año, A.NumSemana, A.NumeroPedido, A.CODPIEZA, A.CodigoPieza, A.DESCRIPCIONPIEZA, B.MODELO, B.INCLUIRTIRASLEDBOTONERA, B.COLOCADOSUELO,
                    B.INCLUIRTIRASLEDESQUINASTRASERAS, B.INCLUIRTIRASLEDZOCALOINFERIOR, B.INCLUIRTIRASLEDZOCALOSUPERIOR, B.POSICIONPASAMANOS90, B.SUELO2,
                    B.POSICIONPASAMANOS180, B.POSICIONPASAMANOS270, B.PLANCHAANTIVIBRATORIA, B.POSICIONBOTONERA90,B.POSICIONBOTONERA180, B.TIPOSKINPLATELATERALIZDO,
                    B.POSICIONBOTONERA270, B.PERFILBOTONERA, B.RINCONERA90180, B.RINCONERA180270, B.PROTECCIONESPOSICIONINFERIOR, B.PROTECCIONESPOSICIONSUPERIOR,
                    B.POSICIONESPEJO90, B.POSICIONESPEJO180, B.POSICIONESPEJO270, B.TIPOENVIO, C.SUBPRODUCTO, D.GFH, B.CABINAEN8171CAT1, B.CABINAEN8171CAT2, B.UNIONPAÑOS
                    ) Q
                ) AS T
                WHERE (T.TIEMPO_TOTAL > 0 AND T.OPCION_UNIONES_ATOR_CAT_2 = 1) OR (T.TIEMPO_TOTAL = 0 AND T.OPCION_UNIONES_ATOR_CAT_2 = 0)
                ORDER BY T.Año, T.NumSemana, T.GFH, T.NumeroPedido
                """, (ano, semana_like,))
        columns = [col[0] for col in cursor.description]
        rows = cursor.fetchall()
        data = [dict(zip(columns, row)) for row in rows]
    return jsonify(data)

# ====================================================================================
# EJECUCIÓN DE LA APLICACIÓN
# ====================================================================================
if __name__ == '__main__':
    print(f"API iniciada. Para cerrarla (si el actualizador lo necesita), usa el token: {SHUTDOWN_SECRET_KEY}")
    # Asegúrate que tu .env tiene SHUTDOWN_SECRET_KEY o cámbialo en el código.
    app.run(host='0.0.0.0', port=5000, debug=True) # debug=False en producción si no lo necesitas para el shutdown
    