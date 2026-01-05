from __future__ import annotations

from functools import lru_cache
import sqlalchemy as sa
import unicodedata
from sqlalchemy import UniqueConstraint, func
from sqlalchemy.orm import deferred
from sqlalchemy.types import TypeDecorator
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from app.extensions import db
from app.utils import make_lookup_hash, normalize_lookup, slugify
from config import encrypt_value, decrypt_value, PRIVILEGED_ROLES


@lru_cache(maxsize=1)
def _permissions_supports_public_flag() -> bool:
    try:
        inspector = sa.inspect(db.engine)
        columns = {col.get("name") for col in inspector.get_columns("permissions")}
        return "is_public" in columns
    except Exception:
        return False


def user_is_privileged(user: User | None) -> bool:
    if not user or not getattr(user, "role", None):
        return False
    role_name = normalize_lookup(getattr(user.role, "name", None))
    if role_name in PRIVILEGED_ROLES:
        return True
    # Compatibilidad con roles con acentos (e.g. "Secretaría") frente a constantes sin acento.
    role_ascii = unicodedata.normalize("NFKD", role_name).encode("ascii", "ignore").decode("ascii")
    return role_ascii in PRIVILEGED_ROLES

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


class Role(db.Model):
    __tablename__ = "roles"

    id = db.Column(db.Integer, primary_key=True)
    _name = db.Column("name", db.String(64), nullable=False)
    name_lookup = db.Column(db.String(128), unique=True, nullable=False, index=True)

    users = db.relationship("User", back_populates="role", lazy="dynamic")
    role_permissions = db.relationship(
        "RolePermission", back_populates="role", lazy="dynamic", cascade="all, delete-orphan"
    )
    permissions = db.relationship(
        "Permission",
        secondary="role_permissions",
        primaryjoin="Role.id==RolePermission.role_id",
        secondaryjoin="RolePermission.permission_id==Permission.id",
        viewonly=True,
        lazy="dynamic",
    )

    @property
    def name(self) -> str | None:
        return self._name

    @name.setter
    def name(self, value: str) -> None:
        self._name = value
        self.name_lookup = normalize_lookup(value)

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
    registration_approved = db.Column(
        db.Boolean,
        default=False,
        nullable=False,
        server_default=sa.false(),
        index=True,
    )
    privacy_accepted_at = db.Column(db.DateTime, nullable=True)
    privacy_version = db.Column(db.String(32), nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    approved_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    deactivated_at = db.Column(db.DateTime, nullable=True)
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
    deleted_at = db.Column(db.DateTime, nullable=True, index=True)

    role = db.relationship("Role", back_populates="users")
    memberships = db.relationship("Membership", back_populates="user", lazy="dynamic", cascade="all, delete-orphan")
    posts = db.relationship("Post", back_populates="author", lazy="dynamic", cascade="all, delete-orphan")
    events = db.relationship("Event", back_populates="organizer", lazy="dynamic", cascade="all, delete-orphan")
    documents = db.relationship("Document", back_populates="uploader", lazy="dynamic", cascade="all, delete-orphan")
    suggestions = db.relationship("Suggestion", back_populates="creator", lazy="dynamic", cascade="all, delete-orphan")
    comments = db.relationship("Comment", back_populates="author", lazy="dynamic", cascade="all, delete-orphan")
    votes = db.relationship("Vote", back_populates="user", lazy="dynamic", cascade="all, delete-orphan")
    discussion_polls_created = db.relationship(
        "DiscussionPoll",
        back_populates="creator",
        lazy="dynamic",
        cascade="all, delete-orphan",
        foreign_keys="DiscussionPoll.created_by",
    )
    discussion_poll_votes = db.relationship(
        "DiscussionPollVote",
        back_populates="user",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    media = db.relationship("Media", back_populates="uploader", lazy="dynamic", cascade="all, delete-orphan")
    enrollments = db.relationship("Enrollment", back_populates="user", lazy="dynamic", cascade="all, delete-orphan")
    commission_memberships = db.relationship(
        "CommissionMembership", back_populates="user", lazy="dynamic", cascade="all, delete-orphan"
    )
    approved_by = db.relationship(
        "User",
        remote_side=[id],
        foreign_keys=[approved_by_id],
        lazy="joined",
    )

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
    def is_deleted(self) -> bool:
        return bool(self.deleted_at)

    @property
    def full_name(self) -> str:
        return f"{(self.first_name or '').strip()} {(self.last_name or '').strip()}".strip()

    @property
    def display_name(self) -> str:
        return (
            self.full_name
            or (self.username or "").strip()
            or (self.email or "").strip()
            or f"Usuario {self.id}"
        )

    @property
    def is_admin(self) -> bool:
        return bool(self.role and (self.role.name_lookup or "").strip().lower() == "administrador")

    def get_commissions(self):
        active_memberships = (
            self.commission_memberships.filter_by(is_active=True)
            .join(Commission)
            .filter(Commission.is_active.is_(True))
        )
        return [membership.commission for membership in active_memberships]

    @property
    def deletion_date(self):
        if not self.is_active and self.deactivated_at:
            from datetime import timedelta
            return self.deactivated_at + timedelta(days=30)
        return None

    def is_commission_coordinator(self, commission) -> bool:
        if not commission:
            return False
        membership = (
            self.commission_memberships.filter_by(
                commission_id=getattr(commission, "id", None), is_active=True
            )
            .first()
        )
        return bool(membership and membership.role == "coordinador")

    def has_permission(self, key: str) -> bool:
        if not key:
            return False
        permission = Permission.query.filter_by(key=key).first()
        if not permission:
            return False
        if Permission.supports_public_flag() and bool(getattr(permission, "is_public", False)):
            return True
        if not self.role:
            return False
        role_permission = RolePermission.query.filter_by(
            role_id=self.role.id, permission_id=permission.id
        ).first()
        if role_permission is not None:
            return bool(role_permission.allowed)
        # Sin asignación explícita, permitimos a roles privilegiados como fallback
        return user_is_privileged(self)

    def __repr__(self) -> str:
        return f"<User {self.username}>"


class Permission(db.Model):
    __tablename__ = "permissions"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(128), unique=True, nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    # `deferred` evita romper arranques si la BD aún no tiene la columna (migración pendiente).
    is_public = deferred(db.Column(db.Boolean, default=False, nullable=False, index=True))

    role_permissions = db.relationship(
        "RolePermission", back_populates="permission", lazy="dynamic", cascade="all, delete-orphan"
    )

    @classmethod
    def supports_public_flag(cls) -> bool:
        return _permissions_supports_public_flag()

    @classmethod
    def is_key_public(cls, key: str) -> bool:
        if not key or not cls.supports_public_flag():
            return False
        try:
            value = db.session.query(cls.is_public).filter_by(key=key).scalar()
            return bool(value)
        except Exception:
            return False


class RolePermission(db.Model):
    __tablename__ = "role_permissions"

    id = db.Column(db.Integer, primary_key=True)
    role_id = db.Column(db.Integer, db.ForeignKey("roles.id"), nullable=False, index=True)
    permission_id = db.Column(db.Integer, db.ForeignKey("permissions.id"), nullable=False, index=True)
    allowed = db.Column(db.Boolean, default=True, nullable=False)

    role = db.relationship("Role", back_populates="role_permissions")
    permission = db.relationship("Permission", back_populates="role_permissions")

    __table_args__ = (db.UniqueConstraint("role_id", "permission_id", name="uq_role_permission"),)


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
    image_variants = db.Column(sa.JSON)
    author_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    published_at = db.Column(db.DateTime)
    featured_position = db.Column(db.Integer, nullable=True, index=True)
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
    image_variants = db.Column(sa.JSON)
    category = db.Column(db.String(64), default="actividades", nullable=True, index=True)
    status = db.Column(db.String(32), default="draft", nullable=False, index=True)
    is_public = db.Column(db.Boolean, default=True, nullable=False, index=True)
    google_event_id = db.Column(db.String(255))
    organizer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, server_default=func.now())
    updated_at = db.Column(db.DateTime, server_default=func.now(), onupdate=func.now())

    organizer = db.relationship("User", back_populates="events")
    enrollments = db.relationship("Enrollment", back_populates="event", lazy="dynamic")


def _generate_unique_event_slug(title: str) -> str:
    """Genera un slug basado en el título y evita duplicados en la tabla events."""
    base_slug = slugify(title or "evento")
    slug_candidate = base_slug
    counter = 2
    while Event.query.filter_by(slug=slug_candidate).first():
        slug_candidate = f"{base_slug}-{counter}"
        counter += 1
    return slug_candidate


class Enrollment(db.Model):
    __tablename__ = "enrollments"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, server_default=func.now())

    event = db.relationship("Event", back_populates="enrollments")
    user = db.relationship("User", back_populates="enrollments")

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
    meeting_minutes = db.relationship(
        "CommissionMeeting", back_populates="minutes_document", lazy="dynamic"
    )


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
    polls = db.relationship(
        "DiscussionPoll",
        back_populates="suggestion",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )


