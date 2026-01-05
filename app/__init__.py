import os
import time
from flask import Flask
from dotenv import load_dotenv
from datetime import datetime

from config import config_by_name, ROOT_PATH
from app.extensions import db, migrate, login_manager, csrf
from app.routes.public import public_bp
from app.routes.members import members_bp
from app.routes.admin import admin_bp
from app.routes.api import api_bp
from app.routes.style import style_bp
from app.models import User, user_is_privileged
from app.models import Permission
from app.forms import LoginForm
from app.commands import register_commands
from app.services.permission_registry import ensure_roles_and_permissions
from app.services.db_backup_scheduler import start_db_backup_scheduler
from app.services.user_cleanup_scheduler import start_user_cleanup_scheduler
from app.services.discussion_poll_scheduler import start_discussion_poll_scheduler


def _is_werkzeug_reloader_child(app: Flask) -> bool:
    """True si estamos en el proceso hijo del reloader de Werkzeug.

    En modo debug, Flask arranca 2 procesos (padre watcher + hijo servidor).
    Queremos ejecutar tareas de arranque (sync estilo, schedulers) solo en el hijo.
    """
    debug_enabled = bool(app.config.get("DEBUG") or app.debug)
    if not debug_enabled:
        return True
    return os.getenv("WERKZEUG_RUN_MAIN") == "true"


def create_app(config_name: str | None = None) -> Flask:
    load_dotenv(ROOT_PATH / ".env", override=True)
    env = config_name or os.getenv("FLASK_ENV", "development")
    config = config_by_name.get(env, config_by_name["development"])

    app = Flask(
        __name__,
        template_folder=str(ROOT_PATH / "templates"),
        static_folder=str(ROOT_PATH / "assets"),
    )
    app.config.from_object(config)
    app.config["ENV"] = env
    config.init_app(app)
    app.config.from_mapping({"ROOT_PATH": str(ROOT_PATH)})

    register_extensions(app)
    register_blueprints(app)
    register_context(app)
    register_guards(app)
    register_commands(app)
    
    @app.errorhandler(400)
    def handle_bad_request(e):
        from flask import request, jsonify
        app.logger.error(f"400 Bad Request: {e.description if hasattr(e, 'description') else e}")
        if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"ok": False, "message": f"Solicitud incorrecta: {e.description if hasattr(e, 'description') else 'Error de seguridad (CSRF).'}"}), 400
        return e

    @app.errorhandler(500)
    def handle_server_error(e):
        from flask import request, jsonify
        if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"ok": False, "message": "Error interno del servidor al procesar el registro."}), 500
        return e

    @app.route("/favicon.ico")
    def favicon():
        return app.send_static_file("favicon.png")
    with app.app_context():
        try:
            ensure_roles_and_permissions()
            # Sincronizar assets del estilo activo a rutas fijas en /assets.
            # En modo debug con reloader, esto se ejecuta dos veces (padre + hijo),
            # así que lo limitamos al proceso hijo.
            if os.getenv("FLASK_RUN_FROM_CLI") != "true" and _is_werkzeug_reloader_child(app):
                # Además, la propia sincronización puede tocar archivos y disparar un reinicio
                # inmediato del reloader. Para evitar doble log/ejecución, aplicamos un lock
                # de ventana corta SOLO en debug.
                should_sync_style = True
                if app.debug:
                    try:
                        lock_path = ROOT_PATH / "cache" / "style_sync_boot.lock"
                        lock_path.parent.mkdir(parents=True, exist_ok=True)
                        if lock_path.exists():
                            age = time.time() - lock_path.stat().st_mtime
                            if age < 20:
                                should_sync_style = False
                        if should_sync_style:
                            lock_path.write_text(str(time.time()), encoding="utf-8")
                    except Exception:
                        # Si falla el lock, no bloqueamos el arranque.
                        should_sync_style = True

                if should_sync_style:
                    from app.services.style_service import sync_active_style_to_static

                    app.logger.info("Sincronizando estilo activo al iniciar...")
                    result = sync_active_style_to_static()
                    copied_count = len(result.get("copied") or [])
                    errors = result.get("errors") or []
                    app.logger.info(
                        "Sincronización de estilo completada: ok=%s style=%s copied=%s errors=%s",
                        bool(result.get("ok")),
                        result.get("style"),
                        copied_count,
                        len(errors),
                    )
                    if errors:
                        app.logger.warning("Errores durante sincronización de estilo: %s", errors)
            
            # Liberar conexiones tras la inicialización para evitar problemas de SSL tras fork/arranque
            db.engine.dispose()
        except Exception as exc:  # noqa: BLE001
            db.session.rollback()
            app.logger.exception("No se pudieron sincronizar los permisos base", exc_info=exc)

    # En modo debug con reloader, arrancar jobs solo en el proceso hijo
    if _is_werkzeug_reloader_child(app):
        start_db_backup_scheduler(app)
        start_user_cleanup_scheduler(app)
        start_discussion_poll_scheduler(app)

    return app


