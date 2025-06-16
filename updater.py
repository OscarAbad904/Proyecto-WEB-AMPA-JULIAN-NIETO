import os
import shutil
import subprocess
import time
import requests # Necesitarás instalarlo: pip install requests
from dotenv import load_dotenv
import sys
import logging

# Configuración básica del logger
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Cargar variables de entorno (si las usas para configuración)
load_dotenv()

# --- CONFIGURACIÓN ---
# Detectar si estamos en un ejecutable PyInstaller
if getattr(sys, 'frozen', False):
    # PyInstaller: sys.executable es la ruta al .exe, normalmente en la carpeta real
    API_DIR = os.path.dirname(os.path.abspath(sys.executable))
    logging.info(f"Detectado entorno PyInstaller. API_DIR ajustado a: {API_DIR}")
else:
    # Script normal
    API_DIR = os.path.dirname(os.path.abspath(__file__))
    logging.info(f"Entorno script normal. API_DIR: {API_DIR}")

API_EXE_NAME = "app.exe"
API_EXE_PATH = os.path.join(API_DIR, API_EXE_NAME)
UPDATE_SOURCE_DIR = os.path.join(API_DIR, "update")
NEW_API_EXE_NAME = "app.exe"
NEW_API_EXE_PATH = os.path.join(UPDATE_SOURCE_DIR, NEW_API_EXE_NAME)

# Configuración para el cierre de la API
API_SHUTDOWN_URL = "http://localhost:5000/shutdown_api" # Asegúrate que el puerto es correcto
# ESTA CLAVE DEBE SER LA MISMA QUE EN TU API FLASK
SHUTDOWN_SECRET_KEY = os.getenv("SHUTDOWN_SECRET_KEY_UPDATER", "Prueba1234")

BACKUP_DIR = os.path.join(API_DIR, "backup_api")
MAX_BACKUPS = 5 # Cuántas versiones antiguas guardar

# --- FUNCIONES AUXILIARES ---

def log_message(message):
    logging.info(message)

def is_api_running():
    """Verifica si el proceso de la API está en ejecución."""
    try:
        # tasklist es específico de Windows. Para Linux, usarías 'ps aux | grep'
        output = subprocess.check_output(
            f'tasklist /FI "IMAGENAME eq {API_EXE_NAME}"', shell=True
        ).decode(errors='ignore')  # <-- Cambiado aquí
        return API_EXE_NAME.lower() in output.lower()
    except subprocess.CalledProcessError:
        # Esto sucede si el proceso no se encuentra, tasklist devuelve un código de error.
        return False
    except Exception as e:
        logging.info(f"Error verificando si la API está corriendo: {e}")
        return False # Asumir que no está corriendo en caso de error

def stop_api_gracefully():
    logging.info("Intentando detener la API de forma controlada...")
    if not is_api_running():
        logging.info("La API no parece estar en ejecución.")
        return True
    try:
        response = requests.post(f"{API_SHUTDOWN_URL}?token={SHUTDOWN_SECRET_KEY}", timeout=10)
        if response.status_code == 200:
            logging.info("Solicitud de cierre enviada a la API. Esperando que termine...")
            # Esperar un tiempo para que la API se cierre
            for _ in range(20): # Esperar hasta 20 segundos (20 * 1s)
                time.sleep(1)
                if not is_api_running():
                    logging.info("API detenida correctamente.")
                    return True
            logging.info("La API no se detuvo a tiempo después de la solicitud de cierre.")
            return False
        else:
            logging.info(f"Error al solicitar el cierre de la API: {response.status_code} - {response.text}")
            return False
    except requests.exceptions.RequestException as e:
        logging.info(f"No se pudo conectar a la API para el cierre: {e}")
        return False

