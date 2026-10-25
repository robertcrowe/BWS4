# Built with Spec4 AI - https://spec4.ai
"""The cost strip: the route taken against a "no router" baseline.

The baseline is the heaviest path applied to every request: one Exa search
plus one generation call, no retrieval. The strip compares by resource type --
model calls, searches, retrievals, time -- with the router's own
classification call shown separately as overhead.

Two rules about time, because they are the ones easiest to break:

- **The route taken always shows its own measured time.**
- **The baseline's time is never this run's time.** It is labelled "typical",
  is the rolling median of real search-route runs across all visitors, shows
  its sample size, and is omitted -- with a note saying why -- until at least
  five observations exist. No nominal figure is ever substituted.

When the route taken *is* search plus generation, the strip says plainly that
routing added one call and saved nothing on this request.
"""

from __future__ import annotations

from typing import Final

from pydantic import BaseModel

from backend.app.router.constants import (
    MIN_OBSERVATIONS,
    ROUTE_LABELS,
    SEARCH_GENERATION,
    RouteId,
)
from backend.app.router.history import LatencyBaseline

#: The "no router" baseline: one search plus one generation call.
BASELINE_MODEL_CALLS: Final[int] = 1
BASELINE_SEARCHES: Final[int] = 1
BASELINE_RETRIEVALS: Final[int] = 0

SAVED_NOTHING: Final[str] = (
    "Routing added one call and saved nothing on this request: the route taken "
    "is the baseline itself."
)
DETERMINISTIC_RELEASE: Final[str] = (
    "The evaluator answered with no model call, so the second reserved unit was "
    "released."
)


class RouteTaken(BaseModel):
    """What the dispatched route actually spent, and its own measured time."""

    model_calls: int
    searches: int
    retrievals: int
    measured_ms: int


class Baseline(BaseModel):
    """The no-router baseline. Its time is typical, never this run's.

    Attributes:
        model_calls: Always 1.
        searches: Always 1.
        retrievals: Always 0.
        typical_ms: Median of recent real search-route runs, or None until
            `MIN_OBSERVATIONS` exist.
        sample_size: Rows the median rests on.
    """

    model_calls: int = BASELINE_MODEL_CALLS
    searches: int = BASELINE_SEARCHES
    retrievals: int = BASELINE_RETRIEVALS
    typical_ms: int | None
    sample_size: int


class Overhead(BaseModel):
    """The router's own classification call, shown separately.

    Zero on a comparison re-run, where the router does not run -- shown as an
    explicit zero rather than omitted.
    """

    model_calls: int
    measured_ms: int


class CostStrip(BaseModel):
    """The whole strip, as the end-of-run event carries it."""

    route: RouteId
    route_label: str
    route_taken: RouteTaken
    baseline: Baseline
    overhead: Overhead
    saved_nothing: bool
    notes: list[str]


def baseline_note(baseline: LatencyBaseline) -> str | None:
    """Explain a missing typical time, if it is missing.

    Args:
        baseline: The latency baseline.

    Returns:
        The note, or None when the typical time is shown.
    """
    if baseline.typical_ms is not None:
        return None
    return (
        "Typical baseline time appears once at least "
        f"{MIN_OBSERVATIONS} real search-route runs have been observed "
        f"({baseline.sample_size} so far); until then the baseline is shown as "
        "counts only."
    )


def build_cost_strip(
    *,
    route: RouteId,
    model_calls: int,
    searches: int,
    retrievals: int,
    route_ms: int,
    overhead_calls: int,
    overhead_ms: int,
    baseline: LatencyBaseline,
    unit_released: bool = False,
    baseline_unavailable: bool = False,
) -> CostStrip:
    """Build the strip for one run.

    Args:
        route: The route the request was dispatched to.
        model_calls: Generation calls the route made.
        searches: Searches the route made.
        retrievals: Retrievals the route made.
        route_ms: The route's own measured time.
        overhead_calls: The router's calls: 1, or 0 on a re-run.
        overhead_ms: The router's measured time.
        baseline: The typical search-route time and its sample size.
        unit_released: True when the deterministic route released its second
            reserved unit.
        baseline_unavailable: True when the latency history could not be
            read; the baseline is then counts only, said so plainly.

    Returns:
        The cost strip.
    """
    saved_nothing = route == SEARCH_GENERATION and overhead_calls > 0
    notes: list[str] = []
    if saved_nothing:
        notes.append(SAVED_NOTHING)
    if unit_released:
        notes.append(DETERMINISTIC_RELEASE)
    if baseline_unavailable:
        notes.append(
            "The typical baseline time could not be read from the history just "
            "now, so the baseline is shown as counts only."
        )
    else:
        missing = baseline_note(baseline)
        if missing:
            notes.append(missing)
    return CostStrip(
        route=route,
        route_label=ROUTE_LABELS[route],
        route_taken=RouteTaken(
            model_calls=model_calls,
            searches=searches,
            retrievals=retrievals,
            measured_ms=route_ms,
        ),
        baseline=Baseline(
            typical_ms=baseline.typical_ms, sample_size=baseline.sample_size
        ),
        overhead=Overhead(model_calls=overhead_calls, measured_ms=overhead_ms),
        saved_nothing=saved_nothing,
        notes=notes,
    )
