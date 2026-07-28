# Built with Spec4 AI - https://spec4.ai
"""Orchestrates retrieval, threshold-gated generation, and the answer result."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.rag.answer import generate_answer
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
    """The outcome of answering one question, ready for the API response."""

    answer: str
    retrieved_passages: list[RetrievedPassage]
    status: Literal["grounded", "low_relevance"]


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

    if result.status == "grounded":
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
            summary="Generated a grounded RAG answer",
        )

    return result


def build_answer(question: str, passages: list[RetrievedPassage]) -> AnswerResult:
    """Apply the similarity threshold and, if it's cleared, generate an answer.

    Below the threshold, no generation call is made at all: forcing an
    answer from weak or absent passages would contradict the rag_example_app
    specification's below-threshold failure-mode mitigation.

    Args:
        question: The visitor's natural-language question.
        passages: The retriever's top-N passages for this question.

    Returns:
        A "low_relevance" result with a graceful message when no passage
        clears SIMILARITY_THRESHOLD, otherwise a "grounded" generated result.

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

    return AnswerResult(answer=answer_text, retrieved_passages=passages, status="grounded")
