"""add reminders

Revision ID: 20260522_0004
Revises: 20260522_0003
Create Date: 2026-05-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op


revision: str = "20260522_0004"
down_revision: str | None = "20260522_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reminders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("form_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("retry_delay_seconds", sa.Integer(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("skip_count", sa.Integer(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["form_id"], ["forms.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_reminders_form_id"), "reminders", ["form_id"], unique=False)
    op.create_index(op.f("ix_reminders_id"), "reminders", ["id"], unique=False)
    op.create_index(op.f("ix_reminders_next_run_at"), "reminders", ["next_run_at"], unique=False)
    op.create_index(op.f("ix_reminders_status"), "reminders", ["status"], unique=False)
    op.create_index(op.f("ix_reminders_user_id"), "reminders", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_reminders_user_id"), table_name="reminders")
    op.drop_index(op.f("ix_reminders_status"), table_name="reminders")
    op.drop_index(op.f("ix_reminders_next_run_at"), table_name="reminders")
    op.drop_index(op.f("ix_reminders_id"), table_name="reminders")
    op.drop_index(op.f("ix_reminders_form_id"), table_name="reminders")
    op.drop_table("reminders")
