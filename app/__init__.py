import os
from flask import Flask
from dotenv import load_dotenv
from datetime import datetime

from config import config_by_name, ROOT_PATH
from app.extensions import db, migrate, login_manager, csrf
from app.routes.public import public_bp
from app.routes.members import members_bp
from app.routes.admin import admin_bp
from app.routes.api import api_bp
from app.models import User, user_is_privileged
from app.models import Permission
from app.forms import LoginForm
from app.commands import register_commands
from app.services.permission_registry import ensure_roles_and_permissions
from app.services.db_backup_scheduler import start_db_backup_scheduler
from app.services.user_cleanup_scheduler import start_user_cleanup_scheduler


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
        if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"ok": False, "message": "Solicitud incorrecta o error de seguridad (CSRF)."}), 400
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
            # Liberar conexiones tras la inicialización para evitar problemas de SSL tras fork/arranque
            db.engine.dispose()
        except Exception as exc:  # noqa: BLE001
            db.session.rollback()
            app.logger.exception("No se pudieron sincronizar los permisos base", exc_info=exc)

    start_db_backup_scheduler(app)
    start_user_cleanup_scheduler(app)

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


def register_context(app: Flask) -> None:
    @app.context_processor
    def inject_globals():
        from flask_login import current_user

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
        # El calendario público consume eventos, así que lo ligamos al permiso de eventos.
        can_view_calendar = can_view_events
        can_manage_events = current_user.is_authenticated and (
            current_user.has_permission("manage_events") or user_is_privileged(current_user)
        )
        can_view_documents = public_view_documents or (current_user.is_authenticated and (
            current_user.has_permission("manage_documents")
            or current_user.has_permission("view_documents")
            or user_is_privileged(current_user)
        ))
        can_view_commissions = (
            current_user.is_authenticated and current_user.has_permission("view_commissions")
        )
        can_manage_commissions = (
            current_user.is_authenticated and current_user.has_permission("manage_commissions")
        )
        can_manage_permissions = (
            current_user.is_authenticated
            and (
                current_user.has_permission("manage_permissions")
                or current_user.has_permission("view_permissions")
                or user_is_privileged(current_user)
            )
        )
        return {
            "current_year": datetime.utcnow().year,
            "header_login_form": LoginForm(),
            "can_manage_members": can_manage_members,
            "can_view_posts": can_view_posts,
            "can_manage_posts": can_manage_posts,
            "can_view_events": can_view_events,
            "can_view_calendar": can_view_calendar,
            "can_manage_events": can_manage_events,
            "can_view_documents": can_view_documents,
            "can_view_commissions": can_view_commissions,
            "can_manage_commissions": can_manage_commissions,
            "can_manage_permissions": can_manage_permissions,
            "can_view_register": public_view_register,
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

        return None


# WSGI callable expected by servers that import `app:app` (e.g. Render default)
app = create_app(os.getenv("FLASK_ENV", "production"))
__all__ = ["create_app", "app"]
