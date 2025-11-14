from datetime import datetime

from flask_login import UserMixin
from sqlalchemy import UniqueConstraint, func
from werkzeug.security import check_password_hash, generate_password_hash

from ..extensions import db


class Role(db.Model):
    __tablename__ = "roles"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(32), unique=True, nullable=False, index=True)

    users = db.relationship("User", back_populates="role", lazy="dynamic")

    def __repr__(self):
        return f"<Role {self.name}>"


class User(db.Model, UserMixin):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    email = db.Column(db.String(128), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    email_verified = db.Column(db.Boolean, default=False, nullable=False, index=True)
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

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self) -> bool:
        return self.role and self.role.name == "admin"

    def __repr__(self):
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
    title = db.Column(db.String(255), nullable=False)
    slug = db.Column(db.String(255), unique=True, nullable=False, index=True)
    body_html = db.Column(db.Text, nullable=False)
    excerpt = db.Column(db.String(512))
    status = db.Column(db.Enum("draft", "published", "scheduled", name="post_status"), default="draft", nullable=False, index=True)
    category = db.Column(db.String(64), default="noticias", nullable=False, index=True)
    tags = db.Column(db.String(255))
    cover_image = db.Column(db.String(255))
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
    description_html = db.Column(db.Text, nullable=False)
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
    title = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(512), nullable=False)
    is_private = db.Column(db.Boolean, default=True, nullable=False)
    category = db.Column(db.String(64))
    uploaded_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, server_default=func.now())

    uploader = db.relationship("User", back_populates="documents")


class Suggestion(db.Model):
    __tablename__ = "suggestions"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    body_html = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(64), index=True)
    status = db.Column(db.Enum("pendiente", "aprobada", "rechazada", "cerrada", name="suggestion_status"), default="pendiente", nullable=False, index=True)
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
    body_html = db.Column(db.Text, nullable=False)
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
    file_path = db.Column(db.String(512), nullable=False)
    kind = db.Column(db.Enum("image", "doc", "video", name="media_kind"), nullable=False)
    uploaded_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, server_default=func.now())

    uploader = db.relationship("User", back_populates="media")
