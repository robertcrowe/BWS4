# Built with Spec4 AI - https://spec4.ai
"""The four one-line route descriptions, generated rather than written.

The router is told each route in one line, and the page shows those lines byte
for byte as the router received them. Nothing here is hand-maintained prose
that could drift from what the routes actually do:

- the deterministic line is rendered from the evaluator's own unit table;
- the retrieval line lists subjects derived from the document titles the RAG
  retriever actually indexes, read at startup;
- the search line carries the shared web-search tool's declared description,
  the same text the Tool-Use example hands its model;
- the single-call line states what that route is: one generation call over the
  request alone. The single-call capability declares no description of its
  own, so this is the one line of prose here.

`route_descriptions_block` is the exact string the classification prompt
receives and the page renders. Both import it; neither reformats it.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from backend.app.router.constants import (
    DETERMINISTIC_EVALUATOR,
    RETRIEVAL,
    ROUTE_COST_ORDER,
    ROUTE_LABELS,
    SEARCH_GENERATION,
    SINGLE_CALL,
    RouteId,
)
from backend.app.tools.agent import SEARCH_TOOL_NAME, TOOL_SCHEMAS

#: The single-call route's line. No declared description exists to borrow.
SINGLE_CALL_DESCRIPTION: Final[str] = (
    "One call through the shared generation service, answering from the request "
    "alone: language tasks such as rewriting, explaining or summarising that need "
    "no outside facts and no live information."
)

#: A trailing parenthetical disambiguator in a document title, e.g. "(rover)".
_DISAMBIGUATOR: Final = re.compile(r"\s*\([^)]*\)\s*$")


@dataclass(frozen=True)
class Route:
    """One route as the router is told it.

    Attributes:
        id: The route id.
        label: Display name.
        description: The one line the router receives, verbatim.
        cost_rank: Position in the fixed cost order, 0 cheapest.
    """

    id: RouteId
    label: str
    description: str
    cost_rank: int


def subject_from_title(title: str) -> str:
    """Derive a subject name from an indexed document title.

    Drops a trailing parenthetical disambiguator, so "Curiosity (rover)" reads
    as "Curiosity"; otherwise the title is the subject.

    Args:
        title: The document title as indexed.

    Returns:
        The subject name.
    """
    return _DISAMBIGUATOR.sub("", title).strip()


def search_tool_description() -> str:
    """Return the shared web-search tool's declared description.

    Returns:
        The `description` from the Tool-Use example's `web_search` schema.

    Raises:
        LookupError: If the schema no longer declares that tool, so a renamed
            tool fails loudly at startup rather than silently changing the line.
    """
    for schema in TOOL_SCHEMAS:
        function = schema.get("function")
        if isinstance(function, dict) and function.get("name") == SEARCH_TOOL_NAME:
            description = function.get("description")
            if isinstance(description, str):
                return description
    raise LookupError(f"No declared description for tool {SEARCH_TOOL_NAME!r}.")


def build_route_descriptions(
    unit_table_line: str, document_titles: Sequence[str]
) -> tuple[Route, ...]:
    """Build the four routes in the fixed cost order.

    Pure: the same inputs always give the same lines.

    Args:
        unit_table_line: The deterministic line, from
            `unit_table.render_supported_operations_line()`.
        document_titles: Titles of the documents the retriever indexes.

    Returns:
        Four routes, cheapest first.

    Raises:
        ValueError: If there are no document titles; a retrieval line with no
            subjects would tell the router nothing true.
    """
    subjects = sorted(
        {subject_from_title(title) for title in document_titles if title.strip()}
    )
    if not subjects:
        raise ValueError("No indexed document titles to describe the RAG route.")
    descriptions: dict[RouteId, str] = {
        DETERMINISTIC_EVALUATOR: unit_table_line,
        SINGLE_CALL: SINGLE_CALL_DESCRIPTION,
        RETRIEVAL: (
            "Retrieval over the RAG example's indexed space-exploration documents, "
            "then one answer call grounded in the retrieved passages. Subjects: "
            f"{', '.join(subjects)}."
        ),
        SEARCH_GENERATION: (
            "Shared Exa web search followed by one generation call over the "
            f"results. {search_tool_description()}"
        ),
    }
    return tuple(
        Route(
            id=route_id,
            label=ROUTE_LABELS[route_id],
            description=descriptions[route_id],
            cost_rank=rank,
        )
        for rank, route_id in enumerate(ROUTE_COST_ORDER)
    )


def route_descriptions_block(routes: Sequence[Route]) -> str:
    """Render the exact block the router prompt receives and the page shows.

    One line per route, `<route id>: <description>`, in cost order, joined by
    newlines with no trailing newline.

    Args:
        routes: The four routes.

    Returns:
        The block.
    """
    return "\n".join(f"{route.id}: {route.description}" for route in routes)


def block_sha256(block: str) -> str:
    """Hash the block so the page can show it is unchanged in transit.

    Args:
        block: The route descriptions block.

    Returns:
        Hex SHA-256 of its UTF-8 bytes.
    """
    return hashlib.sha256(block.encode("utf-8")).hexdigest()
