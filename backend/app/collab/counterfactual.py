# Built with Spec4 AI - https://spec4.ai
"""The priority-sensitivity counterfactual, computed in code. Never by a model.

"Would a different weighting have picked the other supplier?" is arithmetic:
re-score the two best-and-final bids under a different weight vector and see who
comes out ahead. A model asked to *derive* that answer is doing unreliable
mental arithmetic over numbers it has been shown, and the tier rationale for
this whole example warns that exactly this seam is where a collaboration demo
collapses into a thin prose wrapper over untrustworthy sums.

So the flip is computed here and handed to the prompt **as a given fact**. The
model narrates why it happens. It does not get to disagree, and a validator
checks that it did not.

## How the alternative weighting is chosen

Not arbitrarily, and not by a model. The losing bid's *strongest axis* -- the
one where it most out-performs the winner -- is promoted, and the weighting's
current top priority is demoted, by swapping their weights. That is the
alternative most likely to change the answer, which makes it the informative
one to test: an alternative that obviously changes nothing teaches nothing.

## "Too close to call" is a first-class outcome

Forcing a flip would be inventing a result. When the two totals sit within
`TOO_CLOSE_MARGIN` of each other the honest answer is that the projection does
not separate them, and the panel says so.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from backend.app.collab.scenarios import (
    WEIGHT_TOTAL,
    AxisId,
    Bid,
    PriorityWeighting,
    Scenario,
)
from backend.app.collab.scoring import BidScore, rank_bids

#: Weighted-score points within which two bids are treated as indistinguishable.
#:
#: Three points out of a hundred. Below that the ordering is an artefact of
#: where the scenario's axis bounds happen to sit rather than a real preference,
#: and reporting a winner would be reporting noise.
TOO_CLOSE_MARGIN: Final[float] = 3.0


@dataclass(frozen=True)
class Counterfactual:
    """The computed answer to "what if the priorities had been different?".

    Every field here is arithmetic over the recorded bids. The model is given
    this and asked to explain it; it is not asked to reproduce it.

    Attributes:
        original_weighting_id: The weighting the run actually used.
        original_weights: Its per-axis weights, keyed by axis value.
        alternative_label: A human-readable name for the alternative.
        alternative_weights: The alternative's per-axis weights.
        promoted_axis: The axis whose weight was raised.
        demoted_axis: The axis whose weight was lowered.
        original_winner: Who won under the real weighting.
        alternative_winner: Who wins under the alternative.
        flipped: True when the alternative changes the winner.
        too_close: True when the alternative's margin is within
            `TOO_CLOSE_MARGIN`, so the projection does not separate them.
        original_margin: Winner's total minus runner-up's, as run.
        alternative_margin: The same under the alternative.
        decisive_axes: The axes that moved the result, largest swing first.
        original_scores: Both bids scored under the real weighting.
        alternative_scores: Both bids scored under the alternative.
    """

    original_weighting_id: str
    original_weights: dict[str, int]
    alternative_label: str
    alternative_weights: dict[str, int]
    promoted_axis: AxisId
    demoted_axis: AxisId
    original_winner: str
    alternative_winner: str
    flipped: bool
    too_close: bool
    original_margin: float
    alternative_margin: float
    decisive_axes: tuple[AxisId, ...]
    original_scores: tuple[BidScore, ...]
    alternative_scores: tuple[BidScore, ...]

    @property
    def outcome(self) -> str:
        """A single word for what the projection found.

        Returns:
            `too_close`, `flipped`, or `unchanged`. Checked before `flipped`,
            because a flip inside the noise margin is not a flip worth
            reporting.
        """
        if self.too_close:
            return "too_close"
        return "flipped" if self.flipped else "unchanged"


def _normalised(score: BidScore) -> dict[AxisId, float]:
    """Index one bid's per-axis normalised scores by axis."""
    return {entry.axis: entry.normalised for entry in score.axes}


