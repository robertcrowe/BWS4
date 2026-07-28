# Built with Spec4 AI - https://spec4.ai
"""create dataset_embeddings and text_representations tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-26

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMBEDDING_DIMENSIONS = 384


def upgrade() -> None:
    op.create_table(
        "dataset_embeddings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("passage_id", sa.String(length=255), nullable=False),
        sa.Column("source_title", sa.String(length=255), nullable=False),
        sa.Column("text_excerpt", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIMENSIONS), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_dataset_embeddings_passage_id",
        "dataset_embeddings",
        ["passage_id"],
        unique=True,
    )

    op.create_table(
        "text_representations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("source_reference", sa.String(length=255), nullable=False),
        sa.Column("model_name", sa.String(length=255), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("text_representations")
    op.drop_index("ix_dataset_embeddings_passage_id", table_name="dataset_embeddings")
    op.drop_table("dataset_embeddings")
