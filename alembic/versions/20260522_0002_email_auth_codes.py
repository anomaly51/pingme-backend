"""add email auth codes

Revision ID: 20260522_0002
Revises: 20260521_0001
Create Date: 2026-05-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op


revision: str = "20260522_0002"
down_revision: str | None = "20260521_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "email_auth_codes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("code_hash", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_email_auth_codes_email"),
        "email_auth_codes",
        ["email"],
        unique=False,
    )
    op.create_index(
        op.f("ix_email_auth_codes_id"),
        "email_auth_codes",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_email_auth_codes_purpose"),
        "email_auth_codes",
        ["purpose"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_email_auth_codes_purpose"), table_name="email_auth_codes")
    op.drop_index(op.f("ix_email_auth_codes_id"), table_name="email_auth_codes")
    op.drop_index(op.f("ix_email_auth_codes_email"), table_name="email_auth_codes")
    op.drop_table("email_auth_codes")
