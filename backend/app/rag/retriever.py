# Built with Spec4 AI - https://spec4.ai
"""Top-N passage retrieval against dataset_embeddings via pgvector cosine distance."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import DatasetEmbedding
from backend.app.services.embedding import embed_text

TOP_N = 3

#: Below this cosine similarity, a passage is treated as not a strong match
#: (see the rag_example_app specification's below-threshold failure mode).
SIMILARITY_THRESHOLD = 0.35


@dataclass(frozen=True)
class RetrievedPassage:
    """A single passage returned by the retriever, ranked by similarity.

    Attributes:
        passage_id: Stable identifier of the source passage.
        source_title: Title of the document the passage was drawn from.
        text_excerpt: The passage's text content.
        similarity_score: Cosine similarity to the query, in [-1, 1] (higher
            is more similar); computed as ``1 - cosine_distance``.
    """

    passage_id: str
    source_title: str
    text_excerpt: str
    similarity_score: float


async def retrieve_passages(
    session: AsyncSession, question: str, top_n: int = TOP_N
) -> list[RetrievedPassage]:
    """Find the top-N dataset passages most similar to a question's embedding.

    Reuses the shared embedding service to embed the question, then ranks
    dataset_embeddings rows via pgvector's cosine-distance operator so the
    ordering happens in the database rather than in application code.

    Google-style docstring per project convention.

    Args:
        session: An async SQLAlchemy session to query through.
        question: The visitor's natural-language question.
        top_n: Maximum number of passages to return.

    Returns:
        Passages ordered from most to least similar to the question.
    """
    query_vector = embed_text(question)
    distance = DatasetEmbedding.embedding.cosine_distance(query_vector)

    statement = (
        select(DatasetEmbedding, distance.label("distance"))
        .order_by(distance)
        .limit(top_n)
    )
    result = await session.execute(statement)

    return [
        RetrievedPassage(
            passage_id=row.passage_id,
            source_title=row.source_title,
            text_excerpt=row.text_excerpt,
            similarity_score=1 - dist,
        )
        for row, dist in result.all()
    ]
