"""Aplicación Flask completa para la AMPA Julián Nieto en un único módulo.

Este archivo centraliza:
    - La configuración y carga de extensiones de Flask.
    - Los modelos de base de datos y formularios WTForms.
    - Los blueprints público, de socios, de administración y de la API.
    - Utilidades como la generación/validación de tokens.

Al mantener todo en un solo archivo se simplifica el despliegue cuando no se
puede distribuir un paquete con múltiples módulos.
"""

from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta
import re
import unicodedata
from logging.handlers import RotatingFileHandler
from pathlib import Path
import hashlib
from urllib.parse import quote_plus, urlparse, parse_qs

from dotenv import load_dotenv
from flask import (
    Blueprint,
    Flask,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect, FlaskForm
from itsdangerous import URLSafeTimedSerializer
import sqlalchemy as sa
from sqlalchemy import UniqueConstraint, func
from sqlalchemy.types import TypeDecorator
from werkzeug.security import check_password_hash, generate_password_hash
from wtforms import (
    BooleanField,
    IntegerField,
    PasswordField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
    HiddenField,
)  # noqa: WPS433
from wtforms.fields import DateField, EmailField, FileField
from wtforms.validators import DataRequired, Email, EqualTo, Length, Optional, URL

from config import decrypt_value, encrypt_value

ROOT_PATH = Path(__file__).resolve().parent
DATA_PATH = Path(os.getenv("AMPA_DATA_DIR", ROOT_PATH / "Data"))
DEFAULT_SQLALCHEMY_URI = os.getenv(
    "SQLALCHEMY_DATABASE_URI",
    os.getenv("DATABASE_URL", "postgresql+psycopg2://user:password@localhost:5432/ampa_db"),
)
PRIVILEGED_ROLES = {
    "admin",
    "administrador",
    "presidente",
    "vicepresidente",
    "secretario",
    "vicesecretario",
}


def _build_sqlalchemy_uri() -> tuple[str, Path | None]:
    """Obtiene la URI de base de datos priorizando PostgreSQL."""
    uri = os.getenv("SQLALCHEMY_DATABASE_URI") or os.getenv("DATABASE_URL")

    # Permite configurar PostgreSQL mediante variables POSTGRES_/PG*.
    if not uri:
        pg_host = os.getenv("POSTGRES_HOST") or os.getenv("PGHOST")
        pg_port = os.getenv("POSTGRES_PORT") or os.getenv("PGPORT") or "5432"
        pg_user = os.getenv("POSTGRES_USER") or os.getenv("PGUSER")
        pg_password = os.getenv("POSTGRES_PASSWORD")
        if pg_password is None:
            pg_password = os.getenv("PGPASSWORD")
        pg_db = os.getenv("POSTGRES_DB") or os.getenv("PGDATABASE")
        if pg_host and pg_user and pg_db and pg_password is not None:
            uri = (
                "postgresql+psycopg2://"
                f"{quote_plus(pg_user)}:{quote_plus(pg_password)}@{pg_host}:{pg_port}/{quote_plus(pg_db)}"
            )

    if not uri:
        uri = DEFAULT_SQLALCHEMY_URI

    return uri, None


_SQLALCHEMY_URI, _SQLALCHEMY_PATH = _build_sqlalchemy_uri()
os.environ["SQLALCHEMY_DATABASE_URI"] = _SQLALCHEMY_URI

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
csrf = CSRFProtect()


class BaseConfig:
    SECRET_KEY = os.getenv("SECRET_KEY", "changeme")
    SECURITY_PASSWORD_SALT = os.getenv("SECURITY_PASSWORD_SALT", "salt-me")
    SQLALCHEMY_DATABASE_URI = _SQLALCHEMY_URI
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAIL_SERVER = os.getenv("MAIL_SERVER", "smtp.example.com")
    MAIL_PORT = int(os.getenv("MAIL_PORT", 587))
    MAIL_USE_TLS = os.getenv("MAIL_USE_TLS", "true").lower() in ("true", "1", "yes")
    MAIL_USERNAME = os.getenv("MAIL_USERNAME", "")
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "")
    MAIL_DEFAULT_SENDER = os.getenv("MAIL_DEFAULT_SENDER", "no-reply@ampa-jnt.es")
    LOG_FILE = str(ROOT_PATH / "logs" / "ampa.log")
    DATABASE_PATH = _SQLALCHEMY_PATH
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

    @staticmethod
    def init_app(app: Flask) -> None:
        log_path = Path(BaseConfig.LOG_FILE)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            log_path,
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
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
    SQLALCHEMY_DATABASE_URI = _SQLALCHEMY_URI
    WTF_CSRF_ENABLED = False