def stop_api_forcefully():
    logging.info("Intentando detener la API forzosamente (taskkill)...")
    if not is_api_running():
        logging.info("La API no parece estar en ejecución (verificado antes de taskkill).")
        return True
    try:
        # /F para forzar, /IM para nombre de imagen
        subprocess.run(f"taskkill /F /IM {API_EXE_NAME}", check=True, shell=True, capture_output=True)
        logging.info("Comando taskkill ejecutado. Verificando...")
        time.sleep(2) # Dar tiempo a que el proceso muera
        if not is_api_running():
            logging.info("API detenida forzosamente.")
            return True
        else:
            logging.info("Falló el intento de detener la API forzosamente.")
            return False
    except subprocess.CalledProcessError as e:
        # Si taskkill dice "proceso no encontrado", es un éxito para nosotros.
        if "no se encontró" in e.stderr.decode(errors='ignore').lower() or \
           "not found" in e.stderr.decode(errors='ignore').lower():
            logging.info("API no encontrada por taskkill (probablemente ya detenida).")
            return True
        logging.info(f"Error al ejecutar taskkill: {e.stderr.decode(errors='ignore')}")
        return False
    except Exception as e:
        logging.info(f"Excepción durante taskkill: {e}")
        return False

def backup_current_api():
    if not os.path.exists(API_EXE_PATH):
        logging.info("No se encontró el .exe actual de la API para hacer backup. Omitiendo.")
        return

    if not os.path.exists(BACKUP_DIR):
        os.makedirs(BACKUP_DIR)

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    backup_name = f"{os.path.splitext(API_EXE_NAME)[0]}_backup_{timestamp}{os.path.splitext(API_EXE_NAME)[1]}"
    backup_path = os.path.join(BACKUP_DIR, backup_name)

    try:
        shutil.copy2(API_EXE_PATH, backup_path)
        logging.info(f"Backup de la API actual creado en: {backup_path}")

        # Limpiar backups antiguos
        backups = sorted(
            [os.path.join(BACKUP_DIR, f) for f in os.listdir(BACKUP_DIR) if f.startswith(os.path.splitext(API_EXE_NAME)[0])],
            key=os.path.getmtime
        )
        while len(backups) > MAX_BACKUPS:
            old_backup = backups.pop(0)
            os.remove(old_backup)
            logging.info(f"Backup antiguo eliminado: {old_backup}")

    except Exception as e:
        logging.info(f"Error al crear backup de la API: {e}")


def replace_api_exe():
    logging.info(f"Reemplazando {API_EXE_PATH} con {NEW_API_EXE_PATH}")
    try:
        # Evitar reemplazarse a sí mismo si el updater es app.exe
        if os.path.abspath(sys.executable) == os.path.abspath(API_EXE_PATH):
            logging.info("No se puede reemplazar el ejecutable mientras está en uso por el updater. Finaliza el updater y ejecuta la actualización manualmente.")
            return False

        # Si el API_EXE_PATH aún existe (a pesar de los intentos de detener), intentar eliminarlo
        if os.path.exists(API_EXE_PATH):
            logging.info(f"Eliminando .exe antiguo: {API_EXE_PATH}")
            os.remove(API_EXE_PATH) # Puede fallar si el proceso sigue bloqueando el archivo
            time.sleep(0.5) # Pequeña pausa

        shutil.copy2(NEW_API_EXE_PATH, API_EXE_PATH)
        logging.info("Archivo .exe de la API reemplazado con la nueva versión.")
        return True
    except PermissionError as e:
        if hasattr(e, 'winerror') and e.winerror == 5:
            logging.info(f"Error al reemplazar el .exe de la API: Acceso denegado (WinError 5). ¿Estás intentando actualizar el updater mientras está en ejecución? Detén el updater y prueba de nuevo.")
        else:
            logging.info(f"Error al reemplazar el .exe de la API: {e}")
        logging.info("Verifique que la API (o el updater) esté completamente detenida y que el archivo no esté bloqueado.")
        return False
    except Exception as e:
        logging.info(f"Error al reemplazar el .exe de la API: {e}")
        logging.info("Verifique que la API esté completamente detenida y que el archivo no esté bloqueado.")
        return False

def start_api():
    logging.info(f"Iniciando la nueva versión de la API desde: {API_EXE_PATH}")
    try:
        # Usar Popen para iniciar en segundo plano y no bloquear el updater
        # El `creationflags=subprocess.CREATE_NEW_CONSOLE` es opcional si quieres que la API
        # se ejecute en su propia ventana de consola (visible).
        # Si tu .exe es una aplicación de ventana (no consola), esto no es necesario o puedes usar DETACHED_PROCESS.
        # Para una aplicación de consola que quieres que corra en segundo plano sin ventana visible,
        # podrías necesitar herramientas adicionales o empaquetar tu .exe como servicio.
        # Por ahora, esto la iniciará.
        subprocess.Popen([API_EXE_PATH], cwd=API_DIR) # cwd es importante si tu api busca archivos relativos
        time.sleep(5) # Dar tiempo a que inicie
        if is_api_running():
            logging.info("API iniciada correctamente.")
            return True
        else:
            logging.info("La API no parece haberse iniciado después del comando de arranque.")
            return False
    except Exception as e:
        logging.info(f"Error al iniciar la API: {e}")
        return False

