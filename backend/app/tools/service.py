# Built with Spec4 AI - https://spec4.ai
"""Orchestrates the tool_use_integration search capability: usage-limit
enforcement, the agent loop, SearchQuery persistence, and cross-app logging,
reusing the shared_framework_services interface rather than adding a parallel
logging path.

The routing decision lives in tools/agent.py, where the model makes it from a
tool schema. This module owns everything the loop must not know about: quota,
persistence, and logging. It injects `execute_search` into the loop so those
concerns wrap each search the model chooses to run.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import SearchQuery
from backend.app.services import shared
from backend.app.tools.agent import AgentError, AgentStep, run_agent
from backend.app.tools.exa_client import ExaClientError, ExaRateLimitError, ExaResult, search

logger = structlog.get_logger()

#: Tag used on every shared_framework_services invocation the tool-use app
#: makes, per the ServiceLogEntry domain fields.
TOOL_USE_APP_NAME = "Tool-Use Example App"

#: The tool_use_integration failure mode's visitor-facing message: shown
#: whenever the search tool can't be reached, whether from our own usage cap
#: or Exa's own rate limit, so the demonstration never fails silently.
UNAVAILABLE_MESSAGE = (
    "The search tool is temporarily unavailable — it has reached its "
    "free-tier usage limit for now. Please try again later."
)

#: Shown when the free-model chain itself is exhausted, which is a different
#: operator problem from a search cap and shouldn't be reported as one.
AGENT_UNAVAILABLE_MESSAGE = (
    "The agent's language model is temporarily unavailable — every free-tier "
    "model in the chain refused the request. Please try again later."
)


class ToolServiceError(Exception):
    """Raised when a search request can't be fulfilled; message is visitor-facing."""


@dataclass(frozen=True)
class RankedResult:
    """One search result, ranked for display."""

    title: str
    summary: str
    source: str
    rank: int


@dataclass(frozen=True)
class AgentSearchRun:
    """A completed agent run, shaped for the API layer."""

    answer: str
    results: list[RankedResult]
    steps: list[AgentStep]
    queries: list[str]
    model: str
    iterations: int


async def run_search(session: AsyncSession, search_query: str) -> AgentSearchRun:
    """Run the tool-use agent loop over a visitor's question.

    Google-style docstring per project convention.

    Args:
        session: An async SQLAlchemy session for persistence/usage/logging.
        search_query: The visitor's question. It is NOT sent to the search API
            as-is -- the agent decides whether to search and writes its own
            query.

    Returns:
        The completed run: the model's answer, the deduplicated results it
        saw, its step trace, and the queries it wrote.

    Raises:
        ToolServiceError: If a usage cap has been reached, the Exa Search API
            call fails, or the free-model chain is exhausted -- in every case
            with a clear visitor-facing message rather than a raw exception.
    """
    # Persisted unconditionally: the row represents the invocation itself, not
    # a successful search. Each query the model then writes is persisted too,
    # inside execute_search below.
    session.add(SearchQuery(text=search_query))
    await session.commit()

    # One reservation covers every model turn in this loop. The loop is bounded
    # by agent.MAX_ITERATIONS, so a single request can't drain the quota.
    try:
        await shared.reserve_capability(
            session, shared.CAPABILITY_GENERATION, app_name=TOOL_USE_APP_NAME
        )
    except shared.ServiceUnavailableError as exc:
        raise ToolServiceError(AGENT_UNAVAILABLE_MESSAGE) from exc

    async def execute_search(query: str) -> list[ExaResult]:
        """Reserve, persist, and run one model-authored search."""
        await shared.reserve_capability(
            session, shared.CAPABILITY_SEARCH, app_name=TOOL_USE_APP_NAME
        )
        session.add(SearchQuery(text=query))
        await session.commit()
        return await search(query)

    try:
        run = await run_agent(search_query, execute_search=execute_search)
    except shared.ServiceUnavailableError as exc:
        await _log_failure(session, search_query, "usage cap reached")
        raise ToolServiceError(UNAVAILABLE_MESSAGE) from exc
    except (ExaRateLimitError, ExaClientError) as exc:
        await _log_failure(session, search_query, "search API unavailable")
        raise ToolServiceError(UNAVAILABLE_MESSAGE) from exc
    except AgentError as exc:
        logger.error("tool_agent_failed", error=str(exc))
        await _log_failure(session, search_query, "model chain exhausted")
        raise ToolServiceError(AGENT_UNAVAILABLE_MESSAGE) from exc

    await shared.record_generation_request(
        session,
        app_name=TOOL_USE_APP_NAME,
        prompt_excerpt=search_query,
        response_excerpt=run.answer,
        model_name=run.model,
    )
    await shared.log_invocation(
        session,
        app_name=TOOL_USE_APP_NAME,
        capability=shared.CAPABILITY_SEARCH,
        summary=(
            f"Agent answered '{search_query[:50]}' using "
            f"{len(run.queries)} search(es), {len(run.results)} result(s)"
        ),
    )

    return AgentSearchRun(
        answer=run.answer,
        results=[
            RankedResult(title=r.title, summary=r.summary, source=r.source, rank=index + 1)
            for index, r in enumerate(run.results)
        ],
        steps=run.steps,
        queries=run.queries,
        model=run.model,
        iterations=run.iterations,
    )


async def _log_failure(session: AsyncSession, search_query: str, reason: str) -> None:
    """Record a failed invocation on the shared cross-app request log.

    Args:
        session: An async SQLAlchemy session to write through.
        search_query: The visitor's original question.
        reason: A short description of what went wrong.
    """
    await shared.log_invocation(
        session,
        app_name=TOOL_USE_APP_NAME,
        capability=shared.CAPABILITY_SEARCH,
        summary=f"Agent run failed for '{search_query[:50]}' ({reason})",
    )
