"""
Gestor de Configuración AMPA - Lanzador Web

Este archivo lanza la interfaz web moderna para gestionar las variables de entorno.

Uso:
    python env_manager_gui.py

Se abrirá automáticamente el navegador en http://localhost:5050
"""

import sys


def main():
    """Lanza el servidor web del gestor de configuración"""
    print("\n" + "=" * 60)
    print("  GESTOR DE CONFIGURACIÓN AMPA - Interfaz Web")
    print("=" * 60)
    print("\n  Iniciando servidor web...")
    print("  Se abrirá automáticamente el navegador.")
    print("  Presiona Ctrl+C para cerrar.\n")
    
    # Importar y ejecutar el servidor web
    try:
        from env_manager_server import run_server
        run_server()
    except ImportError as e:
        print(f"Error: No se encontró env_manager_server.py: {e}")
        print("Asegúrate de que el archivo está en el directorio del proyecto.")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\nServidor detenido por el usuario.")
        sys.exit(0)
    except Exception as e:
        print(f"Error al iniciar el servidor: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
