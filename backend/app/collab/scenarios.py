# Built with Spec4 AI - https://spec4.ai
"""The collaboration slice's fixed cast: one buyer, two rival sellers.

Typed Python literals rather than a table or a YAML file, for the reasons the
rest of this repo already applies to closed sets like the specialist roster:
mypy checks these nested structures, a redeploy replaces them without a
migration, and there is no serialisation dependency to add.

## What is here

Three kinds of thing, and the difference between them is the whole point:

- the **identity cards**, which any peer may publish to anyone;
- the **scenario catalogue** and **priority weightings**, which are public
  configuration a visitor chooses from;
- the **sealed private constraints**, which one seller must never see from the
  other.

They share a file. Nothing about that grants access -- see the note above the
catalogue below. Publishing a card and unsealing a constraint are different
operations, and only one of them is free.

## Why an agent id is not on the card

A2A's `AgentCard` has no identifier field: a card describes an agent, it does
not address one. The bus needs an address, the UI needs a role pill and an
accent colour, and none of those are A2A's. `CollabAgent` wraps the card with
them, exactly as `orchestrated/roster.py` wraps a specialist with the parts
that never cross the wire -- which keeps `protocol.py` an honest statement of
the protocol's shape rather than the protocol plus whatever this app needed.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from backend.app.collab.protocol import (
    AgentCapabilities,
    AgentCard,
    AgentProvider,
    AgentSkill,
    ToolAccess,
)

#: The A2A data-model version these card shapes follow. Stated on every card
#: because a peer inspecting one needs to know which spelling of the schema it
#: is reading, even when -- as here -- there is no wire to read it over.
PROTOCOL_VERSION: Final[str] = "0.3.0"

#: Every agent in this slice is knowledge-only, so every card declares the same
#: provider: one owner, one repo. That is the honest answer and it is also the
#: candid note the overview makes prominently -- a card claiming three separate
#: organisations would stage the trust boundary in the data as well as in the
#: teaching, which is the one thing the screen promises it does not do.
_PROVIDER: Final[AgentProvider] = AgentProvider(
    organization="BWS4 · Spec4 reference agent",
    url="https://spec4.ai",
)

#: No transport, so no transport features. Every flag is False and every flag
#: is accurate: there is nothing to stream over and nowhere to push to.
_CAPABILITIES: Final[AgentCapabilities] = AgentCapabilities(
    streaming=False,
    push_notifications=False,
    state_transition_history=False,
)


@dataclass(frozen=True)
class CollabAgent:
    """One participant: its address, its presentation, and its published card.

    Attributes:
        id: Stable address. What the message bus routes on, and the only thing
            `context_for` matches -- so these must be unique.
        role: `buyer` or `seller`. Drives the role pill and, later, which
            sealed constraints an agent may load.
        color: Accent from the design mock's palette, so a track is
            recognisable at a glance across the run.
        card: What this peer publishes about itself.
    """

    id: str
    role: str
    color: str
    card: AgentCard


BUYER: Final[CollabAgent] = CollabAgent(
    id="buyer",
    role="buyer",
    color="#38bdf8",
    card=AgentCard(
        name='Buyer Agent "Procura"',
        description=(
            "Acts for the visitor. Composes the request for quotation without a "
            "model call, sends and receives peer messages, and holds a private "
            "budget ceiling it never discloses to either seller."
        ),
        version="1.0.0",
        protocol_version=PROTOCOL_VERSION,
        provider=_PROVIDER,
        capabilities=_CAPABILITIES,
        skills=[
            AgentSkill(
                id="requirement_drafting",
                name="Requirement drafting",
                description=(
                    "Turns a scenario and a priority weighting into a structured "
                    "request for quotation, deterministically and with no model "
                    "call."
                ),
                tags=["procurement", "deterministic"],
            ),
            AgentSkill(
                id="term_comparison",
                name="Term-by-term comparison",
                description=(
                    "Compares bids that are deliberately not like-for-like, axis "
                    "by axis, against the visitor's stated priorities."
                ),
                tags=["analysis"],
            ),
            AgentSkill(
                id="targeted_counter_offer",
                name="Targeted counter-offer",
                description=(
                    "Presses each seller on its own weakest axis rather than "
                    "sending both the same counter."
                ),
                tags=["negotiation"],
            ),
            AgentSkill(
                id="award_justification",
                name="Award justification",
                description=(
                    "Chooses a winner and explains the choice against the stated "
                    "priorities, so a mismatch is visible to the visitor."
                ),
                tags=["negotiation", "explanation"],
            ),
        ],
        tool_access=ToolAccess.NONE,
        default_input_modes=["application/json"],
        default_output_modes=["application/json"],
    ),
)

NORTHWIND: Final[CollabAgent] = CollabAgent(
    id="northwind",
    role="seller",
    color="#fbbf24",
    card=AgentCard(
        name='Seller Agent "Northwind Supply"',
        description=(
            "A rival supplier. Receives only the messages addressed to it, and "
            "bids against a private cost floor and stock position it never "
            "discloses -- to the buyer or to the other seller."
        ),
        version="1.0.0",
        protocol_version=PROTOCOL_VERSION,
        provider=_PROVIDER,
        capabilities=_CAPABILITIES,
        skills=[
            AgentSkill(
                id="quoting",
                name="Quoting",
                description=(
                    "Prices a request against its own sealed constraints, without "
                    "sight of any rival quote."
                ),
                tags=["procurement"],
            ),
            AgentSkill(
                id="stock_allocation",
                name="Stock allocation",
                description=(
                    "Decides how much of the requested quantity it can commit, "
                    "and whether to offer a partial fulfilment."
                ),
                tags=["logistics"],
            ),
            AgentSkill(
                id="delivery_scheduling",
                name="Delivery scheduling",
                description="Commits to a lead time it can actually meet.",
                tags=["logistics"],
            ),
            AgentSkill(
                id="concession_strategy",
                name="Concession strategy",
                description=(
                    "Decides which axis to concede on when countered, and where "
                    "to hold firm because its sealed floor will not move."
                ),
                tags=["negotiation"],
            ),
        ],
        tool_access=ToolAccess.NONE,
        default_input_modes=["application/json"],
        default_output_modes=["application/json"],
    ),
)

MERIDIAN: Final[CollabAgent] = CollabAgent(
    id="meridian",
    role="seller",
    color="#34d399",
    card=AgentCard(
        name='Seller Agent "Meridian Trading"',
        description=(
            "The other rival supplier. Receives only the messages addressed to "
            "it, and competes on warranty and support terms rather than on "
            "headline price -- which is what makes the two bids hard to compare."
        ),
        version="1.0.0",
        protocol_version=PROTOCOL_VERSION,
        provider=_PROVIDER,
        capabilities=_CAPABILITIES,
        skills=[
            AgentSkill(
                id="quoting",
                name="Quoting",
                description=(
                    "Prices a request against its own sealed constraints, without "
                    "sight of any rival quote."
                ),
                tags=["procurement"],
            ),
            AgentSkill(
                id="warranty_structuring",
                name="Warranty structuring",
                description=(
                    "Trades warranty length against price, within a sealed "
                    "liability limit."
                ),
                tags=["negotiation"],
            ),
            AgentSkill(
                id="support_capacity_planning",
                name="Support capacity planning",
                description=(
                    "Commits to a support level its sealed capacity ceiling can "
                    "sustain."
                ),
                tags=["logistics"],
            ),
            AgentSkill(
                id="concession_strategy",
                name="Concession strategy",
                description=(
                    "Decides which axis to concede on when countered, and where "
                    "to hold firm because its sealed floor will not move."
                ),
                tags=["negotiation"],
            ),
        ],
        tool_access=ToolAccess.NONE,
        default_input_modes=["application/json"],
        default_output_modes=["application/json"],
    ),
)

#: Buyer first, then the two sellers in the order their tracks appear on screen.
#: Order is display order, as it is in the frontend's example-app catalogue.
IDENTITY_CARDS: Final[tuple[CollabAgent, ...]] = (BUYER, NORTHWIND, MERIDIAN)

#: The seller ids, for the opacity rules a later phase applies on top of the
#: bus. Derived rather than restated, so it cannot drift from the cast above.
SELLER_IDS: Final[tuple[str, ...]] = tuple(
    agent.id for agent in IDENTITY_CARDS if agent.role == "seller"
)


# ---------------------------------------------------------------------------
# The procurement scenario catalogue, the sealed constraints, and the weightings
# ---------------------------------------------------------------------------
#
# Everything below is authored as typed Python literals rather than YAML or
# JSON, so mypy strict checks these deeply nested fixtures and no serialisation
# dependency is added. The semantics are the same either way: read-only, and
# changed only by a redeploy.
#
# ## Why the sealed constraints live in this file, next to the scenarios
#
# Because file separation would be a lie. Splitting them out would suggest the
# filesystem is providing a boundary it is not -- any module can import any
# module. The sealing is enforced at *access* time by `collab/opacity.py`,
# which is the only sanctioned reader: `constraints_for(agent_id)` has no code
# path that returns another party's position. Putting the constraints here,
# beside the scenario they belong to, keeps that honest: the protection is the
# access policy, and it is worth being unable to point at a directory and
# pretend otherwise.
#
# ## Why the numbers are what they are
#
# The demo's headline claim is that the two bids are genuinely *non-comparable*
# -- that the buyer's judgment is a real trade-off rather than a dominance
# check. That is a property of these constraint sets, not of any model, so it
# is tuned here and proved by the fixture-tuning test before a single model
# call exists. Each scenario is hand-tuned so at least one pair of weightings
# ranks a different seller first.


class AxisId(StrEnum):
    """The four negotiable term axes, identical across every scenario.

    A closed enum rather than free strings: the visitor's weighting is
    validated as a vector over exactly these keys, which is what lets this
    example accept visitor input with no moderation gate at all.
    """

    PRICE = "price"
    DELIVERY = "delivery"
    QUANTITY = "quantity"
    WARRANTY = "warranty"


class AxisDirection(StrEnum):
    """Which way is better on an axis.

    Carried per axis rather than assumed, because it differs: a lower price is
    better, a longer warranty is better, and scoring code that guessed would be
    wrong half the time.
    """

    LOWER_IS_BETTER = "lower_is_better"
    HIGHER_IS_BETTER = "higher_is_better"


@dataclass(frozen=True)
class TermAxis:
    """One negotiable dimension of a scenario, with the range it is scored over.

    `best` and `worst` bound the axis for scoring. They are declared per
    scenario rather than derived from the two bids on the day, and the
    difference matters: min-max over exactly two bids collapses every axis to
    1 and 0, so every weighting would reduce to "which seller won more axes"
    and the arithmetic would stop reflecting *how much* better a bid was.

    Attributes:
        id: Which axis this is.
        label: What the visitor sees.
        unit: The unit values are quoted in.
        direction: Which end of the range is good.
        best: The value scoring treats as full marks.
        worst: The value scoring treats as zero. Values beyond either bound are
            clamped, so an outlying bid cannot score above 1 or below 0.
    """

    id: AxisId
    label: str
    unit: str
    direction: AxisDirection
    best: float
    worst: float


@dataclass(frozen=True)
class BuyerPosition:
    """The buyer's own sealed position for one scenario.

    **Never publish this, and never let it reach the RFQ.** A BATNA is private
    by definition -- a seller who knew what the buyer would settle for would
    price to it, which is the whole reason a buyer keeps one to itself. It is
    nested inside `Scenario` rather than sitting loose beside the public fields
    so that "sealed" is visible at every use site, and it is readable only
    through `opacity.constraints_for("buyer")`.

    Attributes:
        budget_ceiling: The most the buyer will pay per unit.
        batna: Its best alternative to a negotiated agreement, in prose.
        reveal_headline: One line unsealed after the award.
        explanation_seed: Material the reveal explanation is written from.
    """

    budget_ceiling: float
    batna: str
    reveal_headline: str
    explanation_seed: str


@dataclass(frozen=True)
class Scenario:
    """One pre-tuned procurement situation the visitor can select.

    Attributes:
        id: Stable identifier. The closed enum a request is validated against.
        goods: What is being bought.
        baseline_requirement: What the buyer needs, in the visitor's words.
            Public: it is what the RFQ asks for.
        buyer_position: The buyer's **sealed** position. Not public, and never
            part of the RFQ -- see `BuyerPosition`.
        axes: The four negotiable dimensions, always in `AxisId` order.
        partial_fulfilment_allowed: Whether a seller may bid for less than the
            full quantity. True in every shipped scenario, because a seller
            that cannot cover the order is precisely what makes the quantity
            axis a real trade-off rather than a pass/fail.
    """

    id: str
    goods: str
    baseline_requirement: str
    buyer_position: BuyerPosition
    axes: tuple[TermAxis, ...]
    partial_fulfilment_allowed: bool

    def axis(self, axis_id: AxisId) -> TermAxis:
        """Return the axis with this id.

        Args:
            axis_id: Which axis to look up.

        Returns:
            The matching `TermAxis`.

        Raises:
            KeyError: If the scenario does not declare that axis.
        """
        for candidate in self.axes:
            if candidate.id is axis_id:
                return candidate
        raise KeyError(f"Scenario {self.id!r} declares no axis {axis_id!r}")

    def public(self) -> PublicScenario:
        """Project to the fields a seller may see.

        **Use this anywhere a scenario crosses to an agent or the wire.**
        Passing the whole `Scenario` would carry `buyer_position` -- the
        buyer's ceiling and BATNA -- into a seller's turn context, which is
        precisely the leak the opacity policy exists to prevent. That is not
        hypothetical: it is the bug the exhaustive context test caught when
        `TurnContext` first held a `Scenario`.

        Returns:
            The scenario without the buyer's sealed position.
        """
        return PublicScenario(
            id=self.id,
            goods=self.goods,
            baseline_requirement=self.baseline_requirement,
            axes=self.axes,
            partial_fulfilment_allowed=self.partial_fulfilment_allowed,
        )


@dataclass(frozen=True)
class PublicScenario:
    """A scenario with the buyer's sealed position removed.

    Structurally incapable of carrying a BATNA or a budget ceiling, because it
    has no field for one. That is the point: a projection that *omits* the
    sealed data cannot leak it however carelessly it is passed around, whereas
    a `Scenario` handed to the wrong place leaks by default.

    Attributes:
        id: Stable identifier.
        goods: What is being bought.
        baseline_requirement: What the buyer needs, in prose.
        axes: The four negotiable dimensions.
        partial_fulfilment_allowed: Whether a partial quantity may be bid.
    """

    id: str
    goods: str
    baseline_requirement: str
    axes: tuple[TermAxis, ...]
    partial_fulfilment_allowed: bool


@dataclass(frozen=True)
class PrivateConstraint:
    """One seller's sealed negotiating position for one scenario.

    **Never publish this.** It is readable only through
    `opacity.constraints_for()`, and only by the seller it belongs to. The
    reveal fields are released by the post-award stage, not before.

    Attributes:
        scenario_id: Which scenario this position belongs to.
        seller_id: Whose position it is.
        cost_floor: The unit price below which this seller will not go.
        capacity_ceiling: The most it can supply, in the scenario's quantity
            unit. Below the buyer's requirement for at least one seller in
            every scenario -- that gap is what makes partial fulfilment a real
            trade-off.
        delivery_capability_days: The fastest it can deliver.
        warranty_liability_limit_months: The longest warranty it will carry.
        reveal_headline: One line unsealed after the award.
        explanation_seed: The material the reveal explanation is written from,
            saying why this seller held firm or conceded.
    """

    scenario_id: str
    seller_id: str
    cost_floor: float
    capacity_ceiling: int
    delivery_capability_days: int
    warranty_liability_limit_months: int
    reveal_headline: str
    explanation_seed: str


@dataclass(frozen=True)
class PriorityWeighting:
    """A selectable statement of what the visitor cares about.

    Attributes:
        id: Stable identifier; the closed enum a request is validated against.
        label: What the visitor picks.
        description: One line of explanation.
        weights: Per-axis weights over every `AxisId`, summing to 100.
            Validated as a closed numeric vector server-side -- there is no
            free-text input anywhere in this example.
    """

    id: str
    label: str
    description: str
    weights: Mapping[AxisId, int]


@dataclass(frozen=True)
class Bid:
    """A seller's offer, as one value per axis.

    Used two ways: as the shape a seller agent returns in Phase 3, and here as
    the hand-authored `REPRESENTATIVE_BIDS` that prove the fixtures are tuned.

    Attributes:
        seller_id: Who is bidding.
        values: One value per axis, in the axis's own unit.
    """

    seller_id: str
    values: Mapping[AxisId, float]


def _axes(
    *,
    price_unit: str,
    price_best: float,
    price_worst: float,
    delivery_best: float,
    delivery_worst: float,
    quantity_label: str,
    quantity_unit: str,
    quantity_best: float,
    quantity_worst: float,
    warranty_label: str,
    warranty_unit: str,
    warranty_best: float,
    warranty_worst: float,
) -> tuple[TermAxis, ...]:
    """Build a scenario's four axes, always in `AxisId` order.

    A helper rather than four literals per scenario: the directions are fixed
    (cheaper and sooner are better; more and longer are better) and repeating
    them three times is three chances to write one backwards.

    Args:
        price_unit: Unit the price axis is quoted in.
        price_best: Price scoring treats as full marks.
        price_worst: Price scoring treats as zero.
        delivery_best: Lead time in days scoring treats as full marks.
        delivery_worst: Lead time in days scoring treats as zero.
        quantity_label: What the quantity axis is called here.
        quantity_unit: Unit the quantity axis is counted in.
        quantity_best: Quantity scoring treats as full marks.
        quantity_worst: Quantity scoring treats as zero.
        warranty_label: What the warranty axis is called here.
        warranty_unit: Unit the warranty axis is measured in.
        warranty_best: Warranty scoring treats as full marks.
        warranty_worst: Warranty scoring treats as zero.

    Returns:
        The four axes, in `AxisId` declaration order.
    """
    return (
        TermAxis(
            id=AxisId.PRICE,
            label="Unit price",
            unit=price_unit,
            direction=AxisDirection.LOWER_IS_BETTER,
            best=price_best,
            worst=price_worst,
        ),
        TermAxis(
            id=AxisId.DELIVERY,
            label="Delivery lead time",
            unit="days",
            direction=AxisDirection.LOWER_IS_BETTER,
            best=delivery_best,
            worst=delivery_worst,
        ),
        TermAxis(
            id=AxisId.QUANTITY,
            label=quantity_label,
            unit=quantity_unit,
            direction=AxisDirection.HIGHER_IS_BETTER,
            best=quantity_best,
            worst=quantity_worst,
        ),
        TermAxis(
            id=AxisId.WARRANTY,
            label=warranty_label,
            unit=warranty_unit,
            direction=AxisDirection.HIGHER_IS_BETTER,
            best=warranty_best,
            worst=warranty_worst,
        ),
    )


SCENARIO_LAPTOPS: Final[Scenario] = Scenario(
    id="refurbished_laptops_school",
    goods="240 refurbished 14-inch laptops for a school district rollout",
    baseline_requirement=(
        "240 units, delivered before the autumn term starts in 30 days, with at "
        "least a 12-month hardware warranty."
    ),
    buyer_position=BuyerPosition(
        budget_ceiling=430.0,
        batna=(
            "The district's incumbent supplier will do all 240 at 430 per unit in "
            "45 days with a 12-month warranty. Anything worse than that on "
            "balance is not worth switching for."
        ),
        reveal_headline="Would not have paid above 430, and had a 45-day fallback.",
        explanation_seed=(
            "The district could always fall back on its incumbent at 430 per "
            "unit, so any bid above that lost to doing nothing. That ceiling is "
            "why the buyer pressed on price rather than accepting the first "
            "workable offer, and why a partial order at a low price stayed "
            "competitive with a full order near the ceiling."
        ),
    ),
    axes=_axes(
        price_unit="GBP per laptop",
        price_best=350,
        price_worst=450,
        delivery_best=7,
        delivery_worst=45,
        quantity_label="Units supplied",
        quantity_unit="laptops",
        quantity_best=240,
        quantity_worst=120,
        warranty_label="Hardware warranty",
        warranty_unit="months",
        warranty_best=42,
        warranty_worst=6,
    ),
    partial_fulfilment_allowed=True,
)

SCENARIO_REAGENTS: Final[Scenario] = Scenario(
    id="lab_reagents_bulk",
    goods="500 litres of phosphate buffer solution for a research lab",
    baseline_requirement=(
        "500 litres, delivered within 21 days, with at least a 12-month "
        "guaranteed shelf life on arrival."
    ),
    buyer_position=BuyerPosition(
        budget_ceiling=31.0,
        batna=(
            "The lab can reorder in two smaller batches from its current supplier "
            "at 31 per litre with a 12-month shelf life, but that costs it a "
            "month of scheduling."
        ),
        reveal_headline="Ceiling of 31 per litre, with a slower two-batch fallback.",
        explanation_seed=(
            "The lab had a workable fallback at 31 per litre, so its ceiling was "
            "the fallback price rather than a budget line. That is why lead time "
            "mattered more here than it looks: the alternative was not expensive, "
            "it was slow."
        ),
    ),
    axes=_axes(
        price_unit="GBP per litre",
        price_best=18,
        price_worst=34,
        delivery_best=5,
        delivery_worst=40,
        quantity_label="Volume supplied",
        quantity_unit="litres",
        quantity_best=500,
        quantity_worst=250,
        warranty_label="Guaranteed shelf life",
        warranty_unit="months",
        warranty_best=30,
        warranty_worst=6,
    ),
    partial_fulfilment_allowed=True,
)

SCENARIO_TYRES: Final[Scenario] = Scenario(
    id="fleet_tyres_replacement",
    goods="320 commercial van tyres for a regional delivery fleet",
    baseline_requirement=(
        "320 tyres, fitted within 14 days to avoid taking vans off the road, "
        "with a tread-life warranty of at least two years."
    ),
    buyer_position=BuyerPosition(
        budget_ceiling=115.0,
        batna=(
            "The fleet can run on its current tyres for another six weeks before "
            "any van is unroadworthy, so it can afford to walk away from a bad "
            "quote -- but not from a good one on price."
        ),
        reveal_headline="Six weeks of runway and a hard 115 per tyre ceiling.",
        explanation_seed=(
            "Because no van was off the road yet, the buyer could hold out. Its "
            "115 ceiling ruled out the premium compound at list price outright, "
            "so the long-warranty bid only won when the weighting made tread life "
            "worth paying a premium for."
        ),
    ),
    axes=_axes(
        price_unit="GBP per tyre",
        price_best=78,
        price_worst=130,
        delivery_best=3,
        delivery_worst=28,
        quantity_label="Tyres supplied",
        quantity_unit="tyres",
        quantity_best=320,
        quantity_worst=160,
        warranty_label="Tread-life warranty",
        warranty_unit="months",
        warranty_best=72,
        warranty_worst=24,
    ),
    partial_fulfilment_allowed=True,
)

#: The catalogue, in the order a visitor sees it.
SCENARIOS: Final[tuple[Scenario, ...]] = (
    SCENARIO_LAPTOPS,
    SCENARIO_REAGENTS,
    SCENARIO_TYRES,
)

#: The closed set a `scenario_id` is validated against.
SCENARIO_IDS: Final[frozenset[str]] = frozenset(s.id for s in SCENARIOS)

SCENARIOS_BY_ID: Final[Mapping[str, Scenario]] = {s.id: s for s in SCENARIOS}


# --- Sealed private constraints --------------------------------------------
#
# Each pair is hand-tuned so the two sellers are strong on *different* axes.
# That orthogonality is the demo: if one seller dominated the other on every
# term, the buyer's award would be a dominance check and there would be nothing
# to teach. The fixture-tuning test proves it holds by scoring the
# representative bids below under every weighting.

SEALED_CONSTRAINTS: Final[tuple[PrivateConstraint, ...]] = (
    # Laptops: Northwind is clearing existing stock -- cheap and immediate, but
    # it only has 180 units and will not warrant refurbished hardware beyond a
    # year. Meridian sources new-old-stock to order: dearer and slower, but it
    # can cover the whole district and stand behind it for three years.
    PrivateConstraint(
        scenario_id="refurbished_laptops_school",
        seller_id="northwind",
        cost_floor=356.0,
        capacity_ceiling=180,
        delivery_capability_days=14,
        warranty_liability_limit_months=12,
        reveal_headline=(
            "Held 180 units in stock and would not warrant beyond 12 months."
        ),
        explanation_seed=(
            "Northwind was clearing an existing pallet: its cost floor of 356 was "
            "low because the stock was already paid for, and it could ship in two "
            "weeks. But 180 units was everything it had, and its refurbishment "
            "grade would not support a warranty past 12 months at any price. It "
            "conceded on price under counter-offer because that was the only axis "
            "with room; it held firm on quantity and warranty because neither was "
            "a pricing decision."
        ),
    ),
    PrivateConstraint(
        scenario_id="refurbished_laptops_school",
        seller_id="meridian",
        cost_floor=402.0,
        capacity_ceiling=300,
        delivery_capability_days=25,
        warranty_liability_limit_months=36,
        reveal_headline=(
            "Could cover all 240 with a 36-month warranty, but never below 402."
        ),
        explanation_seed=(
            "Meridian sources to order, so it could commit the full 240 units and "
            "carry a three-year warranty its refurbishment grade actually "
            "supports. Its cost floor of 402 came from buying stock it did not "
            "already hold, which is why it could not follow Northwind down on "
            "price. It conceded on warranty length and lead time when countered, "
            "because both cost it less than a price cut it could not afford."
        ),
    ),
    # Reagents: Northwind is fast and cheap but cold-chain limited -- 300 litres
    # and a short shelf life. Meridian is slow and dear but can do the full
    # volume with a two-year guarantee.
    PrivateConstraint(
        scenario_id="lab_reagents_bulk",
        seller_id="northwind",
        cost_floor=19.5,
        capacity_ceiling=300,
        delivery_capability_days=7,
        warranty_liability_limit_months=9,
        reveal_headline=(
            "Cold-chain capacity capped it at 300 litres and a 9-month shelf life."
        ),
        explanation_seed=(
            "Northwind buffers in small batches close to the customer, which is "
            "why it could deliver in a week at a cost floor of 19.50. The same "
            "process is why it could only guarantee nine months of shelf life and "
            "could not stage more than 300 litres of cold storage. It conceded "
            "delivery days it did not need and held firm on volume, which was a "
            "physical limit rather than a commercial one."
        ),
    ),
    PrivateConstraint(
        scenario_id="lab_reagents_bulk",
        seller_id="meridian",
        cost_floor=27.0,
        capacity_ceiling=600,
        delivery_capability_days=24,
        warranty_liability_limit_months=24,
        reveal_headline=(
            "Full 500 litres at a 24-month shelf life, but 24 days out and never "
            "under 27."
        ),
        explanation_seed=(
            "Meridian produces centrally to a pharmaceutical grade, which buys it "
            "a two-year shelf life and ample volume but costs it three and a half "
            "weeks of lead time and a cost floor of 27. It conceded shelf-life "
            "certification it was already carrying and held firm on lead time, "
            "which its production schedule fixed."
        ),
    ),
    # Tyres: both can cover the fleet, so quantity is not the trade-off here --
    # this scenario is a clean price-against-warranty choice, which makes it the
    # one where the weighting most visibly decides the winner.
    PrivateConstraint(
        scenario_id="fleet_tyres_replacement",
        seller_id="northwind",
        cost_floor=84.0,
        capacity_ceiling=400,
        delivery_capability_days=5,
        warranty_liability_limit_months=30,
        reveal_headline=(
            "Clearing an older compound: cheap and immediate, but only 30 months "
            "of tread warranty."
        ),
        explanation_seed=(
            "Northwind was moving a discontinued compound it had 400 of, so it "
            "could fit the whole fleet within a week at a cost floor of 84. That "
            "compound wears faster, which is why it would not guarantee past "
            "30 months however hard it was pressed. It conceded on price and "
            "fitting date and held firm on tread life, because the number was a "
            "property of the rubber rather than of the deal."
        ),
    ),
    PrivateConstraint(
        scenario_id="fleet_tyres_replacement",
        seller_id="meridian",
        cost_floor=109.0,
        capacity_ceiling=500,
        delivery_capability_days=21,
        warranty_liability_limit_months=66,
        reveal_headline=(
            "A premium compound good for five and a half years, but made to order "
            "and never under 109."
        ),
        explanation_seed=(
            "Meridian's compound genuinely lasts nearly twice as long, which is "
            "the whole of its case: a cost floor of 109 and three weeks to "
            "manufacture. It conceded tread-life certification and a small price "
            "movement when countered, and held firm on lead time because the "
            "tyres did not exist yet."
        ),
    ),
)

#: Indexed by `(scenario_id, seller_id)`. Read **only** through
#: `opacity.constraints_for()` -- see the access note above.
SEALED_CONSTRAINTS_BY_KEY: Final[Mapping[tuple[str, str], PrivateConstraint]] = {
    (c.scenario_id, c.seller_id): c for c in SEALED_CONSTRAINTS
}


# --- Priority weightings ---------------------------------------------------

PRIORITY_WEIGHTINGS: Final[tuple[PriorityWeighting, ...]] = (
    PriorityWeighting(
        id="lowest_price",
        label="Lowest price",
        description="Unit cost dominates; everything else is a tiebreak.",
        weights={
            AxisId.PRICE: 70,
            AxisId.DELIVERY: 10,
            AxisId.QUANTITY: 10,
            AxisId.WARRANTY: 10,
        },
    ),
    PriorityWeighting(
        id="fastest_delivery",
        label="Fastest delivery",
        description="Getting it soon matters more than getting it cheap.",
        weights={
            AxisId.PRICE: 10,
            AxisId.DELIVERY: 60,
            AxisId.QUANTITY: 15,
            AxisId.WARRANTY: 15,
        },
    ),
    PriorityWeighting(
        id="full_quantity",
        label="Full quantity required",
        description="A partial order is close to useless; cover the whole requirement.",
        weights={
            AxisId.PRICE: 15,
            AxisId.DELIVERY: 10,
            AxisId.QUANTITY: 60,
            AxisId.WARRANTY: 15,
        },
    ),
    PriorityWeighting(
        id="longest_warranty",
        label="Longest warranty",
        description="Total cost of ownership over years, not the price on the day.",
        weights={
            AxisId.PRICE: 15,
            AxisId.DELIVERY: 10,
            AxisId.QUANTITY: 15,
            AxisId.WARRANTY: 60,
        },
    ),
    PriorityWeighting(
        id="balanced",
        label="Balanced",
        description="No axis dominates; the best all-round offer wins.",
        weights={
            AxisId.PRICE: 25,
            AxisId.DELIVERY: 25,
            AxisId.QUANTITY: 25,
            AxisId.WARRANTY: 25,
        },
    ),
)

#: The closed set a `priority_weighting` id is validated against.
WEIGHTING_IDS: Final[frozenset[str]] = frozenset(w.id for w in PRIORITY_WEIGHTINGS)

WEIGHTINGS_BY_ID: Final[Mapping[str, PriorityWeighting]] = {
    w.id: w for w in PRIORITY_WEIGHTINGS
}

#: What a weighting's per-axis weights must sum to.
WEIGHT_TOTAL: Final[int] = 100


# --- Representative bids ---------------------------------------------------
#
# What each seller would plausibly offer given its sealed constraints. These
# are **fixture-tuning data, not run data**: no visitor ever sees them and no
# model is ever given them. They exist so the non-comparability claim is
# checkable arithmetic in CI rather than a quality problem that only shows up
# in Phase 3 after real model calls have been spent on it.

REPRESENTATIVE_BIDS: Final[Mapping[str, tuple[Bid, Bid]]] = {
    "refurbished_laptops_school": (
        Bid(
            seller_id="northwind",
            values={
                AxisId.PRICE: 372.0,
                AxisId.DELIVERY: 14.0,
                AxisId.QUANTITY: 180.0,
                AxisId.WARRANTY: 12.0,
            },
        ),
        Bid(
            seller_id="meridian",
            values={
                AxisId.PRICE: 418.0,
                AxisId.DELIVERY: 25.0,
                AxisId.QUANTITY: 240.0,
                AxisId.WARRANTY: 30.0,
            },
        ),
    ),
    "lab_reagents_bulk": (
        Bid(
            seller_id="northwind",
            values={
                AxisId.PRICE: 21.0,
                AxisId.DELIVERY: 7.0,
                AxisId.QUANTITY: 300.0,
                AxisId.WARRANTY: 9.0,
            },
        ),
        Bid(
            seller_id="meridian",
            values={
                AxisId.PRICE: 29.0,
                AxisId.DELIVERY: 26.0,
                AxisId.QUANTITY: 500.0,
                AxisId.WARRANTY: 22.0,
            },
        ),
    ),
    "fleet_tyres_replacement": (
        Bid(
            seller_id="northwind",
            values={
                AxisId.PRICE: 92.0,
                AxisId.DELIVERY: 5.0,
                AxisId.QUANTITY: 320.0,
                AxisId.WARRANTY: 30.0,
            },
        ),
        Bid(
            seller_id="meridian",
            values={
                AxisId.PRICE: 118.0,
                AxisId.DELIVERY: 21.0,
                AxisId.QUANTITY: 320.0,
                AxisId.WARRANTY: 66.0,
            },
        ),
    ),
}
