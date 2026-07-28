# Built with Spec4 AI - https://spec4.ai
"""add hnsw index on dataset_embeddings.embedding

Run this migration only after backend/app/rag/index_dataset.py has populated
dataset_embeddings at least once: HNSW index build quality and speed depend
on the data present at build time, and Neon's free tier can build a slow or
ineffective index against an empty table (see phase 3 risk assessment).

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-26

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX ix_dataset_embeddings_embedding_hnsw "
        "ON dataset_embeddings USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64);"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_dataset_embeddings_embedding_hnsw;")
