# Built with Spec4 AI - https://spec4.ai

from typing import Any
import asyncio
import math

from backend.app.db.models import DatasetEmbedding
from backend.app.rag.index_dataset import build_embedded_passages
from backend.app.rag.retriever import retrieve_passages
from backend.app.services.embedding import embed_text


class _FakeRetrievalResult:
    def __init__(self, rows: list[tuple[DatasetEmbedding, float]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[DatasetEmbedding, float]]:
        return self._rows


class _FakeSession:
    """Returns pre-computed rows, mirroring the test_health.py fake-session
    pattern -- the actual ranking happens in Postgres via pgvector, which
    isn't available here, so ranking quality is verified separately below."""

    def __init__(self, rows: list[tuple[DatasetEmbedding, float]]) -> None:
        self._rows = rows

    async def execute(self, *_args: object, **_kwargs: object) -> _FakeRetrievalResult:
        return _FakeRetrievalResult(self._rows)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    return dot / (norm_a * norm_b)


def test_retrieve_passages_maps_ranked_rows_to_similarity_scores() -> None:
    rows = [
        (
            DatasetEmbedding(
                passage_id="voyager-1-1",
                source_title="Voyager 1",
                text_excerpt="Voyager 1 launched in 1977.",
                embedding=[0.0] * 384,
            ),
            0.1,
        ),
        (
            DatasetEmbedding(
                passage_id="apollo-11-1",
                source_title="Apollo 11",
                text_excerpt="Apollo 11 landed on the Moon in 1969.",
                embedding=[0.0] * 384,
            ),
            0.4,
        ),
    ]
    session: Any = _FakeSession(rows)

    passages = asyncio.run(retrieve_passages(session, "When did Voyager 1 launch?"))

    assert [p.passage_id for p in passages] == ["voyager-1-1", "apollo-11-1"]
    assert passages[0].similarity_score == 1 - 0.1
    assert passages[1].similarity_score == 1 - 0.4


def test_retrieval_ranking_surfaces_the_topically_relevant_passage_in_top_k() -> None:
    """Curated question/passage eval: for an in-dataset question, the top-k
    ranked passages (by cosine similarity, mirroring pgvector's `<=>`
    ordering) should include a passage from the topically relevant document.
    """
    embedded_passages = build_embedded_passages()
    question_embedding = embed_text("When did Voyager 1 launch and what is it doing now?")

    ranked = sorted(
        embedded_passages,
        key=lambda item: _cosine_similarity(question_embedding, item.embedding),
        reverse=True,
    )
    top_k = ranked[:3]

    assert any("voyager" in item.passage.source_title.lower() for item in top_k)
