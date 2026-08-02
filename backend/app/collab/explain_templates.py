# Built with Spec4 AI - https://spec4.ai
"""Deterministic renderers for both explanation panels. Built first, on purpose.

These cover **100% of both output shapes from the same inputs the model gets**,
which makes the model call an *enhancement over a working panel* rather than
the panel's only source. That ordering is the phase's own mitigation, and the
reason is timing: these two calls sit at the very end of a run, so a failure
lands after the visitor has already waited through six stages. An empty or
spinning panel at that moment is the worst available outcome.

So the sequence is: render the template, try to improve on it with a model,
check the result, and keep whichever survives. A panel can be *worse* than it
might have been; it can never be blank.

## The template is honest about being a template

Anything rendered from here is badged `fallback_generated`. It is assembled
from arithmetic — stance from the bid delta, the constraint from the
minimum-slack match, the comparison from the computed re-scoring — so it says
less than good narration would, and it never says anything the record does not
support. Passing it off as the model's prose would be the same class of defect
as everything else this project keeps removing.
"""

from __future__ import annotations

from backend.app.collab.counterfactual import Counterfactual
from backend.app.collab.explain_schemas import (
    AxisExplanation,
    AxisStance,
    PartyReveal,
    RevealExplanation,
    SensitivityExplanation,
)
from backend.app.collab.explain_validator import AxisFact
from backend.app.collab.scenarios import AxisId, Scenario

#: How a constraint id reads in a sentence.
_CONSTRAINT_PROSE: dict[str, str] = {
    "cost_floor": "its cost floor",
    "capacity_ceiling": "the most it could supply",
    "delivery_capability": "the fastest it could deliver",
    "warranty_liability_limit": "the longest warranty it would carry",
    "budget_ceiling": "its budget ceiling",
    "batna": "its fallback option",
}


def _axis_label(scenario: Scenario, axis: AxisId) -> str:
    """Return the scenario's own label and unit for an axis."""
    term = scenario.axis(axis)
    return f"{term.label.lower()} ({term.unit})"


def render_axis(scenario: Scenario, party_id: str, fact: AxisFact) -> AxisExplanation:
    """Render one axis's explanation from the recorded values alone.

    Args:
        scenario: The scenario being negotiated.
        party_id: Whose axis this is.
        fact: The recomputed truth for this axis.

    Returns:
        A complete `AxisExplanation` — every field populated, nothing inferred.
    """
    label = _axis_label(scenario, axis=fact.axis)
    if fact.stance is AxisStance.CONCEDED:
        moved = f"{party_id} moved on {label}, from {fact.opening} to {fact.final}."
        because = (
            f" It went as far as {_CONSTRAINT_PROSE[fact.binding]} allowed."
            if fact.binding is not None
            else " It still had room on this term when it stopped."
        )
    else:
        moved = f"{party_id} held {label} at {fact.final}."
        because = (
            f" That was {_CONSTRAINT_PROSE[fact.binding]}, so there was nothing left "
            "to give."
            if fact.binding is not None
            else " No sealed limit forced this; it simply did not move."
        )

    return AxisExplanation(
        axis=fact.axis.value,
        stance=fact.stance.value,
        opening_value=fact.opening,
        final_value=fact.final,
        binding_constraint=fact.binding,
        explanation=moved + because,
    )


def render_party(
    scenario: Scenario, party_id: str, facts: dict[AxisId, AxisFact]
) -> PartyReveal:
    """Render one party's whole reveal block deterministically.

    Args:
        scenario: The scenario being negotiated.
        party_id: Whose block this is.
        facts: The recomputed truth, per axis.

    Returns:
        A complete `PartyReveal`.
    """
    conceded = [f.axis.value for f in facts.values() if f.stance is AxisStance.CONCEDED]
    bound = [f.axis.value for f in facts.values() if f.binding is not None]

    if conceded and bound:
        headline = (
            f"{party_id} gave ground on {', '.join(conceded)} and was at its limit on "
            f"{', '.join(bound)}."
        )
    elif conceded:
        headline = f"{party_id} gave ground on {', '.join(conceded)}."
    elif bound:
        headline = f"{party_id} held every term, at its limit on {', '.join(bound)}."
    else:
        headline = f"{party_id} held every term without hitting a sealed limit."

    return PartyReveal(
        party_id=party_id,
        headline=headline,
        axes=[
            render_axis(scenario, party_id, facts[axis])
            for axis in AxisId
            if axis in facts
        ],
    )


def render_reveal(
    scenario: Scenario, facts_by_party: dict[str, dict[AxisId, AxisFact]]
) -> RevealExplanation:
    """Render the whole reveal from arithmetic alone.

    Args:
        scenario: The scenario being negotiated.
        facts_by_party: The recomputed truth, per party per axis.

    Returns:
        A complete `RevealExplanation`, covering every party.
    """
    return RevealExplanation(
        parties=[
            render_party(scenario, party_id, facts)
            for party_id, facts in facts_by_party.items()
        ]
    )


#: Attached to every projection, template or model-written. The panel's honesty
#: rests on it: re-scoring recorded bids is not the same as running the round
#: again, because the sellers would have bid differently against different
#: stated priorities in the first place.
CAVEAT = (
    "This is a projection: the same recorded bids re-scored under different "
    "weights, not a second negotiation. A real re-run would have started from a "
    "different request, so the suppliers would have bid differently."
)


def render_sensitivity(counterfactual: Counterfactual) -> SensitivityExplanation:
    """Render the counterfactual narration from the computed result alone.

    Args:
        counterfactual: The computed projection.

    Returns:
        A complete `SensitivityExplanation`, phrased as a projection throughout.
    """
    dims = [axis.value for axis in counterfactual.decisive_axes]
    promoted = counterfactual.promoted_axis.value
    demoted = counterfactual.demoted_axis.value

    if counterfactual.outcome == "too_close":
        narration = (
            f"Weighting {promoted} above {demoted} brings the two offers close "
            "enough together that this projection does not separate them. On the "
            "recorded bids it is a coin toss rather than a change of winner."
        )
        confidence = "low"
    elif counterfactual.outcome == "flipped":
        narration = (
            f"Weighting {promoted} above {demoted} is enough to change the "
            f"projected result: {counterfactual.alternative_winner} comes out ahead "
            f"instead of {counterfactual.original_winner}, because {promoted} is "
            f"where the two offers differ most."
        )
        confidence = "medium"
    else:
        narration = (
            f"Even weighting {promoted} above {demoted}, "
            f"{counterfactual.original_winner} stays ahead on this projection — its "
            "advantage does not rest on the priority that was demoted."
        )
        confidence = "medium"

    return SensitivityExplanation(
        likely_winner=(
            "too_close"
            if counterfactual.outcome == "too_close"
            else counterfactual.alternative_winner
        ),
        decisive_dimensions=dims,
        narration=narration,
        confidence=confidence,
        caveat=CAVEAT,
    )