def cleanup_update_source():
    logging.info(f"Limpiando archivo de actualización: {NEW_API_EXE_PATH}")
    try:
        if os.path.exists(NEW_API_EXE_PATH):
            os.remove(NEW_API_EXE_PATH)
            logging.info("Archivo de origen de actualización eliminado.")
    except Exception as e:
        logging.info(f"Error al eliminar el archivo de origen de actualización: {e}")

# --- LÓGICA PRINCIPAL DEL ACTUALIZADOR ---
def main_updater_logic():
    logging.info("=== Iniciando ciclo de actualización ===")
    logging.info(f"Ruta UPDATE_SOURCE_DIR: {UPDATE_SOURCE_DIR}")
    logging.info(f"Ruta NEW_API_EXE_PATH: {NEW_API_EXE_PATH}")

    if not os.path.exists(NEW_API_EXE_PATH):
        logging.info(f"No se encontró una nueva versión en: {NEW_API_EXE_PATH}. No se requiere actualización.")
        if os.path.exists(UPDATE_SOURCE_DIR):
            logging.info(f"Contenido de UPDATE_SOURCE_DIR: {os.listdir(UPDATE_SOURCE_DIR)}")
        else:
            logging.info(f"La carpeta UPDATE_SOURCE_DIR no existe: {UPDATE_SOURCE_DIR}")
        return

    logging.info(f"Nueva versión detectada: {NEW_API_EXE_PATH}")

    # 1. Detener la API
    api_stopped = stop_api_gracefully()
    if not api_stopped:
        logging.info("El cierre controlado falló. Intentando cierre forzoso...")
        api_stopped = stop_api_forcefully()

    if not api_stopped:
        logging.info("¡ERROR CRÍTICO! No se pudo detener la API. Abortando actualización.")
        return

    logging.info("API detenida. Procediendo con la actualización.")

    # 2. Hacer backup de la versión actual (antes de reemplazar)
    backup_current_api()

    # 3. Reemplazar el .exe
    if not replace_api_exe():
        logging.info("¡ERROR CRÍTICO! No se pudo reemplazar el .exe de la API. Intentar restaurar backup si es posible o iniciar manualmente.")
        return

    # 4. Limpiar el archivo de origen de la actualización inmediatamente después de reemplazar
    cleanup_update_source()

    # 5. Iniciar la nueva API
    if not start_api():
        logging.info("¡ERROR CRÍTICO! No se pudo iniciar la nueva versión de la API.")
        logging.info("Revise los logs de la API si es posible. Podría ser necesario revertir manualmente al backup.")
        return

    logging.info("=== Proceso de actualización completado exitosamente ===")

if __name__ == "__main__":
    # Validar que SHUTDOWN_SECRET_KEY no sea el valor por defecto si se está usando
    if SHUTDOWN_SECRET_KEY == "tu_clave_secreta_para_shutdown":
        logging.info("ADVERTENCIA: Estás usando la SHUTDOWN_SECRET_KEY por defecto. ¡Cámbiala por seguridad!")

    logging.info(f"Updater iniciado. Vigilando la carpeta '{UPDATE_SOURCE_DIR}' para el archivo '{NEW_API_EXE_NAME}'.")
    logging.info(f"Revisará cada {60} segundos. Presiona Ctrl+C para detener.")
    try:
        while True:
            main_updater_logic()
            # logging.info(f"Esperando {CHECK_INTERVAL_SECONDS} segundos para la próxima revisión...")
            time.sleep(60)
    except KeyboardInterrupt:
        logging.info("Updater detenido por el usuario (Ctrl+C).")
    except Exception as e:
        logging.info(f"Error inesperado en el bucle principal del updater: {e}")
    finally:
        logging.info("Updater finalizado.")
        