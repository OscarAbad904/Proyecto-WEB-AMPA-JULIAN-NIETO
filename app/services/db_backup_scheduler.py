"""
Scheduler simple (sin dependencias) para backups de BD a Drive.

Se ejecuta en un hilo daemon y respeta las variables:
- DB_BACKUP_ENABLED
- DB_BACKUP_TIME
- DB_BACKUP_FREQUENCY
"""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timedelta

import pytz
from flask import Flask

from app.services.db_backup_service import run_db_backup_to_drive

_scheduler_thread: threading.Thread | None = None
_scheduler_lock = threading.Lock()


def _parse_hhmm(value: str) -> tuple[int, int]:
    raw = (value or "").strip()
    if ":" not in raw:
        return 0, 0
    parts = raw.split(":", 1)
    try:
        hour = max(0, min(23, int(parts[0])))
        minute = max(0, min(59, int(parts[1])))
        return hour, minute
    except ValueError:
        return 0, 0


def _compute_next_run(app: Flask, now: datetime) -> datetime:
    tz = pytz.timezone("Europe/Madrid")
    now_tz = now.astimezone(tz)

    hour, minute = _parse_hhmm(app.config.get("DB_BACKUP_TIME") or "00:00")
    base = now_tz.replace(hour=hour, minute=minute, second=0, microsecond=0)

    freq = app.config.get("DB_BACKUP_FREQUENCY", 1)
    every_days = max(1, int(freq or 1))

    if base <= now_tz:
        base += timedelta(days=every_days)
    return base


def start_db_backup_scheduler(app: Flask) -> None:
    if os.getenv("AMPA_DISABLE_BACKGROUND_JOBS") in {"1", "true", "yes"}:
        return

    # En modo debug, el reloader ejecuta 2 procesos (padre + hijo). Solo arrancar en el hijo.
    if (app.debug or app.config.get("DEBUG")) and os.getenv("WERKZEUG_RUN_MAIN") != "true":
        return

    if not str(app.config.get("DB_BACKUP_ENABLED") or "").lower() in {"1", "true", "yes", "on"}:
        return

    if os.getenv("FLASK_RUN_FROM_CLI") == "true":
        return

    global _scheduler_thread
    with _scheduler_lock:
        if _scheduler_thread and _scheduler_thread.is_alive():
            return

        def _loop() -> None:
            # Esperar un poco al inicio para dar tiempo a Gunicorn a forkear workers
            # y evitar que el master mantenga conexiones abiertas heredadas.
            time.sleep(30)
            
            # Comprobación al inicio: si no hay backup hoy, lo lanzamos.
            # Usamos os.getenv("RENDER") para detectar el entorno de producción de Render.
            try:
                is_render = os.getenv("RENDER") == "true"
                is_dev = app.debug or app.config.get("ENV") == "development"

                if is_render or not is_dev:
                    with app.app_context():
                        from app.extensions import db
                        # Limpiar conexiones heredadas antes de la primera consulta
                        db.engine.dispose()
                        
                        from app.services.db_backup_service import check_if_backup_exists_for_today
                        if not check_if_backup_exists_for_today():
                            app.logger.info("No se encontró backup de hoy al iniciar. Ejecutando backup ahora...")
                            result = run_db_backup_to_drive(force=True)
                            if result.ok:
                                app.logger.info("Backup de inicio completado: %s", result.message)
                            else:
                                app.logger.warning("Fallo en backup de inicio: %s", result.message)
                        else:
                            app.logger.info("Backup de hoy ya existe en Drive. Omitiendo backup de inicio.")
                else:
                    app.logger.info("Modo desarrollo detectado (debug=%s, env=%s). Omitiendo comprobación de backup al inicio.", app.debug, app.config.get("ENV"))
            except Exception as exc:  # noqa: BLE001
                app.logger.exception("Error en comprobación de backup al iniciar: %s", exc)

            while True:
                try:
                    now = datetime.now(tz=pytz.UTC)
                    next_run = _compute_next_run(app, now)
                    sleep_seconds = max(1.0, (next_run - now.astimezone(next_run.tzinfo)).total_seconds())
                    freq = app.config.get("DB_BACKUP_FREQUENCY", 1)
                    app.logger.info("Siguiente backup BD programado: %s (Frecuencia: cada %s días)", next_run.isoformat(), freq)
                    time.sleep(sleep_seconds)
                    with app.app_context():
                        from app.extensions import db
                        # Cerrar todas las conexiones del pool antes de operar
                        db.engine.dispose()
                        result = run_db_backup_to_drive(force=False)
                        level = app.logger.info if result.ok else app.logger.warning
                        level("Backup BD -> Drive: %s", result.message)
                except Exception as exc:  # noqa: BLE001
                    app.logger.exception("Error en scheduler de backup BD: %s", exc)
                    time.sleep(60)

        _scheduler_thread = threading.Thread(target=_loop, name="db-backup-scheduler", daemon=True)
        _scheduler_thread.start()
