"""add discussion polls

Revision ID: d1e2f3a4b5c6
Revises: c3a7f2b1d4e8
Create Date: 2026-01-04 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d1e2f3a4b5c6"
down_revision = "c3a7f2b1d4e8"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "discussion_polls",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("suggestion_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("end_at", sa.DateTime(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("activa", "finalizada", "nula", name="discussion_poll_status"),
            nullable=False,
        ),
        sa.Column("notify_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("nulled_at", sa.DateTime(), nullable=True),
        sa.Column("nulled_by", sa.Integer(), nullable=True),
        sa.Column("result_notified_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_discussion_polls_created_by"),
        sa.ForeignKeyConstraint(["nulled_by"], ["users.id"], name="fk_discussion_polls_nulled_by"),
        sa.ForeignKeyConstraint(["suggestion_id"], ["suggestions.id"], name="fk_discussion_polls_suggestion"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_discussion_polls_suggestion_id", "discussion_polls", ["suggestion_id"], unique=False)
    op.create_index("ix_discussion_polls_end_at", "discussion_polls", ["end_at"], unique=False)
    op.create_index("ix_discussion_polls_status", "discussion_polls", ["status"], unique=False)
    op.create_index("ix_discussion_polls_created_by", "discussion_polls", ["created_by"], unique=False)
    op.create_index("ix_discussion_polls_nulled_by", "discussion_polls", ["nulled_by"], unique=False)

    op.create_table(
        "discussion_poll_votes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("poll_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("value", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["poll_id"], ["discussion_polls.id"], name="fk_discussion_poll_votes_poll"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_discussion_poll_votes_user"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("poll_id", "user_id", name="uq_discussion_poll_vote_user"),
        sa.CheckConstraint("value IN (-1, 1)", name="ck_discussion_poll_vote_value"),
    )
    op.create_index("ix_discussion_poll_votes_poll_id", "discussion_poll_votes", ["poll_id"], unique=False)
    op.create_index("ix_discussion_poll_votes_user_id", "discussion_poll_votes", ["user_id"], unique=False)


def downgrade():
    op.drop_index("ix_discussion_poll_votes_user_id", table_name="discussion_poll_votes")
    op.drop_index("ix_discussion_poll_votes_poll_id", table_name="discussion_poll_votes")
    op.drop_table("discussion_poll_votes")

    op.drop_index("ix_discussion_polls_nulled_by", table_name="discussion_polls")
    op.drop_index("ix_discussion_polls_created_by", table_name="discussion_polls")
    op.drop_index("ix_discussion_polls_status", table_name="discussion_polls")
    op.drop_index("ix_discussion_polls_end_at", table_name="discussion_polls")
    op.drop_index("ix_discussion_polls_suggestion_id", table_name="discussion_polls")
    op.drop_table("discussion_polls")

    discussion_poll_status = sa.Enum("activa", "finalizada", "nula", name="discussion_poll_status")
    discussion_poll_status.drop(op.get_bind(), checkfirst=True)