def alternative_weighting(
    scenario: Scenario,
    weighting: PriorityWeighting,
    bids: list[Bid],
) -> tuple[PriorityWeighting, AxisId, AxisId]:
    """Derive the alternative weighting most likely to change the answer.

    Promotes the losing bid's strongest axis and demotes the current top
    priority, by swapping their weights. Swapping rather than transferring a
    fixed amount keeps the vector summing to 100 without renormalising, which
    matters because a renormalised vector is a *third* weighting neither the
    visitor nor the arithmetic asked for.

    Args:
        scenario: The scenario being negotiated.
        weighting: The weighting the run used.
        bids: The best-and-final bids. Fewer than two means there is no losing
            bid to promote, and the caller should not be here.

    Returns:
        The alternative weighting, the promoted axis, and the demoted axis.
        When the two coincide -- the loser is already strongest on the top
        priority -- the alternative equals the original and the caller reports
        no change rather than inventing one.
    """
    ranked = rank_bids(scenario, weighting, bids)
    winner_scores = _normalised(ranked[0])
    loser_scores = _normalised(ranked[1])

    # Where the loser most out-performs the winner. That is the axis a visitor
    # would have to care more about for the result to move.
    promoted = max(AxisId, key=lambda axis: loser_scores[axis] - winner_scores[axis])
    # The weighting's own top priority, tie-broken by declaration order so the
    # choice is reproducible.
    demoted = max(
        AxisId, key=lambda axis: (weighting.weights[axis], -list(AxisId).index(axis))
    )

    if promoted is demoted:
        return weighting, promoted, demoted

    weights = dict(weighting.weights)
    weights[promoted], weights[demoted] = weights[demoted], weights[promoted]

    return (
        PriorityWeighting(
            id=f"{weighting.id}__alt",
            label=f"{promoted.value.title()} over {demoted.value}",
            description=(
                f"The same bids, weighted so {promoted.value} matters most and "
                f"{demoted.value} matters least."
            ),
            weights=weights,
        ),
        promoted,
        demoted,
    )


def compute_counterfactual(
    scenario: Scenario,
    weighting: PriorityWeighting,
    bids: list[Bid],
) -> Counterfactual | None:
    """Re-score the recorded bids under an alternative weighting.

    Args:
        scenario: The scenario being negotiated.
        weighting: The weighting the run used.
        bids: The best-and-final bids.

    Returns:
        The computed counterfactual, or None when fewer than two bids survived
        -- a projection needs two things to compare, and a degraded run has
        one.
    """
    if len(bids) < 2:
        return None

    alternative, promoted, demoted = alternative_weighting(scenario, weighting, bids)

    original = rank_bids(scenario, weighting, bids)
    alt = rank_bids(scenario, alternative, bids)

    original_margin = original[0].total - original[1].total
    alternative_margin = alt[0].total - alt[1].total

    # Which axes actually moved it: the per-axis contribution swing between the
    # two weightings, largest first. Computed, so the narration cannot pick a
    # dimension that did nothing.
    swings: dict[AxisId, float] = {}
    for axis in AxisId:
        before = _axis_gap(original, axis)
        after = _axis_gap(alt, axis)
        swings[axis] = abs(after - before)
    decisive = tuple(sorted(AxisId, key=lambda axis: -swings[axis]))[:2]

    return Counterfactual(
        original_weighting_id=weighting.id,
        original_weights={axis.value: weighting.weights[axis] for axis in AxisId},
        alternative_label=alternative.label,
        alternative_weights={axis.value: alternative.weights[axis] for axis in AxisId},
        promoted_axis=promoted,
        demoted_axis=demoted,
        original_winner=original[0].seller_id,
        alternative_winner=alt[0].seller_id,
        flipped=alt[0].seller_id != original[0].seller_id,
        too_close=alternative_margin < TOO_CLOSE_MARGIN,
        original_margin=original_margin,
        alternative_margin=alternative_margin,
        decisive_axes=decisive,
        original_scores=original,
        alternative_scores=alt,
    )


def _axis_gap(ranked: tuple[BidScore, ...], axis: AxisId) -> float:
    """Return the leader's contribution minus the runner-up's on one axis."""
    lead = next(entry for entry in ranked[0].axes if entry.axis is axis)
    trail = next(entry for entry in ranked[1].axes if entry.axis is axis)
    return lead.contribution - trail.contribution


def cited_values(counterfactual: Counterfactual) -> frozenset[str]:
    """Every number the sensitivity narration is allowed to use.

    The whitelist the validator checks generated prose against. Numeric fields
    in these explanations are **echo-only**: the model may repeat a figure it
    was given and may not compute, round or interpolate a new one, because a
    plausible-looking invented number is indistinguishable from a real one to
    the visitor.

    Args:
        counterfactual: The computed projection.

    Returns:
        Every figure the model may write, in the renderings it may write them.
    """
    values: set[str] = set()
    for weights in (
        counterfactual.original_weights,
        counterfactual.alternative_weights,
    ):
        for weight in weights.values():
            values.update(_renderings(float(weight)))
    values.update(_renderings(float(WEIGHT_TOTAL)))
    for scores in (counterfactual.original_scores, counterfactual.alternative_scores):
        for score in scores:
            values.update(_renderings(score.total))
            for entry in score.axes:
                values.update(_renderings(entry.value))
    values.update(_renderings(counterfactual.original_margin))
    values.update(_renderings(counterfactual.alternative_margin))
    return frozenset(values)


def _renderings(number: float) -> frozenset[str]:
    """Return the ways a model might write one number."""
    forms = {f"{number:g}", f"{number:.1f}", f"{number:.2f}"}
    if number.is_integer():
        forms.add(str(int(number)))
    return frozenset(forms)
