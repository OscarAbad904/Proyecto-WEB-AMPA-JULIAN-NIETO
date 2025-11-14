"""Utilidad mínima para abrir conexiones ODBC reutilizando credenciales locales."""

from config import DB_USER, DB_PASSWORD
import pyodbc
import socket
import os


class ConexionODBC:
    """Maneja la conexión a una base de datos externa via ODBC (ej: SQL Server)."""

    def __init__(self, database=None, servidor='EMEBIDWH', application_name='Secuenciacion_Corte'):
        """Configura driver, servidor y base de datos a utilizar.

        Aplica overrides desde variables de entorno `ODBC_DRIVER` y `ODBC_SERVER`.
        """
        try:
            hostname = socket.gethostname()

            # Configuración que te funcionaba antes
            if hostname == 'PortatilOscar':
                driver = 'ODBC Driver 17 for SQL Server'
                servidor = 'localhost\\EMEBIDWH'
            else:
                driver = 'SQL Server'

            # Overrides opcionales por variables de entorno
            self.driver = os.getenv('ODBC_DRIVER', driver)
            self.server = os.getenv('ODBC_SERVER', servidor)
            self.database = database
            app_name = os.getenv('ODBC_APP_NAME', application_name)
            self.application_name = app_name.strip() if app_name else None
            self.conn = None

        except Exception as e:
            print(f"Error en ConexionODBC / __init__: {str(e)}")

    def __enter__(self):
        """Abre la conexión y la devuelve para su uso en un contexto `with`."""
        try:
            # Construir cadena de conexión ODBC y abrir conexión
            conn_parts = [
                f"DRIVER={{{self.driver}}}",
                f"SERVER={self.server}",
            ]

            if self.server == 'EMEBIDWH':
                if self.database:
                    conn_parts.append(f"DATABASE={self.database}")
                conn_parts.extend([
                    f"UID={DB_USER}",
                    f"PWD={DB_PASSWORD}",
                    "Trusted_Connection=no",
                ])
            else:
                conn_parts.append("Trusted_Connection=yes")
                if self.database:
                    conn_parts.append(f"DATABASE={self.database}")

            if self.application_name:
                # Permite identificar la app en herramientas como SQL Server Management Studio
                conn_parts.append(f"APP={self.application_name}")

            conn_str = ';'.join(conn_parts) + ';'

            self.conn = pyodbc.connect(conn_str)
            return self.conn
        except Exception as e:
            print(f"Error en ConexionODBC / __enter__: {str(e)}")

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Cierra la conexión al salir del contexto, ignorando errores."""
        try:
            # Cerrar conexión al salir del contexto
            if self.conn:
                self.conn.close()
        except Exception as e:
            print(f"Error en ConexionODBC / __exit__: {str(e)}")
