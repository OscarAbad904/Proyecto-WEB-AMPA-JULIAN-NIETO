"""Utilidad minima para abrir conexiones ODBC reutilizando credenciales locales."""

import os
import pyodbc

from config import DB_USER, DB_PASSWORD


class ConexionODBC:
    """Maneja la conexion a una base de datos externa via ODBC (ej: SQL Server)."""

    def __init__(self, database="AMPA_JNT", servidor=r'localhost\EMEBIDWH', application_name='Secuenciacion_Corte'):
        """Configura driver, servidor y base de datos a utilizar.

        Aplica overrides desde variables de entorno `ODBC_DRIVER`, `ODBC_SERVER` y `ODBC_APP_NAME`.
        """
        try:
            driver = 'ODBC Driver 17 for SQL Server'

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
        """Abre la conexion y la devuelve para su uso en un contexto `with`."""
        try:
            # Construir cadena de conexion ODBC y abrir conexion
            conn_parts = [
                f"DRIVER={{{self.driver}}}",
                f"SERVER={self.server}",
                "TrustServerCertificate=yes",
            ]

            if self.database:
                conn_parts.append(f"DATABASE={self.database}")

            # Si hay credenciales, usamos autenticacion SQL; si no, intentamos Trusted_Connection
            if DB_USER and DB_PASSWORD:
                conn_parts.extend([
                    f"UID={DB_USER}",
                    f"PWD={DB_PASSWORD}",
                    "Trusted_Connection=no",
                ])
            else:
                conn_parts.append("Trusted_Connection=yes")

            if self.application_name:
                # Permite identificar la app en herramientas como SQL Server Management Studio
                conn_parts.append(f"APP={self.application_name}")

            conn_str = ';'.join(conn_parts) + ';'

            self.conn = pyodbc.connect(conn_str)
            return self.conn
        except Exception as e:
            print(f"Error en ConexionODBC / __enter__: {str(e)}")

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Cierra la conexion al salir del contexto, ignorando errores."""
        try:
            if self.conn:
                self.conn.close()
        except Exception as e:
            print(f"Error en ConexionODBC / __exit__: {str(e)}")
