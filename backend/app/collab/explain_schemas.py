# Built with Spec4 AI - https://spec4.ai
"""The two post-award explanation shapes, and the per-run enums that bound them.

Separate from `Award` on purpose: a conformance failure in the reveal must
degrade only the reveal, never the award payload the visitor already has. Same
narrow-schema-per-call rule the negotiation turns follow.

## Numeric fields are echo-only

`opening_value` and `final_value` are values the model was **given**. It may
repeat them; it may not compute, round or interpolate a new one. A plausible
figure that is subtly wrong is indistinguishable from a real one to a visitor,
and this is the surface where a wrong number would look most authoritative --
it arrives at the end, framed as the explanation of everything before it.
`explain_validator.no_invented_numbers` enforces this against a whitelist built
from the input payload.

## `binding_constraint` is nullable, and that is the point

A closed enum of *that party's own* constraint ids, plus `None`. The nullable
option is what lets a model say "nothing forced this" instead of reaching for
the nearest plausible constraint -- which is the signature failure the phase
names: post-hoc rationalisation, invisible without recomputing slack.

## The sensitivity enums are built per run

`build_sensitivity_model()` closes `likely_winner` over the seller ids that
actually bid and `decisive_dimensions` over this scenario's declared axes, so
an off-list supplier or term is **structurally unrepresentable** rather than
merely validated away. PydanticAI is capped at one request per step here, so a
violation fails the step and falls back to the template rather than silently
buying a re-prompt the run's budget cannot afford.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, create_model


class AxisStance(StrEnum):
    """What a party did on one axis between its opening and final bid.

    Recomputed from the actual values by `explain_validator.computed_stance`
    and compared against whatever the model claimed. The model's answer is a
    hypothesis; the arithmetic is the fact.
    """

    CONCEDED = "conceded"
    HELD_FIRM = "held_firm"


#: The sealed constraint each axis could plausibly be bound by, for a seller.
#: A closed vocabulary, so "held firm because of X" names something real.
SELLER_CONSTRAINT_IDS: tuple[str, ...] = (
    "cost_floor",
    "capacity_ceiling",
    "delivery_capability",
    "warranty_liability_limit",
)

#: The buyer's equivalents. Kept separate because a party may only ever cite
#: its *own* constraints -- citing the rival's would be the leak this whole
#: example exists to prevent, arriving in the one panel that unseals anything.
BUYER_CONSTRAINT_IDS: tuple[str, ...] = ("budget_ceiling", "batna")


class AxisExplanation(BaseModel):
    """Why one party moved, or did not, on one axis.

    Attributes:
        axis: Which term. One of `price`, `delivery`, `quantity`, `warranty`.
        stance: What the party did. Checked against the recomputed delta.
        opening_value: Echoed from the opening bid. Not computed.
        final_value: Echoed from the best-and-final bid. Not computed.
        binding_constraint: Which of this party's own sealed constraints forced
            the move, or `None` when none did. Checked against recomputed
            slack.
        explanation: One or two sentences, in the party's own terms.
    """

    axis: str = ""
    stance: str = ""
    opening_value: float = 0.0
    final_value: float = 0.0
    binding_constraint: str | None = None
    explanation: str = ""


class PartyReveal(BaseModel):
    """One party's unsealed position, explained axis by axis.

    Attributes:
        party_id: Whose position this is.
        headline: One line summarising what constrained this party.
        axes: One entry per negotiable term.
    """

    party_id: str = ""
    headline: str = ""
    axes: list[AxisExplanation] = Field(default_factory=list)


class RevealExplanation(BaseModel):
    """The post-award unsealing, for every party in the run.

    Permissive on cardinality for the reason the negotiation schemas are: a
    bound in the output type makes PydanticAI reject and re-prompt, and this
    run has no budget for that. The validator repairs and the template covers
    anything it cannot.

    Attributes:
        parties: One block per participant.
    """

    parties: list[PartyReveal] = Field(default_factory=list)


class SensitivityExplanation(BaseModel):
    """The narrated counterfactual. The base shape, before per-run narrowing.

    Attributes:
        likely_winner: Who the alternative weighting favours.
        decisive_dimensions: The terms that moved the result.
        narration: Why the shift happens, in prose.
        confidence: How firmly the projection separates the two bids.
        caveat: That this is a projection from recorded bids, not a re-run.
    """

    likely_winner: str = ""
    decisive_dimensions: list[str] = Field(default_factory=list)
    narration: str = ""
    confidence: str = ""
    caveat: str = ""


def _literal_of(values: Sequence[str]) -> Any:
    """Build a `Literal` type over values known only at runtime.

    Opaque to mypy by necessity: the legal values are a property of the run,
    so the type cannot be written down statically. The single `type: ignore`
    is confined here rather than repeated at each field.

    Args:
        values: The permitted strings.

    Returns:
        A `Literal` type admitting exactly those values.
    """
    literal: Any = Literal
    return literal[tuple(values)]


def _list_of(item: Any) -> Any:
    """Build a `list[...]` type over a runtime-constructed item type."""
    return list[item]


def build_sensitivity_model(
    *, seller_ids: list[str], axis_ids: list[str]
) -> type[SensitivityExplanation]:
    """Build a sensitivity schema closed over this run's sellers and axes.

    The point is structural: with `likely_winner` typed as a `Literal` over the
    two ids that actually bid, an off-roster supplier cannot be represented at
    all — the model has no way to name one, rather than being told not to.

    Built per run rather than declared statically because the legal values are
    a property of the run, not of the code. `too_close` is admitted alongside
    the seller ids so the model can decline to pick, which the computed
    projection sometimes does too.

    Args:
        seller_ids: The sellers whose bids are being compared.
        axis_ids: This scenario's declared axes.

    Returns:
        A subclass of `SensitivityExplanation` with both fields narrowed.
    """
    winner_values = [*seller_ids, "too_close"]
    model: type[SensitivityExplanation] = create_model(
        "RunSensitivityExplanation",
        __base__=SensitivityExplanation,
        likely_winner=(_literal_of(winner_values), ...),
        decisive_dimensions=(_list_of(_literal_of(axis_ids)), ...),
    )
    return model