def register_extensions(app: Flask) -> None:
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)

    login_manager.login_view = "members.login"
    login_manager.login_message_category = "warning"
    
    @login_manager.user_loader
    def load_user(user_id: str):
        return User.query.get(int(user_id))


def register_blueprints(app: Flask) -> None:
    app.register_blueprint(public_bp)
    app.register_blueprint(members_bp, url_prefix="/socios")
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(api_bp, url_prefix="/api")
    app.register_blueprint(style_bp)


def register_context(app: Flask) -> None:
    @app.context_processor
    def inject_globals():
        from flask_login import current_user
        from flask import url_for, current_app
        from app.services.style_service import (
            get_active_style_name, 
            get_active_style_version,
            ensure_active_style_synced
        )

        # Asegurar que el estilo activo (posiblemente por programación) esté sincronizado
        ensure_active_style_synced()

        # URLs de estilo (rutas fijas en /assets; el servidor sincroniza desde Drive al arrancar y al activar)
        active_style_name = get_active_style_name()
        style_version = get_active_style_version()
        style_urls = {
            "style_css": url_for("static", filename="css/style.css", v=style_version),
            "logo_header": url_for("static", filename="images/current/Logo_AMPA_64x64.png", v=style_version),
            "logo_hero": url_for("static", filename="images/current/Logo_AMPA_400x400.png", v=style_version),
            "placeholder": url_for("static", filename="images/current/Logo_AMPA.png", v=style_version),
            "active_style": active_style_name,
        }

        public_view_posts = Permission.is_key_public("manage_posts") or Permission.is_key_public("view_posts")
        public_view_events = Permission.is_key_public("manage_events") or Permission.is_key_public("view_events")
        public_view_documents = Permission.is_key_public("manage_documents") or Permission.is_key_public("view_documents")
        public_view_register = True
        if Permission.supports_public_flag():
            try:
                value = db.session.query(Permission.is_public).filter_by(key="public_registration").scalar()
                public_view_register = True if value is None else bool(value)
            except Exception:
                public_view_register = True
        can_manage_members = current_user.is_authenticated and (
            current_user.has_permission("manage_members") or user_is_privileged(current_user)
        )
        can_view_private_area = current_user.is_authenticated and (
            getattr(current_user, "registration_approved", False)
            and current_user.has_permission("view_private_area")
        )
        can_view_posts = public_view_posts or (current_user.is_authenticated and (
            current_user.has_permission("manage_posts")
            or current_user.has_permission("view_posts")
            or user_is_privileged(current_user)
        ))
        can_manage_posts = current_user.is_authenticated and (
            current_user.has_permission("manage_posts") or user_is_privileged(current_user)
        )
        can_view_events = public_view_events or (current_user.is_authenticated and (
            current_user.has_permission("manage_events")
            or current_user.has_permission("view_events")
            or user_is_privileged(current_user)
        ))
        has_commission_membership = False
        if current_user.is_authenticated and getattr(current_user, "registration_approved", False):
            from app.models import Commission, CommissionMembership

            has_commission_membership = (
                CommissionMembership.query.filter_by(user_id=current_user.id, is_active=True)
                .join(Commission)
                .filter(Commission.is_active.is_(True))
                .first()
                is not None
            )
        can_view_private_calendar = can_view_private_area and (
            has_commission_membership
            or current_user.has_permission("view_private_calendar")
        )
        # El calendario publico consume eventos; el privado depende de pertenencia o permiso.
        can_view_calendar = can_view_events or can_view_private_calendar
        calendar_href = (
            url_for("members.calendar")
            if can_view_private_calendar
            else url_for("public.calendario")
        )
        can_manage_events = current_user.is_authenticated and (
            current_user.has_permission("manage_events") or user_is_privileged(current_user)
        )
        can_view_documents = public_view_documents or (current_user.is_authenticated and (
            current_user.has_permission("manage_documents")
            or current_user.has_permission("view_documents")
            or user_is_privileged(current_user)
        ))
        can_view_commissions_admin = current_user.is_authenticated and (
            current_user.has_permission("manage_commissions") or user_is_privileged(current_user)
        )
        can_view_commissions_all = current_user.is_authenticated and (
            current_user.has_permission("view_commissions")
            or can_view_commissions_admin
        )
        can_view_commissions = current_user.is_authenticated and (
            can_view_commissions_all or has_commission_membership
        )
        commissions_href = (
            url_for("admin.commissions_index")
            if can_view_commissions_admin
            else url_for("members.commissions")
        )
        can_manage_commissions = current_user.is_authenticated and (
            current_user.has_permission("manage_commissions")
        )
        can_manage_permissions = (
            current_user.is_authenticated
            and (
                current_user.has_permission("manage_permissions")
                or current_user.has_permission("view_permissions")
                or user_is_privileged(current_user)
            )
        )
        can_manage_styles = (
            current_user.is_authenticated
            and (
                current_user.has_permission("manage_styles")
                or current_user.has_permission("view_styles")
                or user_is_privileged(current_user)
            )
        )

        suggestions_forum_enabled = bool(current_app.config.get("SUGGESTIONS_FORUM_ENABLED", False))
        return {
            "current_year": datetime.utcnow().year,
            "header_login_form": LoginForm(),
            "can_manage_members": can_manage_members,
            "can_view_posts": can_view_posts,
            "can_manage_posts": can_manage_posts,
            "can_view_events": can_view_events,
            "can_view_calendar": can_view_calendar,
            "can_view_private_calendar": can_view_private_calendar,
            "can_view_private_area": can_view_private_area,
            "calendar_href": calendar_href,
            "can_manage_events": can_manage_events,
            "can_view_documents": can_view_documents,
            "can_view_commissions": can_view_commissions,
            "commissions_href": commissions_href,
            "can_manage_commissions": can_manage_commissions,
            "can_manage_permissions": can_manage_permissions,
            "can_manage_styles": can_manage_styles,
            "can_view_register": public_view_register,
            "style_urls": style_urls,
            "suggestions_forum_enabled": suggestions_forum_enabled,
        }


