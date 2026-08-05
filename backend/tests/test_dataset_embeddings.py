# Built with Spec4 AI - https://spec4.ai

from typing import Any
import asyncio
import math

from backend.app.db.models import DatasetEmbedding, TextRepresentation
from backend.app.rag.chunking import chunk_document
from backend.app.rag.dataset_loader import load_dataset_documents
from backend.app.rag.index_dataset import build_embedded_passages, index_dataset
from backend.app.services.embedding import EMBEDDING_DIMENSIONS


class _FakeResult:
    def scalars(self) -> "_FakeResult":
        return self

    def all(self) -> list[object]:
        return []


class _FakeAsyncSession:
    """Records ORM writes in memory, mirroring the test_health.py fake-session
    pattern so the indexing script can be verified without a live database.
    """

    def __init__(self) -> None:
        self.added: list[object] = []
        self.committed = False

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def execute(self, *_args: object, **_kwargs: object) -> _FakeResult:
        return _FakeResult()

    async def commit(self) -> None:
        self.committed = True


def _expected_passage_count() -> int:
    return sum(len(chunk_document(doc.title, doc.text)) for doc in load_dataset_documents())


def _cosine_distance(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    return 1 - dot / (norm_a * norm_b)


def test_index_dataset_writes_one_dataset_embedding_and_representation_row_per_passage() -> None:
    expected_count = _expected_passage_count()
    session: Any = _FakeAsyncSession()

    written_count = asyncio.run(index_dataset(session))

    assert written_count == expected_count
    assert session.committed is True

    dataset_rows = [obj for obj in session.added if isinstance(obj, DatasetEmbedding)]
    representation_rows = [obj for obj in session.added if isinstance(obj, TextRepresentation)]

    assert len(dataset_rows) == expected_count
    assert len(representation_rows) == expected_count
    assert all(len(row.embedding) == EMBEDDING_DIMENSIONS for row in dataset_rows)
    assert all(row.passage_id for row in dataset_rows)
    assert len({row.passage_id for row in dataset_rows}) == expected_count


def test_cosine_distance_query_against_a_known_passages_own_embedding_returns_itself() -> None:
    """Emulates pgvector's `embedding <=> :query_vector` cosine-distance
    ordering in plain Python against the same vectors index_dataset.py would
    write, since no live Postgres/pgvector instance is available here."""
    embedded_passages = build_embedded_passages()
    target = embedded_passages[len(embedded_passages) // 2]

    ranked = sorted(
        embedded_passages,
        key=lambda item: _cosine_distance(target.embedding, item.embedding),
    )

    assert ranked[0].passage.passage_id == target.passage.passage_id
    assert _cosine_distance(target.embedding, ranked[0].embedding) < 1e-6
