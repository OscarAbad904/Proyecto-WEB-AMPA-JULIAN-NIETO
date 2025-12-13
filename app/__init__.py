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
from app.forms import LoginForm
from app.commands import register_commands
from app.services.permission_registry import ensure_roles_and_permissions


def create_app(config_name: str | None = None) -> Flask:
    load_dotenv(ROOT_PATH / ".env")
    env = config_name or os.getenv("FLASK_ENV", "development")
    config = config_by_name.get(env, config_by_name["development"])

    app = Flask(
        __name__,
        template_folder=str(ROOT_PATH / "templates"),
        static_folder=str(ROOT_PATH / "assets"),
    )
    app.config.from_object(config)
    config.init_app(app)
    app.config.from_mapping({"ROOT_PATH": str(ROOT_PATH)})

    register_extensions(app)
    register_blueprints(app)
    register_context(app)
    register_commands(app)
    @app.route("/favicon.ico")
    def favicon():
        return app.send_static_file("favicon.png")
    with app.app_context():
        try:
            ensure_roles_and_permissions()
        except Exception as exc:  # noqa: BLE001
            app.logger.exception("No se pudieron sincronizar los permisos base", exc_info=exc)

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
        can_manage_members = current_user.is_authenticated and (
            current_user.has_permission("manage_members") or user_is_privileged(current_user)
        )
        can_view_posts = current_user.is_authenticated and (
            current_user.has_permission("manage_posts")
            or current_user.has_permission("view_posts")
            or user_is_privileged(current_user)
        )
        can_manage_posts = current_user.is_authenticated and (
            current_user.has_permission("manage_posts") or user_is_privileged(current_user)
        )
        can_view_events = current_user.is_authenticated and (
            current_user.has_permission("manage_events")
            or current_user.has_permission("view_events")
            or user_is_privileged(current_user)
        )
        can_manage_events = current_user.is_authenticated and (
            current_user.has_permission("manage_events") or user_is_privileged(current_user)
        )
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
            "can_manage_events": can_manage_events,
            "can_view_commissions": can_view_commissions,
            "can_manage_commissions": can_manage_commissions,
            "can_manage_permissions": can_manage_permissions,
        }


# WSGI callable expected by servers that import `app:app` (e.g. Render default)
app = create_app(os.getenv("FLASK_ENV", "production"))
__all__ = ["create_app", "app"]
