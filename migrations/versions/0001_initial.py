from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "roles",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(length=32), nullable=False, unique=True, index=True),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("username", sa.String(length=64), nullable=False, unique=True, index=True),
        sa.Column("email", sa.String(length=128), nullable=False, unique=True, index=True),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("email_verified", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("role_id", sa.Integer, sa.ForeignKey("roles.id"), nullable=False),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("last_login", sa.DateTime),
        sa.Column("avatar_url", sa.String(length=255)),
    )
    op.create_table(
        "memberships",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("member_number", sa.String(length=32), nullable=False),
        sa.Column("year", sa.Integer, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("user_id", "year", name="uq_membership_user_year"),
    )
    op.create_table(
        "posts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False, unique=True),
        sa.Column("body_html", sa.Text, nullable=False),
        sa.Column("excerpt", sa.String(length=512)),
        sa.Column("status", sa.Enum("draft", "published", "scheduled", name="post_status"), nullable=False, server_default="draft"),
        sa.Column("category", sa.String(length=64), nullable=False, server_default="noticias"),
        sa.Column("tags", sa.String(length=255)),
        sa.Column("cover_image", sa.String(length=255)),
        sa.Column("author_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("published_at", sa.DateTime),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_table(
        "events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False, unique=True),
        sa.Column("description_html", sa.Text, nullable=False),
        sa.Column("start_at", sa.DateTime, nullable=False),
        sa.Column("end_at", sa.DateTime, nullable=False),
        sa.Column("location", sa.String(length=255)),
        sa.Column("capacity", sa.Integer, server_default="0"),
        sa.Column("cover_image", sa.String(length=255)),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column("organizer_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_table(
        "enrollments",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("event_id", sa.Integer, sa.ForeignKey("events.id"), nullable=False),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.UniqueConstraint("event_id", "user_id", name="uq_enrollment_user_event"),
    )
    op.create_table(
        "documents",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("file_path", sa.String(length=512), nullable=False),
        sa.Column("is_private", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("category", sa.String(length=64)),
        sa.Column("uploaded_by", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_table(
        "suggestions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body_html", sa.Text, nullable=False),
        sa.Column("category", sa.String(length=64)),
        sa.Column("status", sa.Enum("pendiente", "aprobada", "rechazada", "cerrada", name="suggestion_status"), nullable=False, server_default="pendiente"),
        sa.Column("created_by", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("is_private", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("votes_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_table(
        "comments",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("suggestion_id", sa.Integer, sa.ForeignKey("suggestions.id"), nullable=False),
        sa.Column("body_html", sa.Text, nullable=False),
        sa.Column("created_by", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("parent_id", sa.Integer, sa.ForeignKey("comments.id")),
    )
    op.create_table(
        "votes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("suggestion_id", sa.Integer, sa.ForeignKey("suggestions.id"), nullable=False),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("value", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.UniqueConstraint("suggestion_id", "user_id", name="uq_vote_user_suggestion"),
    )
    op.create_table(
        "media",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("file_path", sa.String(length=512), nullable=False),
        sa.Column("kind", sa.Enum("image", "doc", "video", name="media_kind"), nullable=False),
        sa.Column("uploaded_by", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )


def downgrade():
    op.drop_table("media")
    op.drop_table("votes")
    op.drop_table("comments")
    op.drop_table("suggestions")
    op.drop_table("documents")
    op.drop_table("enrollments")
    op.drop_table("events")
    op.drop_table("posts")
    op.drop_table("memberships")
    op.drop_table("users")
    op.drop_table("roles")
