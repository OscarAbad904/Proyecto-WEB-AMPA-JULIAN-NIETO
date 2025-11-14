import os
from logging.handlers import RotatingFileHandler


class BaseConfig:
    SECRET_KEY = os.getenv("SECRET_KEY", "changeme")
    SECURITY_PASSWORD_SALT = os.getenv("SECURITY_PASSWORD_SALT", "salt-me")
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "SQLALCHEMY_DATABASE_URI",
        "mssql+pyodbc:///?odbc_connect=DRIVER%3D%7BODBC+Driver+18+for+SQL+Server%7D%3BSERVER%3Dlocalhost%3BDATABASE%3DAMPA_JNT%3BTrusted_Connection%3DYes",
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