config_by_name = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}


class EncryptedType(TypeDecorator):
    """TypeDecorator que encripta/descifra cadenas automáticamente."""

    impl = sa.Text
    cache_ok = True

    def __init__(self, impl: sa.TypeEngine | None = None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._impl = impl or sa.Text()

    def load_dialect_impl(self, dialect):
        return dialect.type_descriptor(self._impl)

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return encrypt_value(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        try:
            return decrypt_value(value)
        except Exception:
            return value


def encrypted_string(length: int | None = None) -> EncryptedType:
    base = sa.String(length) if length else sa.String()
    return EncryptedType(base)


def encrypted_text() -> EncryptedType:
    return EncryptedType(sa.Text())


def _normalize_lookup(value: str | None) -> str:
    if not value:
        return ""
    return value.strip().lower()


def make_lookup_hash(value: str | None) -> str:
    normalized = _normalize_lookup(value)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def slugify(value: str) -> str:
    """Crea un slug URL-safe a partir de un título."""
    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_text).strip("-").lower()
    return slug or "noticia"


def _normalize_drive_url(url: str | None) -> str | None:
    """Convierte enlaces de Drive en URLs de visualización directa."""
    if not url or "drive.google.com" not in url:
        return url

    patterns = [
        r"drive\.google\.com/file/d/([^/]+)/",
        r"drive\.google\.com/file/d/([^/]+)/view",
        r"drive\.google\.com/open\?id=([^&]+)",
        r"drive\.google\.com/uc\?id=([^&]+)",
        r"drive\.googleusercontent\.com/d/([^/]+)",
        r"drive\.google\.com/uc\?export=view&id=([^&]+)",
    ]
    for pat in patterns:
        match = re.search(pat, url)
        if match:
            return f"https://drive.google.com/uc?export=view&id={match.group(1)}"
    try:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        if qs.get("id"):
            return f"https://drive.google.com/uc?export=view&id={qs['id'][0]}"
    except Exception:
        return url
    return url

    patterns = [
        r"drive\.google\.com/file/d/([^/]+)/",
        r"drive\.google\.com/file/d/([^/]+)/view",
        r"drive\.google\.com/open\?id=([^&]+)",
        r"drive\.google\.com/uc\?id=([^&]+)",
        r"drive\.googleusercontent\.com/d/([^/]+)",
        r"drive\.google\.com/uc\?export=view&id=([^&]+)",
    ]
    for pat in patterns:
        match = re.search(pat, url)
        if match:
            return f"https://drive.google.com/uc?export=view&id={match.group(1)}"
    try:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        if qs.get("id"):
            return f"https://drive.google.com/uc?export=view&id={qs['id'][0]}"
    except Exception:
        return url
    return url


def _user_is_privileged(user: User | None) -> bool:
    if not user or not getattr(user, "role", None):
        return False
    role_name = (user.role.name or "").strip().lower()
    return role_name in PRIVILEGED_ROLES


def generate_confirmation_token(email: str) -> str:
    serializer = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
    return serializer.dumps(email, salt=current_app.config["SECURITY_PASSWORD_SALT"])


def confirm_token(token: str, expiration: int = 3600) -> str | bool:
    serializer = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
    try:
        email = serializer.loads(
            token,
            salt=current_app.config["SECURITY_PASSWORD_SALT"],
            max_age=expiration,
        )
    except Exception:  # noqa: BLE001
        return False
    return email


class LoginForm(FlaskForm):
    email = EmailField("Correo", validators=[DataRequired(), Email()])
    password = PasswordField("Contraseña", validators=[DataRequired(), Length(min=8)])
    remember_me = BooleanField("Recordarme")
    submit = SubmitField("Entrar")


class RegisterForm(FlaskForm):
    username = StringField("Usuario", validators=[DataRequired(), Length(min=3, max=64)])
    email = EmailField("Correo", validators=[DataRequired(), Email()])
    role = SelectField(
        "Rol",
        choices=[
            ("Presidencia", "Presidencia"),
            ("Vicepresidencia", "Vicepresidencia"),
            ("Secretaría", "Secretaría"),
            ("Vicesecretaría", "Vicesecretaría"),
            ("Tesorería", "Tesorería"),
            ("Vicetesorería", "Vicetesorería"),
            ("Vocal", "Vocal"),
            ("Socio", "Socio"),
        ],
        default="Socio",
        validators=[DataRequired()],
    )
    password = PasswordField("Contraseña", validators=[DataRequired(), Length(min=8)])
    password_confirm = PasswordField(
        "Repite la contraseña",
        validators=[DataRequired(), EqualTo("password")],
    )
    submit = SubmitField("Crear cuenta")


class RecoverForm(FlaskForm):
    email = EmailField("Correo electrónico", validators=[DataRequired(), Email()])
    submit = SubmitField("Enviar código SMS")


class ResetPasswordForm(FlaskForm):
    email = EmailField("Correo electrónico", validators=[DataRequired(), Email()])
    code = StringField("Código SMS", validators=[DataRequired(), Length(min=6, max=6)])
    password = PasswordField("Nueva contraseña", validators=[DataRequired(), Length(min=8)])
    password_confirm = PasswordField(
        "Repite la contraseña",
        validators=[DataRequired(), EqualTo("password")],
    )
    submit = SubmitField("Cambiar contraseña")


class NewMemberForm(FlaskForm):
    first_name = StringField("Nombre", validators=[DataRequired(), Length(min=2, max=64)])
    last_name = StringField("Apellidos", validators=[DataRequired(), Length(min=2, max=64)])
    email = EmailField("Correo electrónico", validators=[DataRequired(), Email()])
    phone_number = StringField("Teléfono", validators=[DataRequired(), Length(min=6, max=32)])
    address = StringField("Dirección", validators=[DataRequired(), Length(min=4, max=255)])
    city = StringField("Ciudad", validators=[DataRequired(), Length(min=2, max=128)])
    postal_code = StringField("Código postal", validators=[Optional(), Length(min=3, max=10)])
    member_number = StringField("Número de socio", validators=[Optional(), Length(max=32)])
    year = IntegerField("Año", validators=[Optional()], default=None)
    submit = SubmitField("Dar de alta")


class SuggestionForm(FlaskForm):
    title = StringField("Título", validators=[DataRequired(), Length(max=255)])
    category = SelectField(
        "Categoría",
        choices=[
            ("infraestructura", "Infraestructura"),
            ("actividades", "Actividades"),
            ("otro", "Otro"),
        ],
        validators=[DataRequired()],
    )
    body = TextAreaField("Detalle", validators=[DataRequired(), Length(min=10)])
    attachment = FileField("Adjuntar archivo (opcional)")
    submit = SubmitField("Enviar sugerencia")


class CommentForm(FlaskForm):
    content = TextAreaField("Comentario", validators=[DataRequired(), Length(min=5)])
    submit = SubmitField("Comentar")


class VoteForm(FlaskForm):
    value = SelectField("Votar", choices=[("1", "+1"), ("-1", "-1")], validators=[DataRequired()])
    submit = SubmitField("Votar")


class PostForm(FlaskForm):
    post_id = HiddenField()
    title = StringField("Título", validators=[DataRequired(), Length(max=255)])
    published_at = DateField("Fecha de publicación", format="%Y-%m-%d", validators=[Optional()])
    cover_image = StringField(
        "Imagen de portada (URL)",
        validators=[Optional(), URL(message="Introduce una URL válida"), Length(max=255)],
    )
    image_layout = SelectField(
        "Maquetación de imagen",
        choices=[
            ("full", "Portada grande"),
            ("left", "Imagen a la izquierda"),
            ("right", "Imagen a la derecha"),
            ("bottom", "Imagen abajo"),
            ("none", "Sin imagen"),
        ],
        default="full",
    )
    category = SelectField(
        "Categoría",
        choices=[
            ("actividades", "Actividades"),
            ("comunicados", "Comunicados"),
            ("reuniones", "Reuniones"),
            ("general", "General"),
        ],
        default="general",
    )
    excerpt = TextAreaField("Resumen", validators=[Optional(), Length(max=512)])
    content = TextAreaField("Contenido", validators=[DataRequired()])
    status = SelectField(
        "Estado",
        choices=[("draft", "Borrador"), ("published", "Publicada")],
        default="draft",
    )
    submit = SubmitField("Publicar noticia")




class Role(db.Model):
    __tablename__ = "roles"

    id = db.Column(db.Integer, primary_key=True)
    _name = db.Column("name", encrypted_string(64), nullable=False)
    name_lookup = db.Column(db.String(128), unique=True, nullable=False, index=True)

    users = db.relationship("User", back_populates="role", lazy="dynamic")

    @property
    def name(self) -> str | None:
        return self._name

    @name.setter
    def name(self, value: str) -> None:
        self._name = value
        self.name_lookup = make_lookup_hash(value)

    def __repr__(self) -> str:
        return f"<Role {self.name}>"


class User(db.Model, UserMixin):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    _username = db.Column("username", encrypted_string(64), nullable=False)
    username_lookup = db.Column(db.String(128), unique=True, nullable=False, index=True)
    _email = db.Column("email", encrypted_string(256), nullable=False)
    email_lookup = db.Column(db.String(128), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    email_verified = db.Column(db.Boolean, default=False, nullable=False, index=True)
    first_name = db.Column(encrypted_string(64))
    last_name = db.Column(encrypted_string(64))
    phone_number = db.Column(encrypted_string(32), index=True)
    address = db.Column(encrypted_string(255))
    city = db.Column(encrypted_string(128))
    postal_code = db.Column(encrypted_string(10))
    two_fa_enabled = db.Column(
        db.Boolean,
        default=False,
        nullable=False,
        server_default=sa.false(),
    )
    role_id = db.Column(db.Integer, db.ForeignKey("roles.id"), nullable=False)
    created_at = db.Column(db.DateTime, server_default=func.now())
    last_login = db.Column(db.DateTime)
    avatar_url = db.Column(db.String(255))

    role = db.relationship("Role", back_populates="users")
    memberships = db.relationship("Membership", back_populates="user", lazy="dynamic")
    posts = db.relationship("Post", back_populates="author", lazy="dynamic")
    events = db.relationship("Event", back_populates="organizer", lazy="dynamic")
    documents = db.relationship("Document", back_populates="uploader", lazy="dynamic")
    suggestions = db.relationship("Suggestion", back_populates="creator", lazy="dynamic")
    comments = db.relationship("Comment", back_populates="author", lazy="dynamic")
    votes = db.relationship("Vote", back_populates="user", lazy="dynamic")
    media = db.relationship("Media", back_populates="uploader", lazy="dynamic")

    @property
    def username(self) -> str | None:
        return self._username

    @username.setter
    def username(self, value: str) -> None:
        self._username = value
        self.username_lookup = make_lookup_hash(value)

    @property
    def email(self) -> str | None:
        return self._email

    @email.setter
    def email(self, value: str) -> None:
        self._email = value
        self.email_lookup = make_lookup_hash(value)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self) -> bool:
        return self.role and self.role.name == "admin"

    def __repr__(self) -> str:
        return f"<User {self.username}>"


class Membership(db.Model):
    __tablename__ = "memberships"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    member_number = db.Column(db.String(32), nullable=False)
    year = db.Column(db.Integer, nullable=False, index=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    user = db.relationship("User", back_populates="memberships")

    __table_args__ = (db.UniqueConstraint("user_id", "year", name="uq_membership_user_year"),)


class Post(db.Model):
    __tablename__ = "posts"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(encrypted_string(255), nullable=False)
    slug = db.Column(db.String(255), unique=True, nullable=False, index=True)
    body_html = db.Column(encrypted_text(), nullable=False)
    excerpt = db.Column(encrypted_string(512))
    status = db.Column(
        db.Enum("draft", "published", "scheduled", name="post_status"),
        default="draft",
        nullable=False,
        index=True,
    )
    category = db.Column(db.String(64), default="noticias", nullable=False, index=True)
    tags = db.Column(encrypted_string(255))
    cover_image = db.Column(encrypted_string(255))
    author_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    published_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, server_default=func.now())
    updated_at = db.Column(db.DateTime, server_default=func.now(), onupdate=func.now())

    author = db.relationship("User", back_populates="posts")


class Event(db.Model):
    __tablename__ = "events"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    slug = db.Column(db.String(255), unique=True, nullable=False, index=True)
    description_html = db.Column(encrypted_text(), nullable=False)
    start_at = db.Column(db.DateTime, nullable=False, index=True)
    end_at = db.Column(db.DateTime, nullable=False, index=True)
    location = db.Column(db.String(255))
    capacity = db.Column(db.Integer, default=0)
    cover_image = db.Column(db.String(255))
    status = db.Column(db.String(32), default="draft", nullable=False, index=True)
    organizer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, server_default=func.now())
    updated_at = db.Column(db.DateTime, server_default=func.now(), onupdate=func.now())

    organizer = db.relationship("User", back_populates="events")
    enrollments = db.relationship("Enrollment", back_populates="event", lazy="dynamic")


