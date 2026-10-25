# Built with Spec4 AI - https://spec4.ai
"""The titles of the documents the RAG retriever actually indexes.

The retriever exposes no title listing, and `backend/app/rag/` is not to be
modified, so this reads `dataset_embeddings` directly -- read-only, one
`SELECT DISTINCT`. It reads the table the retriever ranks rather than the
dataset files on disk, because a file that was never indexed is not something
the retrieval route can answer from.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import DatasetEmbedding


async def load_indexed_document_titles(session: AsyncSession) -> list[str]:
    """List the distinct source titles in `dataset_embeddings`.

    Args:
        session: An async session. Only read from.

    Returns:
        The titles, sorted.
    """
    statement = select(DatasetEmbedding.source_title).distinct()
    result = await session.execute(statement)
    return sorted(str(title) for title in result.scalars().all())
