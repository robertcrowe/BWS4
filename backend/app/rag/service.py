# Built with Spec4 AI - https://spec4.ai
"""Orchestrates retrieval, threshold-gated generation, and the answer result."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.rag.answer import generate_answer
from backend.app.rag.citations import audit_citations
from backend.app.rag.retriever import (
    SIMILARITY_THRESHOLD,
    RetrievedPassage,
    retrieve_passages,
)
from backend.app.services import shared
from backend.app.services.generation import GenerationServiceError

#: Tag used on every shared_framework_services invocation the RAG app makes,
#: per the ServiceLogEntry domain fields.
RAG_APP_NAME = "RAG Example App"

NO_STRONG_MATCH_MESSAGE = (
    "No strong match found in this dataset for that question. This example "
    "uses a small, topic-limited reference dataset (space exploration "
    "facts) rather than open-domain knowledge, so try a question closer to "
    "one of the documents in the browser on the left."
)


class RagServiceError(Exception):
    """Raised when retrieval succeeded but generation is unavailable."""


@dataclass(frozen=True)
class AnswerResult:
    """The outcome of answering one question, ready for the API response.

    Attributes:
        answer: The answer text shown to the visitor.
        retrieved_passages: The retriever's top-N passages, in rank order.
        status: "low_relevance" when retrieval never cleared the similarity
            threshold (no generation was attempted), "grounded" when the model
            answered and cited at least one retrieved passage, "unsupported"
            when it answered but cited none of them. The last case is not an
            error -- it is usually the model correctly reporting that the
            passages don't answer the question -- but it must not be presented
            as a grounded answer.
        cited_passages: 1-based positions in `retrieved_passages` that the
            answer actually cites.
        unresolved_citations: Citation markers in the answer that point at no
            retrieved passage at all.
    """

    answer: str
    retrieved_passages: list[RetrievedPassage]
    status: Literal["grounded", "unsupported", "low_relevance"]
    cited_passages: list[int] = field(default_factory=list)
    unresolved_citations: list[int] = field(default_factory=list)


async def answer_question(session: AsyncSession, question: str) -> AnswerResult:
    """Retrieve passages for a question, then generate a grounded answer.

    Routes the representation (query embedding) and generation capabilities
    through the shared_framework_services interface for usage-limit
    enforcement and cross-app request logging, without changing the
    underlying retrieval/generation logic in retriever.py/answer.py.

    Google-style docstring per project convention.

    Args:
        session: An async SQLAlchemy session to query dataset_embeddings.
        question: The visitor's natural-language question.

    Returns:
        The generated (or below-threshold graceful) answer result.

    Raises:
        RagServiceError: If a shared capability needed to answer this
            question (representation, or generation once retrieval clears
            the similarity threshold) is unavailable, or if retrieval found
            strong matches but generation itself then failed.
    """
    try:
        await shared.reserve_capability(
            session, shared.CAPABILITY_REPRESENTATION, app_name=RAG_APP_NAME
        )
    except shared.ServiceUnavailableError as exc:
        raise RagServiceError(str(exc)) from exc

    passages = await retrieve_passages(session, question)
    await shared.log_invocation(
        session,
        app_name=RAG_APP_NAME,
        capability=shared.CAPABILITY_REPRESENTATION,
        summary=f"Embedded a visitor question for retrieval ({len(passages)} passage(s) found)",
    )

    if passages and passages[0].similarity_score >= SIMILARITY_THRESHOLD:
        try:
            await shared.reserve_capability(
                session, shared.CAPABILITY_GENERATION, app_name=RAG_APP_NAME
            )
        except shared.ServiceUnavailableError as exc:
            raise RagServiceError(str(exc)) from exc

    result = build_answer(question, passages)

    # Anything that isn't "low_relevance" reached the model, so it must be
    # recorded as a generation regardless of how the citation audit went --
    # an uncited answer costs exactly as much quota as a cited one.
    if result.status != "low_relevance":
        await shared.record_generation_request(
            session,
            app_name=RAG_APP_NAME,
            prompt_excerpt=question,
            response_excerpt=result.answer,
        )
        await shared.log_invocation(
            session,
            app_name=RAG_APP_NAME,
            capability=shared.CAPABILITY_GENERATION,
            summary=(
                f"Generated a RAG answer ({result.status}), citing "
                f"{len(result.cited_passages)} of {len(result.retrieved_passages)} passage(s)"
            ),
        )

    return result


def build_answer(question: str, passages: list[RetrievedPassage]) -> AnswerResult:
    """Apply the similarity threshold and, if it's cleared, generate an answer.

    Below the threshold, no generation call is made at all: forcing an
    answer from weak or absent passages would contradict the rag_example_app
    specification's below-threshold failure-mode mitigation.

    Above the threshold, the generated answer's citations are audited before
    the result claims to be grounded. The threshold alone can't support that
    claim: it rejects only questions with little *lexical* overlap with the
    dataset, so an on-topic question the dataset simply cannot answer (asking
    about the first woman in space, when the dataset covers Gagarin) clears it
    comfortably. Whether the model then cited a real passage is the closest
    checkable proxy for grounding available without a second model call.

    Args:
        question: The visitor's natural-language question.
        passages: The retriever's top-N passages for this question.

    Returns:
        A "low_relevance" result with a graceful message when no passage
        clears SIMILARITY_THRESHOLD, otherwise a generated result marked
        "grounded" or "unsupported" according to its citations.

    Raises:
        RagServiceError: If generation is attempted but the shared
            generation capability fails.
    """
    if not passages or passages[0].similarity_score < SIMILARITY_THRESHOLD:
        return AnswerResult(
            answer=NO_STRONG_MATCH_MESSAGE,
            retrieved_passages=passages,
            status="low_relevance",
        )

    try:
        answer_text = generate_answer(question, passages)
    except GenerationServiceError as exc:
        raise RagServiceError(str(exc)) from exc

    audit = audit_citations(answer_text, len(passages))
    return AnswerResult(
        answer=answer_text,
        retrieved_passages=passages,
        status="grounded" if audit.is_grounded else "unsupported",
        cited_passages=audit.cited,
        unresolved_citations=audit.unresolved,
    )
