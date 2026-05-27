"""add form groups and grouped answer submissions

Revision ID: 20260527_0007
Revises: 20260522_0006
Create Date: 2026-05-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op


revision: str = "20260527_0007"
down_revision: str | None = "20260522_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "form_groups",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.String(length=1000), nullable=True),
        sa.Column("schedule_crons", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reminder_enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("reminder_title", sa.String(), nullable=True),
        sa.Column("reminder_payload", sa.JSON(), nullable=False),
        sa.Column("skip_retry_delay_seconds", sa.Integer(), server_default="3600", nullable=False),
        sa.Column(
            "delivery_retry_delay_seconds",
            sa.Integer(),
            server_default="3600",
            nullable=False,
        ),
        sa.Column("last_reminder_scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_form_groups_id"), "form_groups", ["id"], unique=False)
    op.create_index(op.f("ix_form_groups_user_id"), "form_groups", ["user_id"], unique=False)

    op.create_table(
        "form_group_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("form_id", sa.Integer(), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(["form_id"], ["forms.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["group_id"], ["form_groups.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_form_group_items_id"), "form_group_items", ["id"], unique=False)
    op.create_index(
        op.f("ix_form_group_items_group_id"),
        "form_group_items",
        ["group_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_form_group_items_form_id"),
        "form_group_items",
        ["form_id"],
        unique=False,
    )
    op.create_index(
        "uq_form_group_item_form",
        "form_group_items",
        ["group_id", "form_id"],
        unique=True,
    )

    op.create_table(
        "answer_submissions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("form_group_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["form_group_id"], ["form_groups.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_answer_submissions_id"), "answer_submissions", ["id"], unique=False)
    op.create_index(
        op.f("ix_answer_submissions_user_id"),
        "answer_submissions",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_answer_submissions_form_group_id"),
        "answer_submissions",
        ["form_group_id"],
        unique=False,
    )

    op.add_column("answers", sa.Column("submission_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_answers_submission_id_answer_submissions",
        "answers",
        "answer_submissions",
        ["submission_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(op.f("ix_answers_submission_id"), "answers", ["submission_id"], unique=False)

    op.add_column("reminders", sa.Column("form_group_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_reminders_form_group_id_form_groups",
        "reminders",
        "form_groups",
        ["form_group_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        op.f("ix_reminders_form_group_id"),
        "reminders",
        ["form_group_id"],
        unique=False,
    )
    op.create_index(
        "uq_active_form_group_reminder",
        "reminders",
        ["user_id", "form_group_id"],
        unique=True,
        postgresql_where=sa.text("form_group_id IS NOT NULL AND status IN ('pending', 'skipped')"),
    )


def downgrade() -> None:
    op.drop_index("uq_active_form_group_reminder", table_name="reminders")
    op.drop_index(op.f("ix_reminders_form_group_id"), table_name="reminders")
    op.drop_constraint("fk_reminders_form_group_id_form_groups", "reminders", type_="foreignkey")
    op.drop_column("reminders", "form_group_id")

    op.drop_index(op.f("ix_answers_submission_id"), table_name="answers")
    op.drop_constraint("fk_answers_submission_id_answer_submissions", "answers", type_="foreignkey")
    op.drop_column("answers", "submission_id")

    op.drop_index(op.f("ix_answer_submissions_form_group_id"), table_name="answer_submissions")
    op.drop_index(op.f("ix_answer_submissions_user_id"), table_name="answer_submissions")
    op.drop_index(op.f("ix_answer_submissions_id"), table_name="answer_submissions")
    op.drop_table("answer_submissions")

    op.drop_index("uq_form_group_item_form", table_name="form_group_items")
    op.drop_index(op.f("ix_form_group_items_form_id"), table_name="form_group_items")
    op.drop_index(op.f("ix_form_group_items_group_id"), table_name="form_group_items")
    op.drop_index(op.f("ix_form_group_items_id"), table_name="form_group_items")
    op.drop_table("form_group_items")

    op.drop_index(op.f("ix_form_groups_user_id"), table_name="form_groups")
    op.drop_index(op.f("ix_form_groups_id"), table_name="form_groups")
    op.drop_table("form_groups")