def register_guards(app: Flask) -> None:
    @app.before_request
    def enforce_account_status():
        from flask import request, redirect, url_for, flash, jsonify
        from flask_login import current_user, logout_user

        if not current_user.is_authenticated:
            return None

        # Restringir acceso solo a áreas privadas (socios/admin) y APIs privadas.
        if request.blueprint not in {"members", "admin", "api"}:
            return None

        endpoint = request.endpoint or ""
        allowed = {
            "members.login",
            "members.logout",
            "members.register",
            "members.recuperar",
            "members.mi_cuenta",
            "public.verify_email",
            "public.resend_verification",
            "public.set_password",
            "api.status",
            "api.publicaciones",
            "api.calendario_eventos",
        }
        if endpoint in allowed:
            return None

        if getattr(current_user, "deleted_at", None):
            logout_user()
            if request.blueprint == "api":
                return jsonify({"ok": False, "error": "Cuenta eliminada"}), 403
            flash("Tu cuenta ha sido eliminada.", "danger")
            return redirect(url_for("members.login"))

        if not getattr(current_user, "is_active", True):
            logout_user()
            if request.blueprint == "api":
                return jsonify({"ok": False, "error": "Cuenta desactivada"}), 403
            flash("Tu cuenta está desactivada.", "danger")
            return redirect(url_for("members.login"))

        if not getattr(current_user, "email_verified", False):
            logout_user()
            if request.blueprint == "api":
                return jsonify({"ok": False, "error": "Correo no verificado"}), 403
            flash("Debes verificar tu correo antes de acceder.", "warning")
            return redirect(url_for("members.login"))

        if not getattr(current_user, "registration_approved", False):
            if request.blueprint == "api":
                return jsonify({"ok": False, "error": "Registro pendiente de aprobación"}), 403
            flash("Tu alta está pendiente de aprobación. Solo puedes acceder a tu perfil.", "info")
            return redirect(url_for("public.home"))

        if request.blueprint == "members":
            private_area_exempt = {
                "members.login",
                "members.logout",
                "members.register",
                "members.recuperar",
            }
            path = request.path or ""
            is_commission_endpoint = (
                (
                    bool(endpoint)
                    and (
                        endpoint.startswith("members.commission")
                        or endpoint.startswith("members.project_")
                    )
                )
                or path.startswith("/socios/comisiones")
            )
            is_scoped_discussion_endpoint = False
            if endpoint in {
                "members.detalle_sugerencia",
                "members.comentar_sugerencia",
                "members.votar_sugerencia",
                "members.discussion_polls",
                "members.votar_discussion_poll",
                "members.anular_discussion_poll",
                "members.eliminar_comentario",
                "members.editar_comentario",
            }:
                try:
                    from app.models import Suggestion, Comment

                    view_args = request.view_args or {}
                    suggestion_id = view_args.get("suggestion_id")
                    comment_id = view_args.get("comment_id")
                    suggestion = None
                    if suggestion_id is not None:
                        suggestion = Suggestion.query.get(int(suggestion_id))
                    elif comment_id is not None:
                        comment = Comment.query.get(int(comment_id))
                        suggestion = comment.suggestion if comment else None
                    category = (getattr(suggestion, "category", "") or "").strip().lower()
                    if category.startswith("comision:") or category.startswith("proyecto:"):
                        is_scoped_discussion_endpoint = True
                except Exception:
                    is_scoped_discussion_endpoint = False
            if (
                endpoint not in private_area_exempt
                and not is_commission_endpoint
                and not is_scoped_discussion_endpoint
                and not current_user.has_permission("view_private_area")
            ):
                if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
                    return jsonify({"ok": False, "error": "Area privada desactivada"}), 403
                flash("El area privada esta desactivada.", "info")
                return redirect(url_for("public.home"))

        return None


# WSGI callable expected by servers that import `app:app` (e.g. Render default)
app = create_app(os.getenv("FLASK_ENV", "production"))
__all__ = ["create_app", "app"]
