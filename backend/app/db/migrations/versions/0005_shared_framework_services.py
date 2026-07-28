# Built with Spec4 AI - https://spec4.ai
"""create shared_framework_services tables

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-26

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "language_generation_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("app_name", sa.String(length=100), nullable=False),
        sa.Column("prompt_excerpt", sa.Text(), nullable=False),
        sa.Column("response_excerpt", sa.Text(), nullable=False),
        sa.Column("model_name", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_table(
        "stored_records",
        sa.Column("key", sa.String(length=255), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("written_by", sa.String(length=100), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_table(
        "usage_limits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("capability", sa.String(length=50), nullable=False),
        sa.Column("used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cap", sa.Integer(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_usage_limits_capability",
        "usage_limits",
        ["capability"],
        unique=True,
    )

    op.create_table(
        "service_log_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("app_name", sa.String(length=100), nullable=False),
        sa.Column("capability", sa.String(length=50), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_service_log_entries_timestamp",
        "service_log_entries",
        ["timestamp"],
    )


def downgrade() -> None:
    op.drop_index("ix_service_log_entries_timestamp", table_name="service_log_entries")
    op.drop_table("service_log_entries")

    op.drop_index("ix_usage_limits_capability", table_name="usage_limits")
    op.drop_table("usage_limits")

    op.drop_table("stored_records")
    op.drop_table("language_generation_requests")
