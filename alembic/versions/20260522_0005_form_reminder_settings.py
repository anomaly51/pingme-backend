"""add form reminder settings

Revision ID: 20260522_0005
Revises: 20260522_0004
Create Date: 2026-05-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op


revision: str = "20260522_0005"
down_revision: str | None = "20260522_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "forms",
        sa.Column("reminder_enabled", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column("forms", sa.Column("reminder_title", sa.String(), nullable=True))
    op.add_column(
        "forms",
        sa.Column("reminder_payload", sa.JSON(), server_default="{}", nullable=False),
    )
    op.add_column(
        "forms",
        sa.Column("skip_retry_delay_seconds", sa.Integer(), server_default="3600", nullable=False),
    )
    op.add_column(
        "forms",
        sa.Column(
            "delivery_retry_delay_seconds",
            sa.Integer(),
            server_default="3600",
            nullable=False,
        ),
    )
    op.add_column(
        "forms",
        sa.Column("last_reminder_scheduled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "reminders",
        sa.Column(
            "delivery_retry_delay_seconds",
            sa.Integer(),
            server_default="3600",
            nullable=False,
        ),
    )
    op.add_column(
        "reminders",
        sa.Column("delivery_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "reminders",
        sa.Column("last_delivered_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("reminders", "last_delivered_at")
    op.drop_column("reminders", "delivery_count")
    op.drop_column("reminders", "delivery_retry_delay_seconds")
    op.drop_column("forms", "last_reminder_scheduled_at")
    op.drop_column("forms", "delivery_retry_delay_seconds")
    op.drop_column("forms", "skip_retry_delay_seconds")
    op.drop_column("forms", "reminder_payload")
    op.drop_column("forms", "reminder_title")
    op.drop_column("forms", "reminder_enabled")
