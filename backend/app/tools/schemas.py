# Built with Spec4 AI - https://spec4.ai
"""Pydantic request/response models for the tool_use_integration search endpoint."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    """Request body for POST /api/tools/search."""

    search_query: str = Field(min_length=1)


class SearchResultOut(BaseModel):
    """One ranked external search result, per tool_use_integration's Outputs schema."""

    title: str
    summary: str
    source: str
    rank: int


class AgentStepOut(BaseModel):
    """One observable step from the agent loop.

    Surfaced so the demo's progress trace reflects what the model actually
    did -- which tool it chose, what query it wrote, what came back -- rather
    than a cosmetic animation.
    """

    kind: str
    label: str
    detail: str


class SearchResponse(BaseModel):
    """Response body for POST /api/tools/search."""

    answer: str
    results: list[SearchResultOut]
    steps: list[AgentStepOut]
    queries: list[str]
    model: str
    iterations: int
