# Built with Spec4 AI - https://spec4.ai
"""The in-process holder for the generated route descriptions.

Filled once, at startup, by `warm_route_descriptions`. Per-process state, like
the embedding model: this is one of the reasons the API runs with one worker.

Warm-up is best-effort. If the database is unreachable at boot the process
starts anyway and the holder stays empty; the presets endpoint then retries
once per request through `ensure_route_descriptions` and reports "not ready"
rather than inventing a retrieval line with a hand-written subject list.
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

    Returns:
        The stored descriptions.
    """
    global _current
    routes = build_route_descriptions(render_supported_operations_line(), titles)
    block = route_descriptions_block(routes)
    _current = RouteDescriptions(routes=routes, block=block, sha256=block_sha256(block))
    return _current


def reset_route_descriptions() -> None:
    """Empty the holder. For tests."""
    global _current
    _current = None


async def ensure_route_descriptions() -> RouteDescriptions | None:
    """Generate the descriptions if they are not already held.

    Idempotent and never raises: a failure is logged and the holder stays
    empty, so a later call can try again.

    Returns:
        The descriptions, or None if they could not be generated.
    """
    if _current is not None:
        return _current
    async with _lock:
        if _current is not None:
            return _current
        try:
            async with async_session_factory() as session:
                titles = await load_indexed_document_titles(session)
            return set_route_descriptions(titles)
        except Exception:  # noqa: BLE001 - best-effort by design; reported as not ready
            logger.exception("router_route_descriptions_unavailable")
            return None


async def warm_route_descriptions() -> None:
    """Startup warm-up: generate the descriptions once, never failing boot."""
    descriptions = await ensure_route_descriptions()
    if descriptions is not None:
        logger.info("router_route_descriptions_ready", sha256=descriptions.sha256)
