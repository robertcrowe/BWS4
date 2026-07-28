# Built with Spec4 AI - https://spec4.ai
"""create rag_interactions table

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-26

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "rag_interactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("retrieved_passages", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_rag_interactions_submitted_at",
        "rag_interactions",
        ["submitted_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_rag_interactions_submitted_at", table_name="rag_interactions")
    op.drop_table("rag_interactions")
