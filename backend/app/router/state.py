# Built with Spec4 AI - https://spec4.ai
"""The in-process holder for the generated route descriptions.

Filled at startup by `warm_route_descriptions`. Per-process state, like the
embedding model: this is one of the reasons the API runs with one worker.

The holder is either *ready* or *unavailable* -- never half-filled. It starts
unavailable at import and becomes ready only when a warm-up fully succeeds; the
descriptions are built into a local value and assigned in one step, so a
failure part-way leaves the previous state untouched.

Warm-up is best-effort. If the indexed titles cannot be read at boot (the
database is unreachable), the lifespan logs the failure and the process starts
anyway with the holder unavailable. The Router then reports itself temporarily
unavailable -- `is_ready()` is an in-memory read, no database session -- until
`POST /api/router/retry` calls `warm_route_descriptions` again and it succeeds.
There is no background retry timer and no implicit retry on read: the presets
endpoint and run admission only look at the holder, they never refill it.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import structlog

from backend.app.db.session import async_session_factory
from backend.app.router.indexed_titles import load_indexed_document_titles
from backend.app.router.route_descriptions import (
    Route,
    block_sha256,
    build_route_descriptions,
    route_descriptions_block,
)
from backend.app.router.unit_table import render_supported_operations_line

logger = structlog.get_logger()


@dataclass(frozen=True)
class RouteDescriptions:
    """The four routes, the exact block the router receives, and its hash.

    Attributes:
        routes: The four routes, cheapest first.
        block: The exact string the router prompt receives.
        sha256: Hex SHA-256 of `block`.
    """

    routes: tuple[Route, ...]
    block: str
    sha256: str


_current: RouteDescriptions | None = None
_lock = asyncio.Lock()


def get_route_descriptions() -> RouteDescriptions | None:
    """Return the generated descriptions, or None if not yet generated.

    Returns:
        The descriptions, or None.
    """
    return _current


def current_route_block() -> str | None:
    """Return the exact route block the router prompt receives.

    The one source for that string: the classification prompt and the presets
    endpoint both read it from here, and neither reformats it.

    Returns:
        The block, or None if descriptions are not ready.
    """
    return _current.block if _current is not None else None


def set_route_descriptions(titles: list[str]) -> RouteDescriptions:
    """Generate and store the descriptions from a list of indexed titles.

    Args:
        titles: The indexed document titles.

    Built in full first and stored with a single assignment, so an exception
    while building leaves the holder as it was -- never partially filled.

    Returns:
        The stored descriptions.
    """
    global _current
    routes = build_route_descriptions(render_supported_operations_line(), titles)
    block = route_descriptions_block(routes)
    built = RouteDescriptions(routes=routes, block=block, sha256=block_sha256(block))
    _current = built
    return built


def reset_route_descriptions() -> None:
    """Empty the holder, making the Router unavailable. For tests."""
    global _current
    _current = None


def is_ready() -> bool:
    """Report whether the route descriptions are ready.

    An in-memory read: no database session, no I/O. Run admission calls it
    first, before moderation and before any hold.

    Returns:
        True once a warm-up has succeeded, False while unavailable.
    """
    return _current is not None


async def warm_route_descriptions() -> RouteDescriptions:
    """Generate and store the route descriptions; safe to call again.

    Called once by the lifespan at startup and again by each
    `POST /api/router/retry`. If the holder is already ready it is returned as
    is, without reading the database. Otherwise the indexed titles are read and
    the descriptions are built and stored in one assignment. A failure stores
    nothing and is raised to the caller -- the lifespan logs it and boots
    anyway; the retry endpoint reports it.

    Returns:
        The ready descriptions.

    Raises:
        Exception: Whatever reading the titles or building the descriptions
            raised. The holder is left exactly as it was.
    """
    if _current is not None:
        return _current
    async with _lock:
        if _current is not None:
            return _current
        async with async_session_factory() as session:
            titles = await load_indexed_document_titles(session)
        descriptions = set_route_descriptions(titles)
    logger.info("router_route_descriptions_ready", sha256=descriptions.sha256)
    return descriptions