class Enrollment(db.Model):
    __tablename__ = "enrollments"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, server_default=func.now())

    event = db.relationship("Event", back_populates="enrollments")
    user = db.relationship("User")

    __table_args__ = (db.UniqueConstraint("event_id", "user_id", name="uq_enrollment_user_event"),)


class Document(db.Model):
    __tablename__ = "documents"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(encrypted_string(255), nullable=False)
    file_path = db.Column(encrypted_string(512), nullable=False)
    is_private = db.Column(db.Boolean, default=True, nullable=False)
    category = db.Column(db.String(64))
    uploaded_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, server_default=func.now())

    uploader = db.relationship("User", back_populates="documents")


class Suggestion(db.Model):
    __tablename__ = "suggestions"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(encrypted_string(255), nullable=False)
    body_html = db.Column(encrypted_text(), nullable=False)
    category = db.Column(db.String(64), index=True)
    status = db.Column(
        db.Enum("pendiente", "aprobada", "rechazada", "cerrada", name="suggestion_status"),
        default="pendiente",
        nullable=False,
        index=True,
    )
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    is_private = db.Column(db.Boolean, default=False)
    votes_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, server_default=func.now())
    updated_at = db.Column(db.DateTime, server_default=func.now(), onupdate=func.now())

    creator = db.relationship("User", back_populates="suggestions")
    comments = db.relationship("Comment", back_populates="suggestion", lazy="dynamic")
    votes = db.relationship("Vote", back_populates="suggestion", lazy="dynamic")