class UserSeenItem(db.Model):
    __tablename__ = "user_seen_items"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    item_type = db.Column(db.String(16), nullable=False, index=True)  # 'post' | 'event'
    item_id = db.Column(db.Integer, nullable=False, index=True)
    seen_at = db.Column(db.DateTime, server_default=func.now())
    created_at = db.Column(db.DateTime, server_default=func.now())

    __table_args__ = (
        db.UniqueConstraint("user_id", "item_type", "item_id", name="uq_user_seen_items"),
    )


class Comment(db.Model):
    __tablename__ = "comments"

    id = db.Column(db.Integer, primary_key=True)
    suggestion_id = db.Column(db.Integer, db.ForeignKey("suggestions.id"), nullable=False, index=True)
    body_html = db.Column(encrypted_text(), nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, server_default=func.now())
    is_edited = db.Column(db.Boolean, default=False)
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


class DiscussionPoll(db.Model):
    __tablename__ = "discussion_polls"

    id = db.Column(db.Integer, primary_key=True)
    suggestion_id = db.Column(db.Integer, db.ForeignKey("suggestions.id"), nullable=False, index=True)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    drive_file_ids = db.Column(sa.JSON, nullable=True)
    end_at = db.Column(db.DateTime, nullable=False, index=True)
    status = db.Column(
        db.Enum("activa", "finalizada", "nula", name="discussion_poll_status"),
        default="activa",
        nullable=False,
        index=True,
    )
    notify_enabled = db.Column(
        db.Boolean,
        default=False,
        nullable=False,
        server_default=sa.false(),
    )
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, server_default=func.now())
    closed_at = db.Column(db.DateTime, nullable=True)
    nulled_at = db.Column(db.DateTime, nullable=True)
    nulled_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    result_notified_at = db.Column(db.DateTime, nullable=True)

    suggestion = db.relationship("Suggestion", back_populates="polls")
    creator = db.relationship(
        "User",
        foreign_keys=[created_by],
        back_populates="discussion_polls_created",
    )
    nulled_by_user = db.relationship("User", foreign_keys=[nulled_by])
    votes = db.relationship(
        "DiscussionPollVote",
        back_populates="poll",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )


