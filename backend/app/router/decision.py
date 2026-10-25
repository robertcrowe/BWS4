# Built with Spec4 AI - https://spec4.ai
"""The Router's decision rules: pure code over the four scores.

The model's `route` field is advisory. Everything that decides a run is
recomputed here from the scores alone:

- **Argmax.** The highest score is the chosen route; an exact tie goes to the
  cheaper route in `ROUTE_COST_ORDER`.
- **Low confidence.** When the top two scores are within `DECISION_MARGIN`
  (inclusive), the router did not choose. The two routes it was torn between
  are those top two *by score* -- never a runner-up the model names -- and the
  run dispatches to the cheaper of them.
- **Malformed.** A failed or schema-invalid classification is its own outcome:
  dispatched to single call inside the routed-answer ending, with no agreement
  row. It is **not** "declined"; declined means low confidence and nothing
  else.

Three outcome types rather than one with flags, so a later phase cannot mistake
a malformed fallback for a low-confidence tie or vice versa.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Literal

import structlog

from backend.app.router.classifier import Classification
from backend.app.router.constants import (
    DECISION_MARGIN,
    ROUTE_COST_ORDER,
    SINGLE_CALL,
    RouteId,
)

logger = structlog.get_logger()

#: Absorbs binary floating-point error at the margin boundary, so a gap that is
#: exactly the margin in decimal (0.60 - 0.45) counts as within it.
_MARGIN_EPSILON: Final[float] = 1e-9


class Agreement(StrEnum):
    """How a preset run's decision compares with its expected route."""

    AGREED = "agreed"
    MISROUTED = "misrouted"
    DECLINED = "declined"


@dataclass(frozen=True)
class Routed:
    """The router chose a route with a clear margin.

    Attributes:
        route: The argmax route; dispatch goes here.
        scores: All four scores.
        rationale: The model's one-line rationale.
        expression: The model's expression, if any. Untrusted.
        advisory_route: The route the model named, kept for logging.
        gap: Top score minus runner-up.
    """

    route: RouteId
    scores: dict[RouteId, float]
    rationale: str
    expression: str | None
    advisory_route: RouteId
    gap: float
    kind: Literal["routed"] = "routed"


@dataclass(frozen=True)
class LowConfidence:
    """The top two scores were within the margin: the router did not choose.

    Attributes:
        torn: The two top-scoring routes, cheaper first.
        dispatched: The cheaper of the two; dispatch goes here.
        other: The more expensive of the two, used if the cheaper fails.
        scores: All four scores.
        rationale: The model's one-line rationale.
        expression: The model's expression, if any. Untrusted.
        gap: Top score minus runner-up.
    """

    torn: tuple[RouteId, RouteId]
    dispatched: RouteId
    other: RouteId
    scores: dict[RouteId, float]
    rationale: str
    expression: str | None
    gap: float
    kind: Literal["low_confidence"] = "low_confidence"


@dataclass(frozen=True)
class Malformed:
    """The classification failed or was schema-invalid. Not retried.

    Attributes:
        failure: Why, for logs and the card note.
        dispatched: Always single call.
    """

    failure: str
    dispatched: RouteId = SINGLE_CALL
    kind: Literal["malformed"] = "malformed"


Outcome = Routed | LowConfidence | Malformed


def cost_rank(route: RouteId) -> int:
    """Return a route's position in the fixed cost order, 0 cheapest.

    Args:
        route: The route.

    Returns:
        Its rank.
    """
    return ROUTE_COST_ORDER.index(route)


def rank_routes(scores: dict[RouteId, float]) -> list[RouteId]:
    """Order the routes by score, highest first, exact ties cheapest first.

    Args:
        scores: All four scores.

    Returns:
        The four route ids.
    """
    return sorted(
        ROUTE_COST_ORDER, key=lambda route: (-scores[route], cost_rank(route))
    )


def argmax_route(scores: dict[RouteId, float]) -> RouteId:
    """Return the highest-scoring route, an exact tie going to the cheaper.

    Args:
        scores: All four scores.

    Returns:
        The chosen route.
    """
    return rank_routes(scores)[0]


def is_low_confidence(gap: float, margin: float = DECISION_MARGIN) -> bool:
    """Whether a top-two gap is within the margin (inclusive).

    Args:
        gap: Top score minus runner-up, non-negative.
        margin: The decision margin.

    Returns:
        True when the run is low-confidence.
    """
    return gap <= margin + _MARGIN_EPSILON


def cheaper(first: RouteId, second: RouteId) -> RouteId:
    """Return the cheaper of two routes by the fixed cost order.

    Args:
        first: One route.
        second: Another route.

    Returns:
        Whichever appears earlier in `ROUTE_COST_ORDER`.
    """
    return first if cost_rank(first) <= cost_rank(second) else second


def decide(classification: Classification) -> Outcome:
    """Turn a classification into the run's outcome.

    Args:
        classification: The result of the one classification call.

    Returns:
        Routed, LowConfidence, or Malformed.
    """
    decision = classification.decision
    if decision is None:
        return Malformed(failure=classification.failure or "No decision returned.")

    scores = decision.scores.as_dict()
    ranked = rank_routes(scores)
    top, runner_up = ranked[0], ranked[1]
    gap = scores[top] - scores[runner_up]
    logger.info(
        "router_decision",
        argmax_route=top,
        advisory_route=decision.route,
        route_mismatch=top != decision.route,
        gap=round(gap, 4),
        margin=DECISION_MARGIN,
        classifier_ms=classification.elapsed_ms,
    )

    if is_low_confidence(gap):
        dispatched = cheaper(top, runner_up)
        other = runner_up if dispatched == top else top
        return LowConfidence(
            torn=(dispatched, other),
            dispatched=dispatched,
            other=other,
            scores=scores,
            rationale=decision.rationale,
            expression=decision.expression,
            gap=gap,
        )
    return Routed(
        route=top,
        scores=scores,
        rationale=decision.rationale,
        expression=decision.expression,
        advisory_route=decision.route,
        gap=gap,
    )


def agreement(
    outcome: Outcome,
    expected_route: RouteId | None,
    dispatched: RouteId | None = None,
) -> Agreement | None:
    """State how a preset run's decision compares with its expected route.

    "Agreed" means the route the request was actually *dispatched* to equals
    the expected route after a confident choice. They differ from the router's
    argmax only on an evaluator fallback -- the router chose the deterministic
    route but wrote an expression the evaluator rejected -- and that is the
    router's own misroute, so it does not earn agreement.

    Args:
        outcome: The run's outcome.
        expected_route: The preset's expected route, or None for free text.
        dispatched: Where the request was finally dispatched. Defaults to the
            argmax route.

    Returns:
        Agreed or misrouted for a routed preset run, declined for a
        low-confidence one, and None for free text or a malformed decision --
        neither of which earns an agreement statement or a history row.
    """
    if expected_route is None or isinstance(outcome, Malformed):
        return None
    if isinstance(outcome, LowConfidence):
        return Agreement.DECLINED
    final = dispatched if dispatched is not None else outcome.route
    return Agreement.AGREED if final == expected_route else Agreement.MISROUTED
