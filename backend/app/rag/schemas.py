# Built with Spec4 AI - https://spec4.ai
"""Pydantic request/response models for the rag_example_app structured output."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class RagAskRequest(BaseModel):
    """Request body for POST /api/rag/ask."""

    user_question: str = Field(min_length=1)


class RetrievedPassageOut(BaseModel):
    """One retrieved passage as shown to the visitor, citation-numbered."""

    passage_id: str
    source_title: str
    text_excerpt: str
    similarity_score: float


class RagAskResponse(BaseModel):
    """Response body for POST /api/rag/ask.

    Matches the rag_example_app capability's Outputs/Mechanisms schema: an
    answer grounded in, and citing, the retrieved passages that informed it.

    `status` distinguishes retrieval failure ("low_relevance") from grounding
    failure ("unsupported"), and `cited_passages`/`unresolved_citations`
    carry the audit behind that distinction so the client can report what was
    actually cited rather than inferring grounding from a similarity score.
    """

    answer: str
    retrieved_passages: list[RetrievedPassageOut]
    status: Literal["grounded", "unsupported", "low_relevance"]
    cited_passages: list[int] = []
    unresolved_citations: list[int] = []


class LlmAnswer(BaseModel):
    """The minimal structured output the generation model must produce.

    retrieved_passages metadata (title, excerpt, similarity_score) is known
    server-side from retrieval, so the model is only asked for the answer
    text -- keeping its structured-output contract small and less prone to
    schema-validation failures.
    """

    answer: str


class DatasetDocumentOut(BaseModel):
    """One reference-dataset document for the rag_dataset_browser surface."""

    title: str
    text: str
