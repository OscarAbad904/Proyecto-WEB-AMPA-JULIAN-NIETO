import os
import threading
import time
from datetime import datetime, timedelta
import pytz
from flask import Flask
from app.services.user_cleanup_service import cleanup_deactivated_users

_cleanup_thread: threading.Thread | None = None
_cleanup_lock = threading.Lock()

def start_user_cleanup_scheduler(app: Flask) -> None:
    if os.getenv("AMPA_DISABLE_BACKGROUND_JOBS") in {"1", "true", "yes"}:
        return

    # En modo debug, el reloader ejecuta 2 procesos (padre + hijo). Solo arrancar en el hijo.
    if (app.debug or app.config.get("DEBUG")) and os.getenv("WERKZEUG_RUN_MAIN") != "true":
        return

    if os.getenv("FLASK_RUN_FROM_CLI") == "true":
        return

    global _cleanup_thread
    with _cleanup_lock:
        if _cleanup_thread and _cleanup_thread.is_alive():
            return

        def _loop() -> None:
            # Esperar un poco al inicio para no interferir con el arranque
            time.sleep(60)
            while True:
                try:
                    with app.app_context():
                        from app.extensions import db
                        # Cerrar todas las conexiones del pool antes de operar para evitar SSL stale connections
                        db.engine.dispose()
                        try:
                            app.logger.info("Iniciando limpieza de usuarios desactivados...")
                            count = cleanup_deactivated_users()
                            if count > 0:
                                app.logger.info(f"Limpieza completada: {count} usuarios eliminados.")
                            else:
                                app.logger.info("No hay usuarios para eliminar.")
                        finally:
                            db.session.remove()
                    
                    # Ejecutar una vez al día (24 horas)
                    time.sleep(24 * 3600)
                except Exception as exc:
                    app.logger.exception(f"Error en scheduler de limpieza de usuarios: {exc}")
                    time.sleep(3600) # Reintentar en una hora si falla

        _cleanup_thread = threading.Thread(target=_loop, name="user-cleanup-scheduler", daemon=True)
        _cleanup_thread.start()
