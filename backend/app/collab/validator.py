# Built with Spec4 AI - https://spec4.ai
"""The post-stage checks. Pure functions, no provider, no database, no clock.

Everything the sequencer decides *about* a model's output lives here, so it can
be tested exhaustively without a run and so the sequencer stays a driver rather
than a judge.

Three checks, and they differ in what they are allowed to do about a failure:

- **`differentiation`** may cost a *replacement* call. Two bids that differ on
  fewer than two terms make the buyer's award a dominance check and the demo
  pointless, so it is worth one re-issue with a constraint-salience nudge.
- **`repair_counter_offers`** costs nothing. Cardinality and addressing are
  repairable deterministically -- trimming an extra offer or filling a missing
  one is arithmetic, and re-prompting for it would spend a provider request to
  do what this does for free.
- **`reconcile_award`** may cost one regeneration, and if that fails it
  **flags rather than hides**. An award whose declared winner its own scoring
  does not support is the "plausible-sounding lie" the capability names; the
  honest outcome is a visible banner, not a silently corrected winner. Nothing
  here overwrites the model's declared winner.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.app.collab.scenarios import AxisId, PriorityWeighting
from backend.app.collab.schemas import Award, Bid, CounterOffer, CounterOfferSet

#: How many of the four axes two opening bids must differ on for the award to
#: be a genuine trade-off rather than a dominance check.
MIN_DIFFERING_TERMS = 2

#: Appended to a re-issued opening bid when the two came back too alike. It
#: names no rival and carries no rival value -- it only tells a seller to lean
#: harder on its own position.
DIFFERENTIATION_NUDGE = (
    "Your first quote sat close to the middle on every term. Lean into where "
    "your own sealed position actually gives you an advantage and be honest "
    "about where it does not, so your offer is distinctive rather than "
    "average. Do not speculate about any other supplier."
)


def normalise_priority(name: str) -> AxisId | None:
    """Map a model's priority label onto one of the four axes, or None.

    The award prompt names the four keys exactly, and models still write "unit
    price" and "delivery lead time" -- observed on a live run, where every
    award failed reconciliation and paid for a regeneration it did not need.
    Fixing the prompt is the primary remedy; this is the belt.

    Deliberately conservative: a label matches only when it *contains* an axis
    name as a word. Fuzzy matching would let "price sensitivity of delivery"
    resolve arbitrarily, and on a check whose failure mode is a visible banner,
    a wrong match is worse than no match.

    Args:
        name: The label the model used.

    Returns:
        The axis, or None when nothing matches unambiguously.
    """
    tokens = {token.strip(" -_") for token in name.lower().split()}
    matches = [axis for axis in AxisId if axis.value in tokens]
    return matches[0] if len(matches) == 1 else None


def _axis_values(bid: Bid) -> dict[AxisId, float]:
    """Project a bid onto the four scored axes."""
    return {
        AxisId.PRICE: bid.unit_price,
        AxisId.DELIVERY: bid.delivery_days,
        AxisId.QUANTITY: bid.quantity,
        AxisId.WARRANTY: bid.warranty_months,
    }


def differing_terms(first: Bid, second: Bid) -> set[AxisId]:
    """Return the axes on which two bids actually differ.

    Args:
        first: One bid.
        second: The other.

    Returns:
        The axes whose values are not equal.
    """
    left, right = _axis_values(first), _axis_values(second)
    return {axis for axis in AxisId if left[axis] != right[axis]}


def needs_differentiation(bids: list[Bid]) -> bool:
    """Whether the opening bids are too alike to make the award interesting.

    Args:
        bids: The opening bids received. Fewer than two means a seller failed,
            and a degraded run has nothing to differentiate.

    Returns:
        True when both bids arrived and differ on fewer than two terms.
    """
    if len(bids) < 2:
        return False
    return len(differing_terms(bids[0], bids[1])) < MIN_DIFFERING_TERMS


@dataclass(frozen=True)
class CounterRepair:
    """The outcome of repairing a counter-offer set.

    Attributes:
        offers: One counter per expected seller, in the order given.
        repairs: What had to be fixed, for the degradation record. Empty when
            the model's output was already well formed.
    """

    offers: list[CounterOffer]
    repairs: list[str]


def repair_counter_offers(
    produced: CounterOfferSet, *, expected_sellers: list[str]
) -> CounterRepair:
    """Trim, address and fill counter-offers deterministically. Costs no call.

    The model is asked for one counter per seller and mostly gives it. When it
    does not -- three offers, two addressed to the same seller, one missing --
    the fix is arithmetic and a re-prompt would spend a provider request on
    something this does for free. That is why the output schema is permissive:
    a bound in the type would make PydanticAI re-prompt before this code ever
    ran.

    Args:
        produced: What the buyer returned.
        expected_sellers: The sellers a counter must exist for, in order.

    Returns:
        Exactly one counter per expected seller, plus what was repaired.
    """
    by_seller: dict[str, CounterOffer] = {}
    extras = 0
    for offer in produced.offers:
        if offer.seller_id in expected_sellers and offer.seller_id not in by_seller:
            by_seller[offer.seller_id] = offer
        else:
            extras += 1

    repairs: list[str] = []
    if extras:
        repairs.append(f"dropped {extras} misaddressed or duplicate counter-offer(s)")

    # Anything the model did produce but misaddressed is reused in order rather
    # than discarded: its content is still the buyer's reasoning, and inventing
    # replacement prose here would be this module writing negotiation text,
    # which is not its job.
    spare = [
        offer
        for offer in produced.offers
        if offer is not by_seller.get(offer.seller_id)
    ]
    offers: list[CounterOffer] = []
    for seller_id in expected_sellers:
        existing = by_seller.get(seller_id)
        if existing is not None:
            offers.append(existing.model_copy(update={"seller_id": seller_id}))
            continue
        if spare:
            recycled = spare.pop(0)
            repairs.append(f"re-addressed a counter-offer to {seller_id}")
            offers.append(recycled.model_copy(update={"seller_id": seller_id}))
            continue
        repairs.append(f"no counter-offer was produced for {seller_id}")
        offers.append(
            CounterOffer(
                seller_id=seller_id,
                targeted_term=AxisId.PRICE.value,
                ask="Please improve your offer where your position allows.",
                justification=(
                    "The buyer's counter-offer for this supplier did not come "
                    "back in a usable form, so a neutral request was sent "
                    "instead."
                ),
            )
        )

    return CounterRepair(offers=offers, repairs=repairs)


@dataclass(frozen=True)
class Reconciliation:
    """Whether an award follows from its own per-priority scoring.

    Attributes:
        consistent: True when the declared winner leads on the model's own
            weighted scores and every weighted priority was addressed.
        problem: What did not reconcile, phrased for the regeneration prompt
            and for the visitor-facing flag. Empty when consistent.
        implied_winner: Who the model's own scores actually favour, or None
            when they cannot be read at all.
        missing_priorities: Weighted priorities the scoring never mentioned.
    """

    consistent: bool
    problem: str = ""
    implied_winner: str | None = None
    missing_priorities: tuple[str, ...] = ()


def reconcile_award(
    award: Award, *, weighting: PriorityWeighting, seller_ids: list[str]
) -> Reconciliation:
    """Check an award against the scoring the same response emitted.

    **This never changes the winner.** The model made a decision and the
    visitor is entitled to see it; what they are also entitled to see is that
    it did not follow from the working. Silently substituting the implied
    winner would replace one unverified claim with another and hide that
    anything went wrong.

    Args:
        award: The award to check.
        weighting: The visitor's stated priorities, supplying the weights.
        seller_ids: The sellers that were actually in the running.

    Returns:
        Whether it reconciles, and what did not.
    """
    if award.winner_id not in seller_ids:
        return Reconciliation(
            consistent=False,
            problem=(
                f"The declared winner {award.winner_id!r} is not one of the "
                f"suppliers that bid ({', '.join(seller_ids)})."
            ),
        )

    weighted = {axis.value for axis in AxisId if weighting.weights[axis] > 0}
    scored: set[str] = set()
    for score in award.per_priority_scoring:
        axis = normalise_priority(score.priority)
        if axis is not None:
            scored.add(axis.value)
    missing = tuple(sorted(weighted - scored))

    totals: dict[str, float] = {seller: 0.0 for seller in seller_ids}
    for score in award.per_priority_scoring:
        if score.seller_id not in totals:
            continue
        axis = normalise_priority(score.priority)
        if axis is None:
            continue
        totals[score.seller_id] += score.score * weighting.weights[axis]

    if not any(totals.values()):
        return Reconciliation(
            consistent=False,
            problem=(
                "The award carried no usable per-priority scoring, so the "
                "declared winner cannot be checked against its own working."
            ),
            missing_priorities=missing,
        )

    implied = max(totals, key=lambda seller: (totals[seller], seller))

    if implied != award.winner_id:
        return Reconciliation(
            consistent=False,
            problem=(
                f"You declared {award.winner_id} the winner, but your own "
                f"per-priority scores weighted by the stated priorities favour "
                f"{implied}."
            ),
            implied_winner=implied,
            missing_priorities=missing,
        )

    if missing:
        return Reconciliation(
            consistent=False,
            problem=(
                "Your scoring did not address these weighted priorities: "
                f"{', '.join(missing)}."
            ),
            implied_winner=implied,
            missing_priorities=missing,
        )

    return Reconciliation(consistent=True, implied_winner=implied)
