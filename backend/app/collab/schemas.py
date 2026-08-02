# Built with Spec4 AI - https://spec4.ai
"""The typed outputs of the six negotiation turns.

**Narrow schemas, one per call, rather than one wide schema for the run.** A
model that botches its response then degrades only its own panel: a malformed
opening bid costs one seller's column, not the counter-offers and the award as
well. A single run-shaped schema would make every failure total.

## Permissive bounds, deterministic repair

None of these models constrains cardinality -- `CounterOfferSet` does not
require exactly two offers, `Award.per_priority_scoring` does not require four
entries. That is the same call this project made for `CoordinatorDraft` and
`SpecialistAnswer` in v5, for the same arithmetic reason: PydanticAI binds
typed output through a synthetic output tool, so a bound *in the output type*
makes the framework reject and **re-prompt**, silently spending a second
provider request to fix something the sequencer can repair for free.

Strictness at the boundary the framework enforces buys a retry. Strictness
after it buys a repair. The run's budget only affords the second.

## Field order is load-bearing on `Award`

Structured decoding emits fields in declaration order, so
`per_priority_scoring` is declared **before** `rationale`. The model therefore
commits to its arithmetic before it writes the prose explaining it. Written the
other way round, the rationale comes first and the scores get fitted to it --
which is exactly the "plausible-sounding lie" the reconciliation check exists
to catch, made harder to catch.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class NegotiationStage(StrEnum):
    """The six stages, in order. Two of them spend no model call.

    Named rather than numbered in the wire payloads so a client cannot drift
    on an off-by-one, and so a log line says what happened rather than "stage
    4".
    """

    RFQ = "rfq"
    OPENING_BIDS = "opening_bids"
    COUNTER_OFFERS = "counter_offers"
    COUNTER_DELIVERY = "counter_delivery"
    FINAL_BIDS = "final_bids"
    AWARD = "award"


class Bid(BaseModel):
    """One seller's offer at one stage.

    The four numeric fields are exactly the scenario's four axes, so the
    deterministic scorer can rank two bids without parsing prose. `notes` is
    where a seller says anything the schema has no slot for -- deliberately the
    only free-text field, because a typed slot physically cannot carry a rival
    quote.

    Attributes:
        seller_id: Who is bidding. Overwritten server-side from the agent that
            was actually asked; see `agents.py`.
        stage: Which round this bid belongs to.
        unit_price: Price per unit, in the scenario's price unit.
        quantity: How much the seller commits to supply.
        delivery_days: Lead time in days.
        warranty_months: Warranty length in months.
        notes: Anything else the seller wants to say, in its own words.
        concessions_made: What it gave ground on since its opening bid. Empty
            on an opening bid.
    """

    seller_id: str = ""
    stage: str = ""
    unit_price: float = 0.0
    quantity: float = 0.0
    delivery_days: float = 0.0
    warranty_months: float = 0.0
    notes: str = ""
    concessions_made: list[str] = Field(default_factory=list)


class CounterOffer(BaseModel):
    """The buyer's targeted push on one seller, on one term.

    One axis per counter, deliberately. Pressing a seller everywhere at once
    tells it nothing about where the buyer's value actually is, and the
    capability's whole point is that the buyer targets *each* seller on its own
    weakest axis rather than sending both the same letter.

    Attributes:
        seller_id: Which seller this is addressed to.
        targeted_term: The axis being pushed on: `price`, `delivery`,
            `quantity` or `warranty`.
        ask: What the buyer is asking for on that term, in prose.
        justification: Why, referring to the stated priorities. **Must not
            reference the other seller** -- the leak lint checks it before
            delivery.
    """

    seller_id: str = ""
    targeted_term: str = ""
    ask: str = ""
    justification: str = ""


class CounterOfferSet(BaseModel):
    """Both counter-offers, produced in one buyer call.

    One call rather than two: the buyer is making a single comparison across
    both bids and dividing its pressure between them, so splitting it would
    both double the cost and lose the comparison that makes the targeting
    sensible.

    Deliberately not bounded to exactly two -- see the module docstring.
    `validator.repair_counter_offers` trims and fills.

    Attributes:
        offers: One counter per seller.
    """

    offers: list[CounterOffer] = Field(default_factory=list)


class PriorityScore(BaseModel):
    """The buyer's own score for one seller on one priority.

    The model's arithmetic, kept separate from the deterministic scorer's. The
    reconciliation check compares the two: a winner the model declared that its
    own scores do not support is the failure this array exists to expose.

    Attributes:
        seller_id: Whose score this is.
        priority: Which axis.
        score: The buyer's rating, 0--100.
        comment: One line on why.
    """

    seller_id: str = ""
    priority: str = ""
    score: float = 0.0
    comment: str = ""


class Award(BaseModel):
    """The buyer's decision, with its working shown before its reasoning.

    **`per_priority_scoring` is declared before `rationale` on purpose** -- see
    the module docstring. The scores are the claim; the rationale is the story
    about the claim, and a story written first would drag the scores after it.

    Attributes:
        winner_id: The seller being awarded the contract.
        per_priority_scoring: The buyer's per-axis scores for both sellers,
            emitted before any prose.
        rationale: Why this seller won, in the buyer's words.
        priority_references: The stated priorities the rationale leans on.
        runner_up_note: What the losing bid was better at. Present so the award
            cannot pretend the choice was obvious when it was a trade-off.
    """

    winner_id: str = ""
    per_priority_scoring: list[PriorityScore] = Field(default_factory=list)
    rationale: str = ""
    priority_references: list[str] = Field(default_factory=list)
    runner_up_note: str = ""