class Comment(db.Model):
    __tablename__ = "comments"

    id = db.Column(db.Integer, primary_key=True)
    suggestion_id = db.Column(db.Integer, db.ForeignKey("suggestions.id"), nullable=False, index=True)
    body_html = db.Column(encrypted_text(), nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, server_default=func.now())
    parent_id = db.Column(db.Integer, db.ForeignKey("comments.id"), nullable=True)

    suggestion = db.relationship("Suggestion", back_populates="comments")
    author = db.relationship("User", back_populates="comments")
    children = db.relationship(
        "Comment",
        backref=db.backref("parent", remote_side=[id]),
        lazy="dynamic",
    )


class Vote(db.Model):
    __tablename__ = "votes"

    id = db.Column(db.Integer, primary_key=True)
    suggestion_id = db.Column(db.Integer, db.ForeignKey("suggestions.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    value = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, server_default=func.now())

    suggestion = db.relationship("Suggestion", back_populates="votes")
    user = db.relationship("User", back_populates="votes")

    __table_args__ = (UniqueConstraint("suggestion_id", "user_id", name="uq_vote_user_suggestion"),)


class Media(db.Model):
    __tablename__ = "media"

    id = db.Column(db.Integer, primary_key=True)
    file_path = db.Column(encrypted_string(512), nullable=False)
    kind = db.Column(db.Enum("image", "doc", "video", name="media_kind"), nullable=False)
    uploaded_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, server_default=func.now())

    uploader = db.relationship("User", back_populates="media")


public_bp = Blueprint("public", __name__, template_folder="templates/public")


@public_bp.route("/")
@public_bp.route("/AMPA")
def home():
    return render_template("index.html")


@public_bp.route("/quienes-somos")
def quienes_somos():
    return render_template("public/quienes_somos.html")


@public_bp.route("/noticias")
def noticias():
    query = request.args.get("q", "")
    posts = (
        Post.query.filter_by(status="published")
        .order_by(Post.published_at.desc().nullslast(), Post.created_at.desc())
        .all()
    )
    for post in posts:
        post.cover_image = _normalize_drive_url(post.cover_image)
    latest_three = posts[:3]
    return render_template("public/noticias.html", query=query, posts=posts, latest_three=latest_three)


@public_bp.route("/noticias/<slug>")
def noticia_detalle(slug):
    return render_template("public/noticia_detalle.html", slug=slug)


@public_bp.route("/eventos")
def eventos():
    return render_template("public/eventos.html")


@public_bp.route("/eventos/<slug>")
def evento_detalle(slug):
    return render_template("public/evento_detalle.html", slug=slug)


@public_bp.route("/documentos")
def documentos():
    return render_template("public/documentos.html")


@public_bp.route("/contacto", methods=["GET", "POST"])
def contacto():
    if request.method == "POST":
        current_app.logger.info("Contacto enviado desde la web pública")
    return render_template("public/contacto.html")


@public_bp.route("/faq")
def faq():
    return render_template("public/faq.html")


admin_bp = Blueprint("admin", __name__, template_folder="templates/admin")


@admin_bp.route("/")
@login_required
def dashboard_admin():
    return render_template("admin/dashboard.html")


@admin_bp.route("/posts", methods=["GET", "POST"])
@login_required
def posts():
    if not _user_is_privileged(current_user):
        abort(403)

    form = PostForm()
    if request.method == "GET" and not form.published_at.data:
        form.published_at.data = datetime.utcnow().date()

    recent_posts = (
        Post.query.order_by(Post.published_at.desc().nullslast(), Post.created_at.desc())
        .all()
    )
    for rp in recent_posts:
        rp.cover_image = _normalize_drive_url(rp.cover_image) or rp.cover_image

    if form.validate_on_submit():
        post: Post | None = None
        if form.post_id.data:
            try:
                post = Post.query.get(int(form.post_id.data))
            except Exception:
                post = None

        content_html = form.content.data or ""
        content_text = re.sub(r"<[^>]+>", "", content_html).strip()
        if not content_text:
            flash("Añade contenido a la noticia.", "warning")
            return render_template("admin/posts.html", form=form, posts=recent_posts)

        published_at = None
        if form.published_at.data:
            published_at = datetime.combine(form.published_at.data, datetime.min.time())
        if form.status.data == "published" and not published_at:
            published_at = datetime.utcnow()

        excerpt = form.excerpt.data or content_text[:240]

        category_value = form.category.data or "general"
        normalized_cover = _normalize_drive_url(form.cover_image.data)

        if post:
            post.title = form.title.data.strip()
            if form.title.data and post.slug:
                base_slug = slugify(form.title.data)
                slug = base_slug
                counter = 2
                existing = Post.query.filter(Post.slug == slug, Post.id != post.id).first()
                while existing:
                    slug = f"{base_slug}-{counter}"
                    existing = Post.query.filter(Post.slug == slug, Post.id != post.id).first()
                    counter += 1
                post.slug = slug
            post.body_html = content_html
            post.excerpt = excerpt
            post.status = form.status.data
            post.tags = form.image_layout.data  # usamos tags para layout
            post.cover_image = normalized_cover
            post.published_at = published_at
            post.category = category_value
            db.session.commit()
            flash("Noticia actualizada", "success")
        else:
            base_slug = slugify(form.title.data)
            slug = base_slug
            existing = Post.query.filter_by(slug=slug).first()
            counter = 2
            while existing:
                slug = f"{base_slug}-{counter}"
                existing = Post.query.filter_by(slug=slug).first()
                counter += 1

            post = Post(
                title=form.title.data.strip(),
                slug=slug,
                body_html=content_html,
                excerpt=excerpt,
                status=form.status.data,
                category=category_value,
                tags=form.image_layout.data,  # layout
                cover_image=normalized_cover,
                author_id=current_user.id,
                published_at=published_at,
            )
            db.session.add(post)
            db.session.commit()
            flash("Noticia guardada en el tablón", "success")
        return redirect(url_for("admin.posts"))

    if request.method == "POST":
        flash("Revisa los datos del formulario de noticia.", "warning")

    return render_template("admin/posts.html", form=form, posts=recent_posts)


@admin_bp.route("/posts/<int:post_id>/delete", methods=["POST"])
@login_required
def delete_post(post_id: int):
    if not _user_is_privileged(current_user):
        abort(403)
    post = Post.query.get_or_404(post_id)
    db.session.delete(post)
    db.session.commit()
    flash("Noticia eliminada", "success")
    return redirect(url_for("admin.posts"))


@admin_bp.route("/eventos")
@login_required
def admin_eventos():
    return render_template("admin/eventos.html")


@admin_bp.route("/sugerencias")
@login_required
def admin_sugerencias():
    return render_template("admin/sugerencias.html")


@admin_bp.route("/usuarios")
@login_required
def usuarios():
    return render_template("admin/usuarios.html")


api_bp = Blueprint("api", __name__)


@api_bp.route("/status")
def status() -> tuple[dict[str, str], int]:
    payload: dict[str, str] = {
        "status": "ok",
        "service": "AMPA Julián Nieto",
        "version": "0.1",
    }
    return payload, 200


@api_bp.route("/publicaciones")
def publicaciones() -> tuple[dict[str, object], int]:
    payload: dict[str, object] = {
        "items": [],
        "pagination": {"page": 1, "per_page": 10},
    }
    return payload, 200


members_bp = Blueprint("members", __name__, template_folder="templates/members")


@login_manager.user_loader
def load_user(user_id: str):
    return User.query.get(int(user_id))


def _generate_password(length: int = 10) -> str:
    return secrets.token_urlsafe(length)[:length]


def _generate_member_number(year: int) -> str:
    return f"{year}-SOC-{secrets.randbelow(9999):04}"


def _send_sms_code(phone: str, code: str) -> None:
    print(f"[SMS] Enviar código {code} a {phone}")


@members_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("members.dashboard"))
    form = LoginForm()
    if form.validate_on_submit():
        lookup_email = make_lookup_hash(form.email.data)
        user = User.query.filter_by(email_lookup=lookup_email).first()
        if user and user.check_password(form.password.data):
            login_user(user, remember=form.remember_me.data)
            user.last_login = datetime.utcnow()
            db.session.commit()
            flash("Bienvenido de nuevo", "success")
            return redirect(url_for("members.dashboard"))
        flash("Credenciales inválidas", "danger")
    return render_template("members/login.html", form=form)