class DiscussionPollVote(db.Model):
    __tablename__ = "discussion_poll_votes"

    id = db.Column(db.Integer, primary_key=True)
    poll_id = db.Column(db.Integer, db.ForeignKey("discussion_polls.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    value = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, server_default=func.now())

    poll = db.relationship("DiscussionPoll", back_populates="votes")
    user = db.relationship("User", back_populates="discussion_poll_votes")

    __table_args__ = (
        UniqueConstraint("poll_id", "user_id", name="uq_discussion_poll_vote_user"),
        sa.CheckConstraint("value IN (-1, 1)", name="ck_discussion_poll_vote_value"),
    )


class Media(db.Model):
    __tablename__ = "media"

    id = db.Column(db.Integer, primary_key=True)
    file_path = db.Column(encrypted_string(512), nullable=False)
    kind = db.Column(db.Enum("image", "doc", "video", name="media_kind"), nullable=False)
    uploaded_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, server_default=func.now())

    uploader = db.relationship("User", back_populates="media")


def _generate_unique_commission_slug(title: str, exclude_id: int | None = None) -> str:
    base_slug = slugify(title or "comision")
    slug_candidate = base_slug
    counter = 2
    while True:
        query = Commission.query.filter_by(slug=slug_candidate)
        if exclude_id is not None:
            query = query.filter(Commission.id != exclude_id)
        if not query.first():
            break
        slug_candidate = f"{base_slug}-{counter}"
        counter += 1
    return slug_candidate


class Commission(db.Model):
    __tablename__ = "commissions"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False, index=True)
    slug = db.Column(db.String(255), nullable=False, unique=True, index=True)
    drive_folder_id = db.Column(db.String(255))
    description_html = db.Column(encrypted_text(), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, server_default=func.now())
    updated_at = db.Column(db.DateTime, server_default=func.now(), onupdate=func.now())

    memberships = db.relationship(
        "CommissionMembership", back_populates="commission", lazy="dynamic", cascade="all, delete-orphan"
    )
    projects = db.relationship(
        "CommissionProject", back_populates="commission", lazy="dynamic", cascade="all, delete-orphan"
    )
    meetings = db.relationship(
        "CommissionMeeting", back_populates="commission", lazy="dynamic", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Commission {self.name}>"


class CommissionMembership(db.Model):
    __tablename__ = "commission_memberships"

    id = db.Column(db.Integer, primary_key=True)
    commission_id = db.Column(db.Integer, db.ForeignKey("commissions.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    role = db.Column(db.String(32), nullable=False, index=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, server_default=func.now())

    commission = db.relationship("Commission", back_populates="memberships")
    user = db.relationship("User", back_populates="commission_memberships")

    __table_args__ = (db.UniqueConstraint("commission_id", "user_id", name="uq_commission_member"),)


class CommissionProject(db.Model):
    __tablename__ = "commission_projects"

    id = db.Column(db.Integer, primary_key=True)
    commission_id = db.Column(db.Integer, db.ForeignKey("commissions.id"), nullable=False, index=True)
    title = db.Column(db.String(255), nullable=False)
    drive_folder_id = db.Column(db.String(255))
    description_html = db.Column(encrypted_text(), nullable=True)
    status = db.Column(db.String(32), default="pendiente", nullable=False, index=True)
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    responsible_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, server_default=func.now())
    updated_at = db.Column(db.DateTime, server_default=func.now(), onupdate=func.now())

    commission = db.relationship("Commission", back_populates="projects")
    responsible = db.relationship("User")
    meetings = db.relationship(
        "CommissionMeeting",
        back_populates="project",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )


class DriveFile(db.Model):
    __tablename__ = "drive_files"

    id = db.Column(db.Integer, primary_key=True)
    scope_type = db.Column(
        db.Enum("commission", "project", name="drive_scope_type"),
        nullable=False,
        index=True,
    )
    scope_id = db.Column(db.Integer, nullable=False, index=True)
    drive_file_id = db.Column(db.String(255), nullable=False, index=True)
    name = db.Column(db.String(512), nullable=False)
    description = db.Column(db.Text, nullable=True)

    drive_created_time = db.Column(db.String(64), nullable=True)
    drive_modified_time = db.Column(db.String(64), nullable=True)

    uploaded_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    uploaded_by_label = db.Column(db.String(64), nullable=True)
    modified_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    modified_by_label = db.Column(db.String(64), nullable=True)
    deleted_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    deleted_by_label = db.Column(db.String(64), nullable=True)

    uploaded_at = db.Column(db.DateTime, nullable=True)
    modified_at = db.Column(db.DateTime, nullable=True)
    deleted_at = db.Column(db.DateTime, nullable=True, index=True)
    last_seen_at = db.Column(db.DateTime, nullable=True, index=True)

    created_at = db.Column(db.DateTime, server_default=func.now())
    updated_at = db.Column(db.DateTime, server_default=func.now(), onupdate=func.now())

    events = db.relationship(
        "DriveFileEvent",
        back_populates="drive_file",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )

    uploader = db.relationship("User", foreign_keys=[uploaded_by_id])
    modifier = db.relationship("User", foreign_keys=[modified_by_id])
    deleter = db.relationship("User", foreign_keys=[deleted_by_id])

    __table_args__ = (
        db.UniqueConstraint(
            "scope_type",
            "scope_id",
            "drive_file_id",
            name="uq_drive_file_scope_drive_id",
        ),
    )


class DriveFileEvent(db.Model):
    __tablename__ = "drive_file_events"

    id = db.Column(db.Integer, primary_key=True)
    drive_file_db_id = db.Column(
        db.Integer,
        db.ForeignKey("drive_files.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scope_type = db.Column(
        db.Enum("commission", "project", name="drive_scope_type"),
        nullable=False,
        index=True,
    )
    scope_id = db.Column(db.Integer, nullable=False, index=True)
    drive_file_id = db.Column(db.String(255), nullable=False, index=True)

    event_type = db.Column(
        db.Enum(
            "upload",
            "overwrite",
            "rename",
            "trash",
            "restore",
            "external_modify",
            "description_update",
            name="drive_file_event_type",
        ),
        nullable=False,
        index=True,
    )

    actor_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    actor_label = db.Column(db.String(64), nullable=True)

    old_name = db.Column(db.String(512), nullable=True)
    new_name = db.Column(db.String(512), nullable=True)
    old_description = db.Column(db.Text, nullable=True)
    new_description = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, server_default=func.now(), index=True)

    drive_file = db.relationship("DriveFile", back_populates="events")
    actor = db.relationship("User")


class CommissionMeeting(db.Model):
    __tablename__ = "commission_meetings"

    id = db.Column(db.Integer, primary_key=True)
    commission_id = db.Column(db.Integer, db.ForeignKey("commissions.id"), nullable=False, index=True)
    project_id = db.Column(db.Integer, db.ForeignKey("commission_projects.id"), index=True)
    title = db.Column(db.String(255), nullable=False)
    description_html = db.Column(encrypted_text(), nullable=True)
    start_at = db.Column(db.DateTime, nullable=False, index=True)
    end_at = db.Column(db.DateTime, nullable=False, index=True)
    location = db.Column(db.String(255))
    google_event_id = db.Column(db.String(255))
    minutes_document_id = db.Column(db.Integer, db.ForeignKey("documents.id"))
    created_at = db.Column(db.DateTime, server_default=func.now())
    updated_at = db.Column(db.DateTime, server_default=func.now(), onupdate=func.now())

    commission = db.relationship("Commission", back_populates="meetings")
    project = db.relationship("CommissionProject", back_populates="meetings")
    minutes_document = db.relationship("Document", back_populates="meeting_minutes")


class SiteSetting(db.Model):
    """
    Configuración clave-valor del sitio.
    Usada para almacenar el estilo activo y otras preferencias globales.
    """
    __tablename__ = "site_settings"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(128), unique=True, nullable=False, index=True)
    value = db.Column(db.Text, nullable=True)
    description = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, server_default=func.now())
    updated_at = db.Column(db.DateTime, server_default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:
        return f"<SiteSetting {self.key}={self.value}>"

    @classmethod
    def get(cls, key: str, default: str = None) -> str | None:
        """Obtiene el valor de una configuración."""
        setting = cls.query.filter_by(key=key).first()
        if setting:
            return setting.value
        return default

    @classmethod
    def set(cls, key: str, value: str, description: str = None) -> "SiteSetting":
        """Establece el valor de una configuración."""
        setting = cls.query.filter_by(key=key).first()
        if setting:
            setting.value = value
            if description:
                setting.description = description
        else:
            setting = cls(key=key, value=value, description=description)
            db.session.add(setting)
        return setting

    @classmethod
    def delete(cls, key: str) -> bool:
        """Elimina una configuración."""
        setting = cls.query.filter_by(key=key).first()
        if setting:
            db.session.delete(setting)
            return True
        return False

    @classmethod
    def get_all(cls) -> dict:
        """Obtiene todas las configuraciones como diccionario."""
        settings = cls.query.all()
        return {s.key: s.value for s in settings}


class StyleSchedule(db.Model):
    """
    Programación de estilos por fechas.
    Permite activar un estilo automáticamente en un rango de fechas.
    """
    __tablename__ = "style_schedules"

    id = db.Column(db.Integer, primary_key=True)
    style_name = db.Column(db.String(128), nullable=False, index=True)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    is_enabled = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, server_default=func.now())
    updated_at = db.Column(db.DateTime, server_default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:
        return f"<StyleSchedule {self.style_name}: {self.start_date} to {self.end_date}>"
