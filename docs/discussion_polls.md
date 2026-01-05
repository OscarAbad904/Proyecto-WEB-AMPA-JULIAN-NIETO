# Votaciones de discusion

Resumen operativo de las votaciones multiples asociadas a discusiones de comisiones/proyectos.

## Auto-cierre
- Scheduler: `app/services/discussion_poll_scheduler.py` (arranca desde `app/__init__.py`).
- Intervalo: `DISCUSSION_POLL_CLOSE_INTERVAL` (segundos), por defecto 60, minimo 15.
- Regla: cierra votaciones con `end_at <= now`, marca `status=finalizada` y `closed_at`.
- Idempotencia: solo transiciona si sigue en `activa` y evita duplicar emails usando `result_notified_at`.

## Votacion NULA
- Significa que la votacion queda anulada y no admite mas votos.
- Se registra con `status=nula`, `nulled_at`, `nulled_by`.
- Es la unica accion de modificacion permitida tras crearla.

## Abstenciones
- Formula: `abstenciones = miembros_activos - (votos_a_favor + votos_en_contra)`.
- Miembros activos: se calculan por comision en el momento del conteo.

## Correos automaticos
- Invitacion: al crear la votacion si `notify_enabled` esta activo.
- Resultado: al cierre automatico si `notify_enabled` esta activo.
- Anulacion: al marcar como nula si `notify_enabled` esta activo.
- Destinatarios: miembros activos de la comision (tambien para proyectos).
- Contenido: siempre anonimo (solo recuentos, sin nombres de votantes).
