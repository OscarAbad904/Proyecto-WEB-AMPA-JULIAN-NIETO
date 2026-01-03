"""add drive file registry

Revision ID: 6c8d1a2f3b4c
Revises: 5b7c9d0e1f2a
Create Date: 2026-01-03 00:00:00

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "6c8d1a2f3b4c"
down_revision = "5b7c9d0e1f2a"
branch_labels = None
depends_on = None


def upgrade():
    # Crear tipos ENUM de PostgreSQL de forma segura (checkfirst) y evitar que
    # create_table intente recrearlos (create_type=False en los usados por tablas).
    drive_scope_type_db = postgresql.ENUM(
        "commission",
        "project",
        name="drive_scope_type",
        create_type=True,
    )
    drive_file_event_type_db = postgresql.ENUM(
        "upload",
        "overwrite",
        "rename",
        "trash",
        "restore",
        "external_modify",
        "description_update",
        name="drive_file_event_type",
        create_type=True,
    )

    drive_scope_type = postgresql.ENUM(
        "commission",
        "project",
        name="drive_scope_type",
        create_type=False,
    )
    drive_file_event_type = postgresql.ENUM(
        "upload",
        "overwrite",
        "rename",
        "trash",
        "restore",
        "external_modify",
        "description_update",
        name="drive_file_event_type",
        create_type=False,
    )

    bind = op.get_bind()
    drive_scope_type_db.create(bind, checkfirst=True)
    drive_file_event_type_db.create(bind, checkfirst=True)

    op.create_table(
        "drive_files",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scope_type", drive_scope_type, nullable=False),
        sa.Column("scope_id", sa.Integer(), nullable=False),
        sa.Column("drive_file_id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("drive_created_time", sa.String(length=64), nullable=True),
        sa.Column("drive_modified_time", sa.String(length=64), nullable=True),
        sa.Column("uploaded_by_id", sa.Integer(), nullable=True),
        sa.Column("uploaded_by_label", sa.String(length=64), nullable=True),
        sa.Column("modified_by_id", sa.Integer(), nullable=True),
        sa.Column("modified_by_label", sa.String(length=64), nullable=True),
        sa.Column("deleted_by_id", sa.Integer(), nullable=True),
        sa.Column("deleted_by_label", sa.String(length=64), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(), nullable=True),
        sa.Column("modified_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["deleted_by_id"], ["users.id"], name="fk_drive_files_deleted_by"),
        sa.ForeignKeyConstraint(["modified_by_id"], ["users.id"], name="fk_drive_files_modified_by"),
        sa.ForeignKeyConstraint(["uploaded_by_id"], ["users.id"], name="fk_drive_files_uploaded_by"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scope_type",
            "scope_id",
            "drive_file_id",
            name="uq_drive_file_scope_drive_id",
        ),
    )

    op.create_index("ix_drive_files_scope_type", "drive_files", ["scope_type"], unique=False)
    op.create_index("ix_drive_files_scope_id", "drive_files", ["scope_id"], unique=False)
    op.create_index("ix_drive_files_drive_file_id", "drive_files", ["drive_file_id"], unique=False)
    op.create_index("ix_drive_files_deleted_at", "drive_files", ["deleted_at"], unique=False)
    op.create_index("ix_drive_files_last_seen_at", "drive_files", ["last_seen_at"], unique=False)
    op.create_index("ix_drive_files_uploaded_by_id", "drive_files", ["uploaded_by_id"], unique=False)
    op.create_index("ix_drive_files_modified_by_id", "drive_files", ["modified_by_id"], unique=False)
    op.create_index("ix_drive_files_deleted_by_id", "drive_files", ["deleted_by_id"], unique=False)

    op.create_table(
        "drive_file_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("drive_file_db_id", sa.Integer(), nullable=False),
        sa.Column("scope_type", drive_scope_type, nullable=False),
        sa.Column("scope_id", sa.Integer(), nullable=False),
        sa.Column("drive_file_id", sa.String(length=255), nullable=False),
        sa.Column("event_type", drive_file_event_type, nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("actor_label", sa.String(length=64), nullable=True),
        sa.Column("old_name", sa.String(length=512), nullable=True),
        sa.Column("new_name", sa.String(length=512), nullable=True),
        sa.Column("old_description", sa.Text(), nullable=True),
        sa.Column("new_description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], name="fk_drive_file_events_actor"),
        sa.ForeignKeyConstraint(
            ["drive_file_db_id"],
            ["drive_files.id"],
            name="fk_drive_file_events_drive_file",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_drive_file_events_drive_file_db_id",
        "drive_file_events",
        ["drive_file_db_id"],
        unique=False,
    )
    op.create_index("ix_drive_file_events_scope_type", "drive_file_events", ["scope_type"], unique=False)
    op.create_index("ix_drive_file_events_scope_id", "drive_file_events", ["scope_id"], unique=False)
    op.create_index("ix_drive_file_events_drive_file_id", "drive_file_events", ["drive_file_id"], unique=False)
    op.create_index("ix_drive_file_events_event_type", "drive_file_events", ["event_type"], unique=False)
    op.create_index("ix_drive_file_events_actor_user_id", "drive_file_events", ["actor_user_id"], unique=False)
    op.create_index("ix_drive_file_events_created_at", "drive_file_events", ["created_at"], unique=False)


def downgrade():
    bind = op.get_bind()

    op.drop_index("ix_drive_file_events_created_at", table_name="drive_file_events")
    op.drop_index("ix_drive_file_events_actor_user_id", table_name="drive_file_events")
    op.drop_index("ix_drive_file_events_event_type", table_name="drive_file_events")
    op.drop_index("ix_drive_file_events_drive_file_id", table_name="drive_file_events")
    op.drop_index("ix_drive_file_events_scope_id", table_name="drive_file_events")
    op.drop_index("ix_drive_file_events_scope_type", table_name="drive_file_events")
    op.drop_index("ix_drive_file_events_drive_file_db_id", table_name="drive_file_events")
    op.drop_table("drive_file_events")

    op.drop_index("ix_drive_files_deleted_by_id", table_name="drive_files")
    op.drop_index("ix_drive_files_modified_by_id", table_name="drive_files")
    op.drop_index("ix_drive_files_uploaded_by_id", table_name="drive_files")
    op.drop_index("ix_drive_files_last_seen_at", table_name="drive_files")
    op.drop_index("ix_drive_files_deleted_at", table_name="drive_files")
    op.drop_index("ix_drive_files_drive_file_id", table_name="drive_files")
    op.drop_index("ix_drive_files_scope_id", table_name="drive_files")
    op.drop_index("ix_drive_files_scope_type", table_name="drive_files")
    op.drop_table("drive_files")

    drive_file_event_type = postgresql.ENUM(name="drive_file_event_type")
    drive_scope_type = postgresql.ENUM(name="drive_scope_type")

    drive_file_event_type.drop(bind, checkfirst=True)
    drive_scope_type.drop(bind, checkfirst=True)
