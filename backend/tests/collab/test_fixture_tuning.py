# Built with Spec4 AI - https://spec4.ai
"""The fixtures are tuned for genuine non-comparability. Proved arithmetically.

This is the test the phase's risk assessment asks for, and its whole purpose is
*when* it runs. The demo's teaching point is that the buyer faces a real
trade-off rather than a dominance check, and that is a property of the authored
constraint sets -- not of any model. If a scenario is badly tuned, every
downstream phase produces bids that look comparable and the lesson quietly
collapses.

Left to Phase 3 that would surface as a vague quality complaint after real
model calls had been spent discovering it. Here it is a failing assertion over
hand-authored representative bids, before a single provider request exists.

The representative bids are fixture data, never run data: no visitor sees them
and no model is given them.
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.app.collab.scenarios import (
    PRIORITY_WEIGHTINGS,
    REPRESENTATIVE_BIDS,
    SCENARIOS,
    SEALED_CONSTRAINTS_BY_KEY,
    WEIGHT_TOTAL,
    AxisId,
)
from backend.app.collab.scoring import rank_bids, winner

SCENARIO_IDS = [s.id for s in SCENARIOS]


def _scenario(scenario_id: str) -> Any:
    return next(s for s in SCENARIOS if s.id == scenario_id)


class TestEveryScenarioHasAWinnerFlippingPair:
    @pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
    def test_at_least_one_pair_of_weightings_ranks_a_different_seller_first(
        self, scenario_id: str
    ) -> None:
        """The headline tuning property, per scenario."""
        scenario = _scenario(scenario_id)
        bids = REPRESENTATIVE_BIDS[scenario_id]

        winners = {w.id: winner(scenario, w, bids) for w in PRIORITY_WEIGHTINGS}

        assert len(set(winners.values())) > 1, (
            f"{scenario_id} is not tuned: every weighting picks "
            f"{next(iter(set(winners.values())))}, so the buyer's judgment is a "
            "dominance check rather than a trade-off"
        )

    @pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
    def test_the_cheapest_bid_wins_on_price_and_loses_on_warranty(
        self, scenario_id: str
    ) -> None:
        """Names *which* pair flips, so a scenario cannot pass by flipping for
        some incidental reason while price and warranty both favour one seller.
        """
        scenario = _scenario(scenario_id)
        bids = REPRESENTATIVE_BIDS[scenario_id]

        by_price = winner(scenario, _weighting("lowest_price"), bids)
        by_warranty = winner(scenario, _weighting("longest_warranty"), bids)

        assert by_price != by_warranty


def _weighting(weighting_id: str) -> Any:
    return next(w for w in PRIORITY_WEIGHTINGS if w.id == weighting_id)


class TestTheTwoSellersAreOrthogonal:
    @pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
    def test_each_seller_is_better_on_at_least_one_axis(self, scenario_id: str) -> None:
        """Neither bid dominates: if one were better on all four terms there
        would be nothing to weigh."""
        scenario = _scenario(scenario_id)
        first, second = REPRESENTATIVE_BIDS[scenario_id]
        weighting = _weighting("balanced")

        ranked = rank_bids(scenario, weighting, [first, second])
        scores = {s.seller_id: s for s in ranked}
        a, b = scores[first.seller_id], scores[second.seller_id]

        paired = list(zip(a.axes, b.axes, strict=True))
        a_wins = {x.axis for x, y in paired if x.normalised > y.normalised}
        b_wins = {y.axis for x, y in paired if y.normalised > x.normalised}

        assert a_wins, f"{first.seller_id} is better on no axis in {scenario_id}"
        assert b_wins, f"{second.seller_id} is better on no axis in {scenario_id}"

    @pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
    def test_the_bids_differ_on_at_least_two_of_the_four_terms(
        self, scenario_id: str
    ) -> None:
        """The capability's own differentiation check, applied to the fixtures
        the live bids are supposed to resemble."""
        first, second = REPRESENTATIVE_BIDS[scenario_id]

        differing = [
            axis for axis in AxisId if first.values[axis] != second.values[axis]
        ]
        assert len(differing) >= 2

    @pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
    def test_one_seller_cannot_cover_the_full_requirement(
        self, scenario_id: str
    ) -> None:
        """Partial fulfilment has to be a live trade-off in at least one
        scenario per seller pairing, or the quantity axis is decorative."""
        scenario = _scenario(scenario_id)
        quantity_axis = scenario.axis(AxisId.QUANTITY)
        capacities = [
            SEALED_CONSTRAINTS_BY_KEY[(scenario_id, seller)].capacity_ceiling
            for seller in ("northwind", "meridian")
        ]

        # At least one seller can cover the requirement, so the buyer has a
        # real option; the scenario is still valid if both can, as the tyres
        # one is -- there the trade-off is price against warranty instead.
        assert max(capacities) >= quantity_axis.best


class TestTheBidsRespectTheSealedConstraints:
    @pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
    def test_no_representative_bid_breaks_its_own_seller_s_floor_or_ceiling(
        self, scenario_id: str
    ) -> None:
        """A representative bid that violated its own constraints would prove
        nothing about a run where the agent must respect them."""
        for bid in REPRESENTATIVE_BIDS[scenario_id]:
            sealed = SEALED_CONSTRAINTS_BY_KEY[(scenario_id, bid.seller_id)]

            assert bid.values[AxisId.PRICE] >= sealed.cost_floor
            assert bid.values[AxisId.QUANTITY] <= sealed.capacity_ceiling
            assert bid.values[AxisId.DELIVERY] >= sealed.delivery_capability_days
            assert bid.values[AxisId.WARRANTY] <= sealed.warranty_liability_limit_months


class TestTheWeightingsThemselves:
    @pytest.mark.parametrize("weighting", PRIORITY_WEIGHTINGS, ids=lambda w: w.id)
    def test_every_preset_covers_all_four_axes_and_sums_to_one_hundred(
        self, weighting: Any
    ) -> None:
        assert set(weighting.weights) == set(AxisId)
        assert sum(weighting.weights.values()) == WEIGHT_TOTAL

    def test_the_presets_are_distinct(self) -> None:
        """Two presets with identical weights could never flip a winner
        between them, so they would be one preset wearing two labels."""
        vectors = {tuple(sorted(w.weights.items())) for w in PRIORITY_WEIGHTINGS}
        assert len(vectors) == len(PRIORITY_WEIGHTINGS)


class TestNoSealedValueIsInferableFromPublishedBounds:
    @pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
    def test_no_sealed_value_equals_a_published_axis_bound(
        self, scenario_id: str
    ) -> None:
        """A sealed constraint that exactly equals a bound the RFQ publishes is
        partially inferable, which weakens the claim that it is sealed. Caught
        as a real collision while tuning these fixtures -- one seller's warranty
        limit was the scenario's own declared maximum.
        """
        scenario = _scenario(scenario_id)
        bounds = {axis.best for axis in scenario.axes} | {
            axis.worst for axis in scenario.axes
        }

        for seller in ("northwind", "meridian"):
            sealed = SEALED_CONSTRAINTS_BY_KEY[(scenario_id, seller)]
            values = {
                sealed.cost_floor,
                float(sealed.capacity_ceiling),
                float(sealed.delivery_capability_days),
                float(sealed.warranty_liability_limit_months),
            }
            assert not (values & bounds), (
                f"{seller}'s sealed value(s) {values & bounds} equal a published "
                f"axis bound of {scenario_id}"
            )
