import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask

from .config import config_by_name
from .extensions import csrf, db, login_manager, migrate
from .public import public_bp
from .members import members_bp
from .admin import admin_bp
from .api import api_bp

ROOT_PATH = Path(__file__).resolve().parent.parent


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

    return app


def register_extensions(app: Flask) -> None:
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)

    login_manager.login_view = "members.login"
    login_manager.login_message_category = "warning"


def register_blueprints(app: Flask) -> None:
    app.register_blueprint(public_bp)
    app.register_blueprint(members_bp, url_prefix="/socios")
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(api_bp, url_prefix="/api")


def register_context(app: Flask) -> None:
    @app.context_processor
    def inject_year():
        from datetime import datetime

        return {"current_year": datetime.utcnow().year}
