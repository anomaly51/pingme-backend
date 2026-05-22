"""add product ready form and reminder fields

Revision ID: 20260522_0006
Revises: 20260522_0005
Create Date: 2026-05-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op


revision: str = "20260522_0006"
down_revision: str | None = "20260522_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("avatar_url", sa.String(length=500), nullable=True))
    op.add_column("users", sa.Column("push_token", sa.String(length=500), nullable=True))
    op.add_column(
        "users",
        sa.Column("timezone", sa.String(length=64), server_default="UTC", nullable=False),
    )
    op.add_column(
        "users",
        sa.Column(
            "notification_preferences",
            sa.JSON(),
            server_default='{"realtime": true, "email": false, "push": false}',
            nullable=False,
        ),
    )

    op.add_column("forms", sa.Column("description", sa.String(length=1000), nullable=True))
    op.add_column(
        "forms",
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
    )
    op.add_column("forms", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))

    op.add_column(
        "reminders",
        sa.Column("enqueue_status", sa.String(length=32), server_default="pending", nullable=False),
    )
    op.add_column(
        "reminders",
        sa.Column("last_enqueue_error", sa.String(length=1000), nullable=True),
    )
    op.add_column("reminders", sa.Column("enqueued_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "uq_active_form_reminder",
        "reminders",
        ["user_id", "form_id"],
        unique=True,
        postgresql_where=sa.text("form_id IS NOT NULL AND status IN ('pending', 'skipped')"),
    )


def downgrade() -> None:
    op.drop_index("uq_active_form_reminder", table_name="reminders")
    op.drop_column("reminders", "enqueued_at")
    op.drop_column("reminders", "last_enqueue_error")
    op.drop_column("reminders", "enqueue_status")
    op.drop_column("forms", "archived_at")
    op.drop_column("forms", "is_active")
    op.drop_column("forms", "description")
    op.drop_column("users", "notification_preferences")
    op.drop_column("users", "timezone")
    op.drop_column("users", "push_token")
    op.drop_column("users", "avatar_url")
