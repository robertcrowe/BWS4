# Built with Spec4 AI - https://spec4.ai
"""One-off script: chunk the reference dataset, embed each passage, and write
the results to dataset_embeddings (logging each computation to
text_representations).

Run once after applying the 0002 migration and before applying the 0003
(HNSW index) migration -- per the phase 3 risk assessment, the HNSW index
should build against real data rather than an empty table:

    uv run alembic -c backend/alembic.ini upgrade 0002
    uv run python backend/app/rag/index_dataset.py
    uv run alembic -c backend/alembic.ini upgrade 0003

Safe to re-run: existing rows are cleared before repopulating.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import structlog
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.db.models import DatasetEmbedding, TextRepresentation
from backend.app.db.session import async_session_factory
from backend.app.rag.chunking import Passage, chunk_document, embedding_text
from backend.app.rag.dataset_loader import load_dataset_documents
from backend.app.services.embedding import EMBEDDING_DIMENSIONS, embed_text

logger = structlog.get_logger()


@dataclass(frozen=True)
class EmbeddedPassage:
    """A chunked passage paired with its computed embedding vector."""

    passage: Passage
    embedding: list[float]


def build_embedded_passages() -> list[EmbeddedPassage]:
    """Chunk every dataset document and embed each resulting passage.

    Touches no database state, so it can be exercised directly in tests
    without a live Postgres connection.

    Google-style docstring per project convention.

    Returns:
        One EmbeddedPassage per passage the chunking pipeline produces,
        across every document in the reference dataset.
    """
    embedded: list[EmbeddedPassage] = []
    for document in load_dataset_documents():
        for passage in chunk_document(document.title, document.text):
            # embedding_text(), not text_excerpt: the vector needs the source
            # title that the excerpt alone no longer carries.
            embedded.append(
                EmbeddedPassage(passage=passage, embedding=embed_text(embedding_text(passage)))
            )
    return embedded


async def index_dataset(session: AsyncSession) -> int:
    """Populate dataset_embeddings and text_representations from the dataset.

    Clears any existing rows first so the script is safe to re-run.

    Args:
        session: An async SQLAlchemy session to write through.

    Returns:
        The number of passages written.
    """
    embedded_passages = build_embedded_passages()
    model_name = get_settings().embedding_model_name

    await session.execute(delete(DatasetEmbedding))
    await session.execute(delete(TextRepresentation))

    for item in embedded_passages:
        session.add(
            DatasetEmbedding(
                passage_id=item.passage.passage_id,
                source_title=item.passage.source_title,
                text_excerpt=item.passage.text_excerpt,
                embedding=item.embedding,
            )
        )
        session.add(
            TextRepresentation(
                source_type="dataset_passage",
                source_reference=item.passage.passage_id,
                model_name=model_name,
                dimensions=EMBEDDING_DIMENSIONS,
            )
        )

    await session.commit()
    logger.info("dataset_indexing_completed", passage_count=len(embedded_passages))
    return len(embedded_passages)


async def _main() -> None:
    async with async_session_factory() as session:
        count = await index_dataset(session)
    print(f"Indexed {count} passages into dataset_embeddings.")


if __name__ == "__main__":
    asyncio.run(_main())