@members_bp.route("/register", methods=["GET", "POST"])
def register():
    form = RegisterForm()
    if form.validate_on_submit():
        lookup_email = make_lookup_hash(form.email.data)
        if User.query.filter_by(email_lookup=lookup_email).first():
            flash("Ya existe una cuenta con ese correo", "warning")
            return render_template("members/register.html", form=form)
        role = Role.query.filter_by(name_lookup=make_lookup_hash("socio")).first()
        if not role:
            role = Role(name="socio")
            db.session.add(role)
            db.session.commit()
        user = User(
            username=form.username.data,
            email=form.email.data.lower(),
            role=role,
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        generate_confirmation_token(user.email)
        flash("Se ha enviado un correo de verificación", "info")
        return redirect(url_for("members.login"))
    return render_template("members/register.html", form=form)


@members_bp.route("/logout")
def logout():
    logout_user()
    flash("Sesión cerrada", "info")
    return redirect(url_for("public.home"))


@members_bp.route("/")
@login_required
def dashboard():
    alta_form = NewMemberForm()
    return render_template("members/dashboard.html", alta_form=alta_form)


@members_bp.route("/socios/alta", methods=["POST"])
@login_required
def alta_socio():
    if not current_user.is_admin:
        abort(403)
    form = NewMemberForm()
    if form.validate_on_submit():
        email = form.email.data
        lookup_email = make_lookup_hash(email)
        if User.query.filter_by(email_lookup=lookup_email).first():
            flash("Ya existe un usuario con ese correo.", "warning")
            return redirect(url_for("members.dashboard"))
        role = Role.query.filter_by(name_lookup=make_lookup_hash("socio")).first()
        if not role:
            role = Role(name="socio")
            db.session.add(role)
            db.session.commit()
        username = email.split("@")[0]
        password = _generate_password()
        year = form.year.data or datetime.utcnow().year
        member_number = form.member_number.data or _generate_member_number(year)
        user = User(
            username=username,
            email=email,
            first_name=form.first_name.data,
            last_name=form.last_name.data,
            phone_number=form.phone_number.data,
            address=form.address.data,
            city=form.city.data,
            postal_code=form.postal_code.data,
            role=role,
            email_verified=True,
            two_fa_enabled=True,
        )
        user.set_password(password)
        membership = Membership(
            user=user,
            member_number=member_number,
            year=year,
            is_active=True,
        )
        db.session.add(user)
        db.session.add(membership)
        db.session.commit()
        flash(
            f"Socio creado. Usuario: {email} | Contraseña temporal: {password}",
            "success",
        )
    else:
        flash("Revisa los datos del formulario de alta.", "danger")
    return redirect(url_for("members.dashboard"))


@members_bp.route("/recuperar", methods=["GET", "POST"])
def recuperar():
    email_form = RecoverForm()
    reset_form = ResetPasswordForm()
    reset_data = session.get("reset_flow")

    if email_form.validate_on_submit() and "stage" not in request.form:
        lookup_email = make_lookup_hash(email_form.email.data)
        user = User.query.filter_by(email_lookup=lookup_email).first()
        if user and user.phone_number:
            code = f"{secrets.randbelow(1_000_000):06}"
            expires_at = (datetime.utcnow() + timedelta(minutes=10)).isoformat()
            session["reset_flow"] = {
                "email": user.email,
                "code": code,
                "expires_at": expires_at,
            }
            _send_sms_code(user.phone_number, code)
            flash("Te hemos enviado un código SMS para restablecer la contraseña.", "info")
        else:
            flash("No hay teléfono asociado o la cuenta no existe.", "warning")
        return render_template(
            "members/recuperar.html",
            email_form=email_form,
            reset_form=reset_form,
            stage="code",
        )

    if reset_form.validate_on_submit() and request.form.get("stage") == "code":
        flow = reset_data or {}
        submitted_email = reset_form.email.data
        if not flow or flow.get("email") != submitted_email:
            flash("La solicitud de recuperación expiró o es inválida.", "danger")
            return render_template(
                "members/recuperar.html",
                email_form=email_form,
                reset_form=reset_form,
                stage="code",
            )
        if datetime.utcnow() > datetime.fromisoformat(flow["expires_at"]):
            session.pop("reset_flow", None)
            flash("El código ha expirado. Solicita uno nuevo.", "warning")
            return render_template(
                "members/recuperar.html",
                email_form=email_form,
                reset_form=reset_form,
                stage="code",
            )
        if reset_form.code.data != flow["code"]:
            flash("Código incorrecto.", "danger")
            return render_template(
                "members/recuperar.html",
                email_form=email_form,
                reset_form=reset_form,
                stage="code",
            )
        user = User.query.filter_by(email_lookup=make_lookup_hash(submitted_email)).first()
        if not user:
            flash("Cuenta no encontrada.", "danger")
            return render_template(
                "members/recuperar.html",
                email_form=email_form,
                reset_form=reset_form,
                stage="code",
            )
        user.set_password(reset_form.password.data)
        db.session.commit()
        session.pop("reset_flow", None)
        flash("Contraseña actualizada. Ya puedes iniciar sesión.", "success")
        return redirect(url_for("members.login"))

    return render_template(
        "members/recuperar.html",
        email_form=email_form,
        reset_form=reset_form,
        stage="code" if reset_data else "email",
    )


@members_bp.route("/sugerencias")
@login_required
def sugerencias():
    status = request.args.get("status", "pendiente")
    page = request.args.get("page", 1, type=int)
    suggestions = (
        Suggestion.query.filter_by(status=status)
        .order_by(Suggestion.votes_count.desc())
        .paginate(page=page, per_page=5)
    )
    return render_template("members/sugerencias.html", suggestions=suggestions, status=status)


@members_bp.route("/sugerencias/nueva", methods=["GET", "POST"])
@login_required
def nueva_sugerencia():
    form = SuggestionForm()
    if form.validate_on_submit():
        suggestion = Suggestion(
            title=form.title.data,
            body_html=form.body.data,
            category=form.category.data,
            created_by=current_user.id,
        )
        db.session.add(suggestion)
        db.session.commit()
        flash("Sugerencia creada", "success")
        return redirect(url_for("members.sugerencias"))
    return render_template("members/sugerencia_form.html", form=form)


@members_bp.route("/sugerencias/<int:suggestion_id>")
@login_required
def detalle_sugerencia(suggestion_id: int):
    suggestion = Suggestion.query.get_or_404(suggestion_id)
    comment_form = CommentForm()
    vote_form = VoteForm()
    return render_template(
        "members/sugerencia_detalle.html",
        suggestion=suggestion,
        comment_form=comment_form,
        vote_form=vote_form,
    )


@members_bp.route("/sugerencias/<int:suggestion_id>/comentar", methods=["POST"])
@login_required
def comentar_sugerencia(suggestion_id: int):
    suggestion = Suggestion.query.get_or_404(suggestion_id)
    form = CommentForm()
    if form.validate_on_submit():
        parent_id = request.form.get("parent_id")
        comment = Comment(
            suggestion_id=suggestion.id,
            body_html=form.content.data,
            created_by=current_user.id,
            parent_id=parent_id,
        )
        db.session.add(comment)
        db.session.commit()
        flash("Comentario añadido", "success")
    return redirect(url_for("members.detalle_sugerencia", suggestion_id=suggestion_id))


@members_bp.route("/sugerencias/<int:suggestion_id>/votar", methods=["POST"])
@login_required
def votar_sugerencia(suggestion_id: int):
    suggestion = Suggestion.query.get_or_404(suggestion_id)
    form = VoteForm()
    if form.validate_on_submit():
        value = int(form.value.data)
        vote = Vote.query.filter_by(user_id=current_user.id, suggestion_id=suggestion.id).first()
        if vote:
            suggestion.votes_count -= vote.value
            vote.value = value
        else:
            vote = Vote(suggestion_id=suggestion.id, user_id=current_user.id, value=value)
            db.session.add(vote)
        suggestion.votes_count += value
        db.session.commit()
        flash("Voto registrado", "success")
    return redirect(url_for("members.detalle_sugerencia", suggestion_id=suggestion_id))


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
    def inject_globals():
        can_manage_members = _user_is_privileged(current_user)
        return {
            "current_year": datetime.utcnow().year,
            "header_login_form": LoginForm(),
            "can_manage_members": can_manage_members,
        }
