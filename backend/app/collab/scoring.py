# Built with Spec4 AI - https://spec4.ai
"""Deterministic priority-weighted scoring of bids. No model, ever.

Ranking two bids against a weighting is arithmetic, and the capability is
explicit that it should stay arithmetic: *"weighing final bids against the
visitor's stated priority weights is arithmetic and should be deterministic
code, with the LLM only writing the rationale over the computed ranking."*
A model that both computed the ranking and explained it could produce a
rationale that did not follow from any calculation, which is the defect this
project has fixed three times elsewhere -- a surface asserting something
nothing checked.

So this module decides *who wins*. Phase 3's buyer agent writes the prose about
why, over a ranking it did not choose.

## Why axis bounds come from the scenario, not from the two bids

The obvious normalisation -- min-max across the bids actually received --
collapses every axis to exactly 1 and 0 when there are two bidders. Every
weighting then reduces to "which seller won more axes, weighted", the margin
of a win stops mattering, and a bid that was barely cheaper scores identically
to one that halved the price. Scoring against the scenario's declared
`best`/`worst` range keeps the arithmetic sensitive to *how much* better an
offer is, which is what makes a close call close.

Values outside the declared range are clamped rather than extrapolated, so an
outlying bid cannot score above 1 or below 0 and cannot be gamed by quoting an
absurd number on one axis.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from backend.app.collab.scenarios import (
    AxisId,
    Bid,
    PriorityWeighting,
    Scenario,
    TermAxis,
)
from backend.app.collab.schemas import Bid as NegotiationBid


@dataclass(frozen=True)
class AxisScore:
    """How one bid did on one axis.

    Attributes:
        axis: Which axis.
        value: The bid's raw value, in the axis's own unit.
        normalised: 0.0--1.0, where 1.0 is the scenario's declared best.
        weight: The weighting's weight for this axis, 0--100.
        contribution: `normalised * weight`. Summed across axes to give the
            bid's total.
    """

    axis: AxisId
    value: float
    normalised: float
    weight: int
    contribution: float


@dataclass(frozen=True)
class BidScore:
    """One bid's total, with the per-axis working kept.

    The breakdown is retained rather than reduced to a number because the
    award has to be explainable: the buyer agent is given this, and a visitor
    is shown it beside the rationale so a mismatch between the two is visible.

    Attributes:
        seller_id: Whose bid this is.
        total: Sum of the axis contributions, 0--100.
        axes: The per-axis working, in `AxisId` declaration order.
    """

    seller_id: str
    total: float
    axes: tuple[AxisScore, ...]


def normalise(axis: TermAxis, value: float) -> float:
    """Map a raw axis value onto 0.0--1.0, where 1.0 is best.

    Args:
        axis: The axis, carrying its direction and its declared range.
        value: The bid's raw value.

    Returns:
        The normalised score, clamped to `[0.0, 1.0]`. A degenerate axis whose
        `best` equals its `worst` scores 1.0 rather than dividing by zero --
        an axis with no spread cannot distinguish two bids, so it should not
        penalise either.
    """
    span = axis.best - axis.worst
    if span == 0:
        return 1.0

    # One formula serves both directions: `direction` is already encoded in the
    # *ordering* of `best` and `worst`. On a lower-is-better axis `best < worst`
    # so the span is negative, and the same expression still returns 1.0 at
    # `best` and 0.0 at `worst`. Branching on `direction` here would be a second
    # place for the sign to be wrong.
    fraction = (value - axis.worst) / span
    return max(0.0, min(1.0, fraction))


def score_bid(scenario: Scenario, weighting: PriorityWeighting, bid: Bid) -> BidScore:
    """Score one bid against one weighting.

    Args:
        scenario: The scenario, supplying each axis's range and direction.
        weighting: The visitor's stated priorities.
        bid: The offer to score.

    Returns:
        The bid's total and its per-axis working.

    Raises:
        KeyError: If the bid omits an axis the scenario declares. Bids are
            schema-constrained upstream, so a missing axis is a bug rather
            than a value to default -- defaulting it would quietly award a
            zero and change who won.
    """
    axes: list[AxisScore] = []
    for axis in scenario.axes:
        value = bid.values[axis.id]
        weight = weighting.weights[axis.id]
        normalised = normalise(axis, value)
        axes.append(
            AxisScore(
                axis=axis.id,
                value=value,
                normalised=normalised,
                weight=weight,
                contribution=normalised * weight,
            )
        )

    return BidScore(
        seller_id=bid.seller_id,
        total=sum(entry.contribution for entry in axes),
        axes=tuple(axes),
    )


def rank_bids(
    scenario: Scenario, weighting: PriorityWeighting, bids: Sequence[Bid]
) -> tuple[BidScore, ...]:
    """Rank bids best-first under a weighting.

    Ties are broken by `seller_id` so the result is fully deterministic: two
    runs of the same inputs return the same winner, which a test can assert
    and a visitor can reproduce.

    Args:
        scenario: The scenario being bid on.
        weighting: The visitor's stated priorities.
        bids: The offers to rank.

    Returns:
        The scored bids, highest total first.
    """
    scores = [score_bid(scenario, weighting, bid) for bid in bids]
    return tuple(sorted(scores, key=lambda s: (-s.total, s.seller_id)))


def winner(
    scenario: Scenario, weighting: PriorityWeighting, bids: Sequence[Bid]
) -> str:
    """Return the seller id ranked first.

    Args:
        scenario: The scenario being bid on.
        weighting: The visitor's stated priorities.
        bids: The offers to rank. Must not be empty.

    Returns:
        The winning seller's id.

    Raises:
        ValueError: If no bids were supplied. A run with nothing to award is a
            caller error, not an award of `None`.
    """
    if not bids:
        raise ValueError("Cannot pick a winner from an empty bid list")
    return rank_bids(scenario, weighting, bids)[0].seller_id


def weights_as_mapping(weighting: PriorityWeighting) -> Mapping[str, int]:
    """Project a weighting's weights to plain string keys, for persistence.

    Args:
        weighting: The weighting to project.

    Returns:
        The per-axis weights keyed by the axis's string value, ready for a
        JSONB column or an SSE payload.
    """
    return {axis.value: weight for axis, weight in weighting.weights.items()}


def to_scored_bid(bid: NegotiationBid) -> Bid:
    """Convert a negotiation turn's bid into the shape the scorer takes.

    Two `Bid` types exist and both earn their place: `schemas.Bid` is what a
    seller agent *returns* (with notes, concessions and a stage label), while
    `scenarios.Bid` is the axis vector the arithmetic operates on. Keeping them
    apart stops the scorer depending on prose fields it has no use for.

    This is the single place the mapping lives, so an axis cannot be wired to
    the wrong field in one caller and not another.

    Args:
        bid: A bid as a seller agent produced it.

    Returns:
        The same offer as a four-axis vector.
    """
    return Bid(
        seller_id=bid.seller_id,
        values={
            AxisId.PRICE: bid.unit_price,
            AxisId.DELIVERY: bid.delivery_days,
            AxisId.QUANTITY: bid.quantity,
            AxisId.WARRANTY: bid.warranty_months,
        },
    )
