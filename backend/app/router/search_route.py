# Built with Spec4 AI - https://spec4.ai
"""The search route: one Exa search, then one grounded generation call.

Calls the shared wrapper `services/web_search.search` directly, in-process --
no MCP, no new client, no tool registration -- and the shared generation
service once. The model never decides whether to search: code already did.

Every early exit is candid and spends nothing it did not need:

- the shared search cap refuses -> search unavailable, no search, no model;
- Exa fails -> search unavailable, no fabricated sources, no silent re-route;
- zero snippets -> a fixed "no usable results" notice, no model call;
- generation fails -> a fixed message with the raw snippet titles and links.

After generation, every `[n]` the answer cites is checked against the list:
an index with no snippet is stripped and reported, and any URL the model wrote
that is not one of the snippets' own is removed.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Callable, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.services import generation, shared, web_search
from backend.app.services.prompt_context import with_current_date
from backend.app.services.prompt_loader import load_prompt
from backend.app.services.untrusted import untrusted_block

logger = structlog.get_logger()

PROMPTS_DIR: Final[Path] = Path(__file__).parent / "prompts"
SEARCH_PROMPT_VERSION: Final[str] = "search_answer_v1"
#: Snippets passed to the model and shown on the page.
MAX_SNIPPETS: Final[int] = 5
#: Characters kept of each snippet.
MAX_SNIPPET_CHARS: Final[int] = 600
#: Response-length cap for the one generation call.
MAX_ANSWER_TOKENS: Final[int] = 350

NO_RESULTS_MESSAGE: Final[str] = (
    "The search ran but found no usable results for this request, so no answer "
    "was composed and no model call was made."
)
COMPOSE_FAILED_MESSAGE: Final[str] = (
    "The search ran but an answer could not be composed: every model in the "
    "shared generation chain failed. The sources it found are listed below."
)
SEARCH_CAP_MESSAGE: Final[str] = (
    "Search unavailable: the showcase's shared hourly search cap, used by every "
    "example app, is spent. No search was made and no sources are shown."
)

#: Opens a database session, as `async_session_factory` does.
SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]

_CITATION: Final = re.compile(r"\[(\d+)\]")
_URL: Final = re.compile(r"https?://[^\s)\]>]+")


@dataclass(frozen=True)
class Snippet:
    """One search result as shown and as given to the model.

    Attributes:
        index: 1-based position; what `[n]` cites.
        title: The page title.
        url: The page URL.
        excerpt: Exa's summary, trimmed.
        published_date: ISO date, or None when Exa could not tell.
        truncated: True when the excerpt was cut.
    """

    index: int
    title: str
    url: str
    excerpt: str
    published_date: str | None
    truncated: bool


@dataclass(frozen=True)
class SearchOutcome:
    """What the search route produced.

    Attributes:
        status: `answered`, `no_results`, `search_unavailable` or
            `compose_failed`.
        query: The exact query sent to Exa (None when no search was made).
        snippets: The trimmed results.
        answer_text: The checked answer, when one was composed.
        model: The slug that composed it.
        invalid_citations: Cited indices that matched no snippet, stripped.
        removed_urls: URLs the model wrote that were not a snippet's, removed.
        message: The fixed candid message for a non-answer.
        searches: Searches made (0 or 1).
        model_calls: Generation calls that produced an answer (0 or 1).
        elapsed_ms: The route's own measured time.
    """

    status: Literal["answered", "no_results", "search_unavailable", "compose_failed"]
    elapsed_ms: int
    query: str | None = None
    snippets: tuple[Snippet, ...] = ()
    answer_text: str | None = None
    model: str | None = None
    invalid_citations: tuple[int, ...] = ()
    removed_urls: tuple[str, ...] = ()
    message: str | None = None
    searches: int = 0
    model_calls: int = 0


def trim_results(results: Sequence[web_search.ExaResult]) -> tuple[Snippet, ...]:
    """Keep the top results, each excerpt cut to `MAX_SNIPPET_CHARS`.

    Args:
        results: Exa's results, in rank order.

    Returns:
        At most `MAX_SNIPPETS` snippets, numbered from 1.
    """
    snippets = []
    for index, result in enumerate(results[:MAX_SNIPPETS], start=1):
        excerpt = " ".join(result.summary.split())
        truncated = len(excerpt) > MAX_SNIPPET_CHARS
        if truncated:
            excerpt = excerpt[:MAX_SNIPPET_CHARS].rsplit(" ", 1)[0] + " …"
        snippets.append(
            Snippet(
                index=index,
                title=result.title,
                url=result.source,
                excerpt=excerpt,
                published_date=result.published_date,
                truncated=truncated,
            )
        )
    return tuple(snippets)


def build_user_prompt(request: str, snippets: Sequence[Snippet]) -> str:
    """Lay out the request and the numbered snippets, each delimited.

    Args:
        request: The visitor's request.
        snippets: The trimmed results.

    Returns:
        The user turn.
    """
    blocks = [untrusted_block("visitor request", request), "Snippets:"]
    for snippet in snippets:
        dated = snippet.published_date or "undated"
        content = f"{snippet.title} ({dated})\n{snippet.excerpt}"
        block = untrusted_block(f"snippet {snippet.index}", content)
        blocks.append(f"[{snippet.index}] {block}")
    return "\n\n".join(blocks)


def check_citations(
    text: str, snippets: Sequence[Snippet]
) -> tuple[str, tuple[int, ...], tuple[str, ...]]:
    """Strip citations to missing snippets and URLs that are not a snippet's.

    Args:
        text: The model's answer.
        snippets: The snippets it was given.

    Returns:
        The cleaned text, the invalid indices removed, and the URLs removed.
    """
    valid = {snippet.index for snippet in snippets}
    known_urls = {snippet.url for snippet in snippets}
    invalid: list[int] = []

    def drop_invalid(match: re.Match[str]) -> str:
        index = int(match.group(1))
        if index in valid:
            return match.group(0)
        invalid.append(index)
        return ""

    cleaned = _CITATION.sub(drop_invalid, text)
    removed = [url for url in _URL.findall(cleaned) if url not in known_urls]
    for url in removed:
        cleaned = cleaned.replace(url, "[link removed]")
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned).strip()
    return cleaned, tuple(sorted(set(invalid))), tuple(removed)


async def _reserve_search(session_factory: SessionFactory) -> bool:
    """Spend one unit of the shared search cap. Never raises.

    Args:
        session_factory: Opens a session.

    Returns:
        True when the unit was taken, False when the cap refused.
    """
    async with session_factory() as session:
        try:
            await shared.reserve_capability(
                session, shared.CAPABILITY_SEARCH, app_name="router_example_app"
            )
        except shared.ServiceUnavailableError:
            return False
    return True


async def answer(request: str, session_factory: SessionFactory) -> SearchOutcome:
    """Search once and compose one grounded answer.

    Args:
        request: The visitor's request; also the exact search query.
        session_factory: Opens a session for the search-cap reservation.

    Returns:
        The outcome, candid on every path.
    """
    started = time.perf_counter()

    def elapsed() -> int:
        return round((time.perf_counter() - started) * 1000)

    if not await _reserve_search(session_factory):
        logger.info("router_search_refused", reason="search_cap")
        return SearchOutcome(
            status="search_unavailable",
            elapsed_ms=elapsed(),
            message=SEARCH_CAP_MESSAGE,
        )

    try:
        results = await web_search.search(request)
    except (web_search.ExaClientError, web_search.ExaRateLimitError) as exc:
        logger.warning("router_search_failed", error_type=type(exc).__name__)
        return SearchOutcome(
            elapsed_ms=elapsed(),
            status="search_unavailable",
            query=request,
            searches=1,
            message=(
                "Search unavailable: the web search could not be completed. No "
                "sources are shown rather than invented ones, and the request "
                "was not sent to another route."
            ),
        )

    snippets = trim_results(results)
    if not snippets:
        return SearchOutcome(
            elapsed_ms=elapsed(),
            status="no_results",
            query=request,
            searches=1,
            message=NO_RESULTS_MESSAGE,
        )

    instructions = with_current_date(load_prompt(PROMPTS_DIR, SEARCH_PROMPT_VERSION))
    try:
        generated = await asyncio.to_thread(
            generation.generate_text,
            system_prompt=instructions,
            user_prompt=build_user_prompt(request, snippets),
            max_tokens=MAX_ANSWER_TOKENS,
        )
    except generation.GenerationServiceError:
        logger.warning("router_search_compose_failed")
        return SearchOutcome(
            elapsed_ms=elapsed(),
            status="compose_failed",
            query=request,
            snippets=snippets,
            searches=1,
            message=COMPOSE_FAILED_MESSAGE,
        )

    text, invalid, removed = check_citations(generated.text, snippets)
    logger.info(
        "router_search_answered",
        model=generated.model,
        snippets=len(snippets),
        invalid_citations=len(invalid),
        removed_urls=len(removed),
    )
    return SearchOutcome(
        elapsed_ms=elapsed(),
        status="answered",
        query=request,
        snippets=snippets,
        answer_text=text,
        model=generated.model,
        invalid_citations=invalid,
        removed_urls=removed,
        searches=1,
        model_calls=1,
    )
