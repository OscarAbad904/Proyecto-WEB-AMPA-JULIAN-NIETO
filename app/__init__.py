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
        can_manage_members = user_is_privileged(current_user)
        return {
            "current_year": datetime.utcnow().year,
            "header_login_form": LoginForm(),
            "can_manage_members": can_manage_members,
        }
