import os
from logging.handlers import RotatingFileHandler
from urllib.parse import quote_plus

from config import DB_PASSWORD, DB_USER

DEFAULT_DRIVER = os.getenv("ODBC_DRIVER", "ODBC Driver 17 for SQL Server")
DEFAULT_SERVER = os.getenv("ODBC_SERVER", r"localhost\EMEBIDWH")
DEFAULT_DATABASE = os.getenv("ODBC_DATABASE", "AMPA_JNT")


def _build_default_sqlalchemy_uri() -> str:
    """Arma la cadena ODBC escapada para SQLAlchemy apuntando al server real."""
    conn_parts: list[str] = [
        f"DRIVER={{{DEFAULT_DRIVER}}}",
        f"SERVER={DEFAULT_SERVER}",
        f"DATABASE={DEFAULT_DATABASE}",
        "TrustServerCertificate=yes",
    ]

    if DB_USER and DB_PASSWORD:
        conn_parts.extend(
            [f"UID={DB_USER}", f"PWD={DB_PASSWORD}", "Trusted_Connection=no"]
        )
    else:
        conn_parts.append("Trusted_Connection=yes")

    return f"mssql+pyodbc:///?odbc_connect={quote_plus(';'.join(conn_parts) + ';')}"


class BaseConfig:
    SECRET_KEY = os.getenv("SECRET_KEY", "changeme")
    SECURITY_PASSWORD_SALT = os.getenv("SECURITY_PASSWORD_SALT", "salt-me")
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "SQLALCHEMY_DATABASE_URI",
        _build_default_sqlalchemy_uri(),
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAIL_SERVER = os.getenv("MAIL_SERVER", "smtp.example.com")
    MAIL_PORT = int(os.getenv("MAIL_PORT", 587))
    MAIL_USE_TLS = os.getenv("MAIL_USE_TLS", "true").lower() in ("true", "1", "yes")
    MAIL_USERNAME = os.getenv("MAIL_USERNAME", "")
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "")
    MAIL_DEFAULT_SENDER = os.getenv("MAIL_DEFAULT_SENDER", "no-reply@ampa-jnt.es")
    LOG_FILE = os.path.join(os.path.dirname(__file__), "..", "logs", "ampa.log")
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

    @staticmethod
    def init_app(app):
        if not os.path.exists(os.path.dirname(BaseConfig.LOG_FILE)):
            os.makedirs(os.path.dirname(BaseConfig.LOG_FILE), exist_ok=True)
        handler = RotatingFileHandler(
            BaseConfig.LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=5
        )
        handler.setLevel(BaseConfig.LOG_LEVEL)
        app.logger.addHandler(handler)


class DevelopmentConfig(BaseConfig):
    DEBUG = True
    CACHE_TYPE = "SimpleCache"


class ProductionConfig(BaseConfig):
    DEBUG = False
    CACHE_TYPE = "RedisCache"


class TestingConfig(BaseConfig):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False


config_by_name = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}
