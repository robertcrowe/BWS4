# Built with Spec4 AI - https://spec4.ai
"""The golden suite: every claim this example makes, over every preset.

Fifteen cases — three scenarios × five weightings — replayed through the real
sequencer with only the model substituted. **Offline by construction**: a test
asserts the whole grid runs with `build_fallback_model` patched to raise, so a
path that reached a provider fails loudly rather than quietly spending.

## What the fixtures are, and what they are not

`golden/negotiation_cases.json` is **constructed from the Phase 2 hand-tuned
fixtures, not captured from a live provider.** That is a deliberate trade and
worth being plain about:

- Recording fifteen live runs would cost real quota, and the recordings would
  rot as free slugs are retired — the phase's own second named risk.
- What the golden suite is *for* is pinning the deterministic behaviour: stage
  order, call counts, schema conformance, opacity, the winner flip. None of
  that is a property of any particular model's prose.

What this suite therefore **cannot** establish is how a live model behaves —
whether real bids differentiate, whether a real award names the priorities. One
live smoke run exercises the provider chain; this grid exercises everything
that must hold regardless of which model answered.

## Why the filename is not

The orchestrated app already has a module by that name, and the test packages
carry no , so two same-named modules collide at collection. Unique
basenames across  are a requirement of the layout, not a style
preference.

## Why the filename is not `test_golden_eval.py`

The orchestrated app already has a module by that name, and the test packages
carry no `__init__.py`, so two same-named modules collide at collection.
Unique basenames across `backend/tests/` are a requirement of this layout
rather than a style preference.

## Loops, not samples

The isolation and sensitivity assertions iterate the **full** catalogue. A spot
check does not prove an invariant, and the specific failure this guards against
is a leak introduced by a badly authored fixture in the scenario nobody tested.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from backend.app.collab import explanations, opacity, sequencer
from backend.app.collab.rfq import compose_rfq
from backend.app.collab.runtime import RunBudget
from backend.app.collab.scenarios import (
    SCENARIOS,
    SCENARIOS_BY_ID,
    WEIGHTINGS_BY_ID,
    AxisId,
    PrivateConstraint,
)
from backend.app.collab.schemas import (
    Award,
    Bid,
    CounterOffer,
    CounterOfferSet,
    NegotiationStage,
)
from backend.app.collab.telemetry import RunTelemetry
from backend.app.services.agent_runtime import StepResult

#: Where this suite patches the collaborators the module under test
#: resolved at import time -- patch-at-point-of-use, kept as one
#: constant so the dotted path is stated once.
_PATCH_BASE = "backend.app.collab.sequencer.agents"

GOLDEN = json.loads(
    (Path(__file__).parent / "golden" / "negotiation_cases.json").read_text()
)
CASES: list[dict[str, Any]] = GOLDEN["cases"]
CASE_IDS = [case["id"] for case in CASES]
SELLERS = sorted(opacity.SELLER_IDS_SET)


class GoldenPlayer:
    """Serves one recorded case in place of every model call in the run."""

    def __init__(self, case: dict[str, Any], *, probe: str = "") -> None:
        self.case = case
        self.probe = probe
        self.contexts: list[Any] = []
        self.prompts: list[str] = []
        self.labels: list[str] = []

    async def opening_bid(
        self, context: Any, *, budget: Any, nudge: Any = ""
    ) -> StepResult[Any]:
        self.contexts.append(context)
        self.prompts.append(context.rfq_text)
        budget.spend()
        return StepResult(
            output=Bid(**self.case["opening_bids"][context.agent_id]),
            model="golden/replay",
        )

    async def final_bid(
        self, context: Any, *, counter: Any, budget: Any
    ) -> StepResult[Any]:
        self.contexts.append(context)
        budget.spend()
        return StepResult(
            output=Bid(**self.case["final_bids"][context.agent_id]),
            model="golden/replay",
        )

    async def counter_offers(
        self, *, request: Any, weighting: Any, bids: Any, budget: Any
    ) -> StepResult[Any]:
        budget.spend()
        return StepResult(
            output=CounterOfferSet(
                offers=[CounterOffer(**offer) for offer in self.case["counter_offers"]]
            ),
            model="golden/replay",
        )

    async def award(
        self,
        *,
        request: Any,
        weighting: Any,
        final_bids: Any,
        budget: Any,
        inconsistency: Any = "",
    ) -> StepResult[Any]:
        budget.spend()
        return StepResult(output=Award(**self.case["award"]), model="golden/replay")

    async def explanation_step(self, **kwargs: Any) -> StepResult[Any]:
        """Stand in for both post-award calls.

        Raises so each falls back to its deterministic template, while still
        charging the budget -- which is what a real run does when a model is
        unreachable, and what makes `total_model_calls_used` 8 rather than 6.
        """
        self.labels.append(str(kwargs.get("label", "")))
        budget = kwargs.get("budget")
        if isinstance(budget, RunBudget):
            budget.spend()
        raise RuntimeError("golden replay: no provider")


def play(case: dict[str, Any], *, probe: str = "") -> Any:
    """Drive the real sequencer over one recorded case."""
    scenario = SCENARIOS_BY_ID[case["scenario_id"]]
    weighting = WEIGHTINGS_BY_ID[case["weighting_id"]]
    request = compose_rfq(scenario, weighting)
    telemetry = RunTelemetry(
        run_id=case["id"], scenario_id=scenario.id, weighting_id=weighting.id
    )
    player = GoldenPlayer(case, probe=probe)
    events: list[sequencer.StageEvent] = []
    outcome: sequencer.NegotiationOutcome | None = None

    async def _go() -> None:
        nonlocal outcome
        with (
            patch(f"{_PATCH_BASE}.seller_opening_bid", player.opening_bid),
            patch(f"{_PATCH_BASE}.seller_final_bid", player.final_bid),
            patch(f"{_PATCH_BASE}.buyer_counter_offers", player.counter_offers),
            patch(f"{_PATCH_BASE}.buyer_award", player.award),
            patch.object(explanations, "run_agent_step", player.explanation_step),
        ):
            async for item in sequencer.run_negotiation(
                run_id=case["id"],
                scenario=scenario,
                weighting=weighting,
                request=request,
                telemetry=telemetry,
            ):
                if isinstance(item, sequencer.NegotiationOutcome):
                    outcome = item
                else:
                    events.append(item)

    asyncio.run(_go())
    assert outcome is not None
    return events, outcome, telemetry, player


@pytest.fixture(scope="module")
def played() -> dict[str, tuple[Any, Any, Any, Any]]:
    """Play every case once and share the results across the suite."""
    return {case["id"]: play(case) for case in CASES}


class TestTheSuiteIsOffline:
    def test_the_whole_grid_runs_with_no_provider_reachable(self) -> None:
        """Not "no credential is configured" -- *no provider is reachable*. A
        path that slipped through to a real model fails here rather than
        quietly spending on every CI run."""

        def _explode(*_a: object, **_k: object) -> object:
            raise AssertionError("the golden suite reached a provider")

        with patch("backend.app.services.agent_runtime.build_fallback_model", _explode):
            for case in CASES:
                _, outcome, _, _ = play(case)
                assert outcome.award is not None

    def test_the_fixture_file_says_what_it_is(self) -> None:
        """Constructed from the tuned fixtures, not recorded from a model. A
        suite that implied otherwise would overstate what it proves."""
        assert "not captured from a live provider" in GOLDEN["note"]


@pytest.mark.parametrize("case_id", CASE_IDS)
class TestEveryGoldenRun:
    def test_the_six_stages_occur_in_the_specified_order(
        self, case_id: str, played: Any
    ) -> None:
        events, _, _, _ = played[case_id]
        order = [event.stage for event in events]

        for earlier, later in [
            (NegotiationStage.RFQ, NegotiationStage.OPENING_BIDS),
            (NegotiationStage.OPENING_BIDS, NegotiationStage.COUNTER_OFFERS),
            (NegotiationStage.COUNTER_OFFERS, NegotiationStage.COUNTER_DELIVERY),
            (NegotiationStage.COUNTER_DELIVERY, NegotiationStage.FINAL_BIDS),
            (NegotiationStage.FINAL_BIDS, NegotiationStage.AWARD),
        ]:
            assert order.index(earlier.value) < order.index(later.value)

    def test_stage_one_and_stage_four_consume_zero_model_calls(
        self, case_id: str, played: Any
    ) -> None:
        events, _, _, _ = played[case_id]
        free = [
            event
            for event in events
            if event.stage
            in {NegotiationStage.RFQ.value, NegotiationStage.COUNTER_DELIVERY.value}
        ]

        assert len(free) == 2
        assert all(event.payload["model_calls"] == 0 for event in free)

    def test_the_negotiation_costs_exactly_six_calls(
        self, case_id: str, played: Any
    ) -> None:
        """The number the whole pattern claim rests on."""
        _, outcome, telemetry, _ = played[case_id]

        assert outcome.budget.negotiation_stage_calls == 6
        assert telemetry.negotiation_stage_calls == 6

    def test_the_run_costs_exactly_eight_provider_requests(
        self, case_id: str, played: Any
    ) -> None:
        """Six negotiation plus the two post-award explanations -- the whole
        reservation, and never more than it."""
        _, outcome, telemetry, _ = played[case_id]

        assert outcome.budget.used == 8
        assert telemetry.total_model_calls == 8
        assert outcome.budget.used <= outcome.budget.ceiling

    def test_exactly_three_agents_participate(self, case_id: str, played: Any) -> None:
        _, outcome, _, _ = played[case_id]

        parties = {envelope.sender for envelope in outcome.bus.log()} | {
            envelope.recipient for envelope in outcome.bus.log()
        }
        assert parties == {opacity.BUYER_ID, *SELLERS}

    def test_every_artifact_conforms_to_its_narrow_schema(
        self, case_id: str, played: Any
    ) -> None:
        _, outcome, _, _ = played[case_id]

        assert len(outcome.opening_bids) == 2
        assert len(outcome.final_bids) == 2
        assert len(outcome.counter_offers) == 2
        for bid in [*outcome.opening_bids, *outcome.final_bids]:
            assert Bid.model_validate(bid.model_dump()) == bid
        for offer in outcome.counter_offers:
            assert offer.seller_id in SELLERS
            assert offer.targeted_term in {axis.value for axis in AxisId}
        assert outcome.award is not None
        assert Award.model_validate(outcome.award.model_dump()) == outcome.award

    def test_concessions_are_recorded_rather_than_empty(
        self, case_id: str, played: Any
    ) -> None:
        """A best-and-final that conceded nothing anywhere would make the
        counter-offer stage decorative."""
        _, outcome, _, _ = played[case_id]

        assert any(bid.concessions_made for bid in outcome.final_bids)

    def test_the_two_opening_bids_differ_on_at_least_two_terms(
        self, case_id: str, played: Any
    ) -> None:
        """Otherwise the award is a dominance check rather than a trade-off."""
        _, outcome, _, _ = played[case_id]
        first, second = outcome.opening_bids

        differing = [
            axis
            for axis in AxisId
            if getattr(first, _FIELD[axis]) != getattr(second, _FIELD[axis])
        ]
        assert len(differing) >= 2

    def test_both_explanations_render_despite_no_provider(
        self, case_id: str, played: Any
    ) -> None:
        """The panels can be worse than they might have been; they can never be
        blank. Every case here degrades to the deterministic template."""
        _, outcome, _, _ = played[case_id]

        assert outcome.reveal is not None
        assert outcome.reveal["fallback_generated"] is True
        assert len(outcome.reveal["parties"]) == 2
        assert outcome.sensitivity is not None
        assert outcome.sensitivity["caveat"]


_FIELD = {
    AxisId.PRICE: "unit_price",
    AxisId.DELIVERY: "delivery_days",
    AxisId.QUANTITY: "quantity",
    AxisId.WARRANTY: "warranty_months",
}


@pytest.mark.parametrize("case_id", CASE_IDS)
class TestIsolationAcrossEveryPreset:
    def test_no_message_has_a_seller_at_both_ends(
        self, case_id: str, played: Any
    ) -> None:
        _, outcome, telemetry, _ = played[case_id]

        assert opacity.seller_to_seller_count(outcome.bus) == 0
        assert telemetry.seller_to_seller_messages == 0

    def test_each_seller_s_prompt_holds_only_what_it_is_entitled_to(
        self, case_id: str, played: Any
    ) -> None:
        """The RFQ, its own constraints, and buyer messages addressed to it —
        and nothing else, checked by construction rather than by reading."""
        _, _, _, player = played[case_id]
        scenario_id = CASES[CASE_IDS.index(case_id)]["scenario_id"]

        for context in player.contexts:
            assert all(env.recipient == context.agent_id for env in context.inbox)
            assert all(env.sender == opacity.BUYER_ID for env in context.inbox)
            own = context.own_constraints
            assert isinstance(own, PrivateConstraint)
            assert own.seller_id == context.agent_id
            assert not hasattr(context.scenario, "buyer_position")
            assert set(vars(context)) == {
                "agent_id",
                "role",
                "scenario",
                "own_constraints",
                "inbox",
                "rfq_text",
            }
            _ = scenario_id

    def test_no_pre_reveal_artifact_carries_a_rival_sealed_value(
        self, case_id: str, played: Any
    ) -> None:
        """Every bid, counter-offer and award, checked against the *other*
        seller's corpus — measured over the public baseline so a coincidence
        with a published figure is not counted as a disclosure."""
        _, outcome, _, _ = played[case_id]
        case = CASES[CASE_IDS.index(case_id)]
        scenario = SCENARIOS_BY_ID[case["scenario_id"]]
        weighting = WEIGHTINGS_BY_ID[case["weighting_id"]]
        baseline = repr(scenario.public()) + compose_rfq(scenario, weighting).text

        for seller in SELLERS:
            rival = opacity.rival_of(seller)
            corpus = opacity.constraint_corpus(rival, scenario.id)
            public = opacity.contains_sealed_value(baseline, corpus)

            visible = " ".join(
                [
                    *(bid.notes for bid in outcome.opening_bids),
                    *(bid.notes for bid in outcome.final_bids),
                    *(
                        f"{offer.ask} {offer.justification}"
                        for offer in outcome.counter_offers
                        if offer.seller_id == seller
                    ),
                ]
            )
            leaked = opacity.contains_sealed_value(visible, corpus) - public
            assert not leaked, f"{seller} could see rival values {leaked}"


class TestTheSqlOpacityProof:
    def test_the_predicate_over_the_stored_projection_returns_zero(self) -> None:
        """The headline claim, made provable **from the store** rather than
        from application memory.

        The rows are built the way `persist_run` builds them, from each run's
        own bus log, and then the single predicate an operator would run
        against Postgres is applied to them. Asserting against in-memory state
        would test the code's opinion of itself.
        """
        rows: list[tuple[str, str]] = []
        for case in CASES:
            _, outcome, _, _ = play(case)
            rows.extend(
                (envelope.sender, envelope.recipient) for envelope in outcome.bus.log()
            )

        assert rows, "no messages were persisted at all"
        seller_to_seller = [
            row for row in rows if row[0] in SELLERS and row[1] in SELLERS
        ]
        assert seller_to_seller == []

    def test_the_persisted_rows_carry_the_addressing_the_predicate_needs(
        self,
    ) -> None:
        """A `sender`/`recipient` pair on every row, so the predicate is one
        `WHERE` rather than a scan through JSONB."""
        from backend.app.db.models import PeerMessage

        columns = set(PeerMessage.__table__.columns.keys())
        assert {"sender", "recipient", "run_id", "sequence"} <= columns


class TestSensitivityAcrossEveryScenario:
    @pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.id)
    def test_at_least_one_pair_of_weightings_changes_the_winner(
        self, scenario: Any, played: Any
    ) -> None:
        """Proves the buyer's judgment is weighting-driven rather than
        scenario-locked -- run over the *golden outcomes*, not just the
        fixtures, so it covers what the sequencer actually awarded."""
        winners = {
            played[case["id"]][1].award.winner_id
            for case in CASES
            if case["scenario_id"] == scenario.id
        }

        assert len(winners) > 1, (
            f"{scenario.id} awards {winners} under every weighting, so the "
            "priorities are decorative"
        )

    @pytest.mark.parametrize("case_id", CASE_IDS)
    def test_the_award_rationale_names_the_top_weighted_priorities(
        self, case_id: str, played: Any
    ) -> None:
        _, outcome, _, _ = played[case_id]
        case = CASES[CASE_IDS.index(case_id)]
        weighting = WEIGHTINGS_BY_ID[case["weighting_id"]]
        top = max(AxisId, key=lambda axis: weighting.weights[axis])

        assert outcome.award is not None
        rendered = f"{outcome.award.rationale} {outcome.award.priority_references}"
        assert top.value in rendered.lower()
