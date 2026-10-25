# Built with Spec4 AI - https://spec4.ai
"""The retrieval route: the RAG example's retriever, then its answer step.

Both calls go through the RAG slice's existing entry points, unmodified:

- `rag.retriever.retrieve_passages` -- embeds the request with the shared
  in-process model and ranks `dataset_embeddings` by cosine distance;
- `rag.service.build_answer` -- applies the RAG app's similarity threshold and,
  only if a passage clears it, makes exactly one generation call and audits
  the citations.

`rag.service.answer_question` is *not* used: it charges the shared usage gate
a generation unit of its own, and a Router run already holds its two. Its inner
`build_answer` makes at most one generation call, which is exactly the run's
second unit, so the 2-unit ceiling holds.

When nothing clears the threshold the dataset does not cover the request, and
the route says so -- as the RAG app does -- without calling a model.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Final, Literal

import structlog

from backend.app.rag import retriever as rag_retriever
from backend.app.rag import service as rag_service
from backend.app.router.search_route import SessionFactory

logger = structlog.get_logger()

NOT_COVERED_MESSAGE: Final[str] = (
    "The space dataset does not cover this request: no retrieved passage cleared "
    "the RAG example's similarity threshold, so no answer was generated. The "
    "closest passages are listed below."
)
COMPOSE_FAILED_MESSAGE: Final[str] = (
    "Retrieval ran but an answer could not be composed: every model in the "
    "shared generation chain failed. The retrieved passages are listed below."
)
RETRIEVAL_FAILED_MESSAGE: Final[str] = (
    "Retrieval unavailable: the indexed dataset could not be searched. No "
    "passages are shown rather than invented ones."
)


@dataclass(frozen=True)
class Passage:
    """One retrieved passage as shown on the page.

    Attributes:
        index: 1-based rank; what the answer's `[n]` cites.
        title: The source document's title.
        excerpt: The passage text.
        similarity: Cosine similarity to the request.
        cited: Whether the answer cites it.
    """

    index: int
    title: str
    excerpt: str
    similarity: float
    cited: bool


@dataclass(frozen=True)
class RetrievalOutcome:
    """What the retrieval route produced.

    Attributes:
        status: `grounded`, `unsupported`, `low_relevance`, `compose_failed`
            or `retrieval_failed`.
        elapsed_ms: The route's own measured time.
        passages: The retrieved passages, in rank order.
        answer_text: The generated answer, when one was composed.
        model: The slug that composed it.
        unresolved_citations: Cited indices that match no passage.
        message: The candid message for a non-answer.
        retrievals: Retrievals made (0 or 1).
        model_calls: Generation calls made (0 or 1).
    """

    status: Literal[
        "grounded", "unsupported", "low_relevance", "compose_failed", "retrieval_failed"
    ]
    elapsed_ms: int
    passages: tuple[Passage, ...] = ()
    answer_text: str | None = None
    model: str | None = None
    unresolved_citations: tuple[int, ...] = ()
    message: str | None = None
    retrievals: int = 0
    model_calls: int = 0


def _passages(
    retrieved: list[rag_retriever.RetrievedPassage], cited: set[int]
) -> tuple[Passage, ...]:
    return tuple(
        Passage(
            index=index,
            title=passage.source_title,
            excerpt=passage.text_excerpt,
            similarity=round(passage.similarity_score, 3),
            cited=index in cited,
        )
        for index, passage in enumerate(retrieved, start=1)
    )


async def answer(request: str, session_factory: SessionFactory) -> RetrievalOutcome:
    """Retrieve passages and, if any is relevant, compose one answer.

    Args:
        request: The visitor's request.
        session_factory: Opens a session for the retriever's read.

    Returns:
        The outcome, candid on every path.
    """
    started = time.perf_counter()

    def elapsed() -> int:
        return round((time.perf_counter() - started) * 1000)

    try:
        async with session_factory() as session:
            retrieved = await rag_retriever.retrieve_passages(session, request)
    except Exception:  # noqa: BLE001 - any failure to read the index is reported, not raised
        logger.exception("router_retrieval_failed")
        return RetrievalOutcome(
            status="retrieval_failed",
            elapsed_ms=elapsed(),
            message=RETRIEVAL_FAILED_MESSAGE,
        )

    try:
        result = await asyncio.to_thread(rag_service.build_answer, request, retrieved)
    except rag_service.RagServiceError:
        logger.warning("router_retrieval_compose_failed")
        return RetrievalOutcome(
            status="compose_failed",
            elapsed_ms=elapsed(),
            passages=_passages(retrieved, set()),
            message=COMPOSE_FAILED_MESSAGE,
            retrievals=1,
        )

    if result.status == "low_relevance":
        return RetrievalOutcome(
            status="low_relevance",
            elapsed_ms=elapsed(),
            passages=_passages(retrieved, set()),
            message=NOT_COVERED_MESSAGE,
            retrievals=1,
        )

    logger.info(
        "router_retrieval_answered",
        status=result.status,
        model=result.model,
        passages=len(retrieved),
    )
    return RetrievalOutcome(
        status=result.status,
        elapsed_ms=elapsed(),
        passages=_passages(result.retrieved_passages, set(result.cited_passages)),
        answer_text=result.answer,
        model=result.model,
        unresolved_citations=tuple(result.unresolved_citations),
        retrievals=1,
        model_calls=1,
    )
