# Built with Spec4 AI - https://spec4.ai
"""The six-stage negotiation, with every model call substituted.

The claims this file exists to hold down, in the order the phase's risk
assessment ranks them:

1. **Call-count drift.** Retries, schema repairs and the differentiation nudge
   each tempt an implementation that *adds* a call, quietly breaking the
   six-call claim the whole example rests on. The stage counter and the spend
   counter are asserted separately, because they are two different claims.
2. **A cancelled sibling.** An exception inside `asyncio.gather` without
   `return_exceptions=True` cancels the other seller and destroys a bid that
   was about to succeed. Asserted by failing one branch and checking the other
   survived.
3. **The sequencer turning into a coordinator.** The six calls belong to the
   three agents; the driver makes none of its own. Asserted structurally.

No provider is reached: `agents.*` is patched at its point of use in the
sequencer, which is also the seam that lets a test drive a *specific* model
behaviour -- a seller that fails, an award that contradicts its own scoring, a
buyer that leaks.

**The `_no_live_explanations` fixture is autouse and deliberately so.** When
Phase 5 added the two post-award calls, every test in this file started making
real provider requests and still passed -- the same silent cost v5 found in its
dispatch suite. Patching `explain_run` to raise makes a forgotten stub a loud
failure instead of a bill. A test that wants the explanation stage overrides it
explicitly.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from backend.app.collab import opacity, runtime, sequencer
from backend.app.collab.rfq import compose_rfq
from backend.app.collab.runtime import RunBudget
from backend.app.collab.scenarios import (
    SCENARIOS_BY_ID,
    WEIGHTINGS_BY_ID,
    PrivateConstraint,
)
from backend.app.collab.schemas import (
    Award,
    Bid,
    CounterOffer,
    CounterOfferSet,
    NegotiationStage,
    PriorityScore,
)
from backend.app.collab.telemetry import RunTelemetry
from backend.app.services.agent_runtime import AgentLaneError, StepResult


@pytest.fixture(autouse=True)
def _no_live_explanations():
    """Refuse to let the post-award calls reach a provider.

    Autouse: the cost of forgetting is real money and a slow suite, and the
    failure is otherwise invisible because a failed explanation degrades to a
    template rather than raising.
    """

    async def _refuse(**_kwargs: object) -> object:
        raise AssertionError("a post-award explanation reached a provider")

    # Patched at the *provider* boundary rather than at `explain_run`, so the
    # explanation stage still runs and degrades to its deterministic template
    # exactly as it would in production. Raising from `explain_run` itself
    # would break the run instead of exercising the fallback.
    with patch.object(sequencer.explanations, "run_agent_step", _refuse):
        yield


SCENARIO = SCENARIOS_BY_ID["refurbished_laptops_school"]
WEIGHTING = WEIGHTINGS_BY_ID["balanced"]
SELLERS = sorted(opacity.SELLER_IDS_SET)


def _bid(seller_id: str, *, price: float, days: float, qty: float, warranty: float):
    return Bid(
        seller_id=seller_id,
        unit_price=price,
        quantity=qty,
        delivery_days=days,
        warranty_months=warranty,
        notes=f"{seller_id} offer",
    )


#: Two deliberately different bids, so the differentiation check passes.
OPENING = {
    SELLERS[0]: _bid(SELLERS[0], price=418, days=25, qty=240, warranty=30),
    SELLERS[1]: _bid(SELLERS[1], price=372, days=14, qty=180, warranty=12),
}


def _award(winner: str, *, scores: dict[str, float] | None = None) -> Award:
    scores = scores or {SELLERS[0]: 80.0, SELLERS[1]: 40.0}
    return Award(
        winner_id=winner,
        per_priority_scoring=[
            PriorityScore(seller_id=seller, priority=axis, score=score)
            for seller, score in scores.items()
            for axis in ("price", "delivery", "quantity", "warranty")
        ],
        rationale="It scored best against the stated priorities.",
        priority_references=["price", "warranty"],
        runner_up_note="The other bid was cheaper.",
    )


class _Recorder:
    """Substitutes the four agent calls and records what was asked of them."""

    def __init__(
        self,
        *,
        fail: set[str] | None = None,
        award: Award | None = None,
        counters: CounterOfferSet | None = None,
        opening: dict[str, Bid] | None = None,
    ) -> None:
        self.fail = fail or set()
        self.award_value = award or _award(SELLERS[0])
        self.counters = counters
        self.opening = opening or OPENING
        self.calls: list[str] = []
        self.contexts: list[Any] = []
        self.award_prompts: list[str] = []

    async def opening_bid(self, context, *, budget, nudge=""):
        self.calls.append(f"opening:{context.agent_id}{':nudged' if nudge else ''}")
        self.contexts.append(context)
        budget.spend()
        if context.agent_id in self.fail:
            raise AgentLaneError("every model failed")
        return StepResult(
            output=self.opening[context.agent_id].model_copy(
                update={"stage": NegotiationStage.OPENING_BIDS.value}
            ),
            model="fake/model",
        )

    async def final_bid(self, context, *, counter, budget):
        self.calls.append(f"final:{context.agent_id}")
        budget.spend()
        if f"final:{context.agent_id}" in self.fail:
            raise AgentLaneError("every model failed")
        return StepResult(
            output=self.opening[context.agent_id].model_copy(
                update={"stage": NegotiationStage.FINAL_BIDS.value}
            ),
            model="fake/model",
        )

    async def counter_offers(self, *, request, weighting, bids, budget):
        self.calls.append("counters")
        budget.spend()
        if "counters" in self.fail:
            raise AgentLaneError("every model failed")
        produced = self.counters or CounterOfferSet(
            offers=[
                CounterOffer(
                    seller_id=bid.seller_id,
                    targeted_term="price",
                    ask="Improve the price.",
                    justification="Price is weighted highly.",
                )
                for bid in bids
            ]
        )
        return StepResult(output=produced, model="fake/model")

    async def award(self, *, request, weighting, final_bids, budget, inconsistency=""):
        self.calls.append(f"award{':retry' if inconsistency else ''}")
        self.award_prompts.append(inconsistency)
        budget.spend()
        if "award" in self.fail:
            raise AgentLaneError("every model failed")
        return StepResult(output=self.award_value, model="fake/model")


def _drive(recorder: _Recorder, *, budget: RunBudget | None = None):
    """Run the sequencer to completion with the recorder substituted."""
    request = compose_rfq(SCENARIO, WEIGHTING)
    telemetry = RunTelemetry(
        run_id="run-1", scenario_id=SCENARIO.id, weighting_id=WEIGHTING.id
    )
    events: list[sequencer.StageEvent] = []
    outcome: sequencer.NegotiationOutcome | None = None

    async def _go():
        nonlocal outcome
        with (
            patch.object(sequencer.agents, "seller_opening_bid", recorder.opening_bid),
            patch.object(sequencer.agents, "seller_final_bid", recorder.final_bid),
            patch.object(
                sequencer.agents, "buyer_counter_offers", recorder.counter_offers
            ),
            patch.object(sequencer.agents, "buyer_award", recorder.award),
        ):
            async for item in sequencer.run_negotiation(
                run_id="run-1",
                scenario=SCENARIO,
                weighting=WEIGHTING,
                request=request,
                telemetry=telemetry,
                budget=budget,
            ):
                if isinstance(item, sequencer.NegotiationOutcome):
                    outcome = item
                else:
                    events.append(item)

    asyncio.run(_go())
    assert outcome is not None
    return events, outcome, telemetry


class TestTheCallCount:
    def test_a_clean_run_makes_exactly_six_negotiation_calls(self) -> None:
        recorder = _Recorder()
        _, outcome, telemetry = _drive(recorder)

        assert outcome.budget.negotiation_stage_calls == 6
        assert telemetry.negotiation_stage_calls == 6
        # Two opening, one counter, two final, one award.
        assert len(recorder.calls) == 6

    def test_exactly_three_agents_participate(self) -> None:
        recorder = _Recorder()
        _, outcome, _ = _drive(recorder)

        parties = {env.sender for env in outcome.bus.log()} | {
            env.recipient for env in outcome.bus.log()
        }
        assert parties == {opacity.BUYER_ID, *SELLERS}
        assert len(parties) == 3

    def test_the_negotiation_itself_spends_six_of_the_reserved_budget(self) -> None:
        """The two counters are different claims: six is the pattern, eight is
        the reservation, and the remaining two are the post-award explanations.

        The explanation stage is stubbed out here, so `used` shows what the
        *negotiation* cost -- which is the number the pattern claim rests on.
        """
        recorder = _Recorder()
        _, outcome, _ = _drive(recorder)

        assert outcome.budget.negotiation_stage_calls == 6
        assert outcome.budget.used == 6
        assert outcome.budget.ceiling == runtime.MAX_PROVIDER_REQUESTS


class TestTheStageOrder:
    def test_stages_arrive_in_the_specified_order(self) -> None:
        recorder = _Recorder()
        events, _, _ = _drive(recorder)

        order = [event.stage for event in events]
        assert order[0] == NegotiationStage.RFQ.value
        # The award is the last *negotiation* stage. The post-award explanations
        # follow it (stubbed out here), and the message log comes last because
        # it is the record of everything that was routed.
        assert order[-1] == "message_log"
        assert NegotiationStage.AWARD.value in order
        assert order.index(NegotiationStage.AWARD.value) > order.index(
            NegotiationStage.FINAL_BIDS.value
        )
        # Counter delivery sits between the counters and the final bids.
        assert order.index(NegotiationStage.COUNTER_OFFERS.value) < order.index(
            NegotiationStage.COUNTER_DELIVERY.value
        )
        assert order.index(NegotiationStage.COUNTER_DELIVERY.value) < order.index(
            NegotiationStage.FINAL_BIDS.value
        )

    def test_the_agents_are_called_in_the_specified_order(self) -> None:
        recorder = _Recorder()
        _drive(recorder)

        assert recorder.calls[:2] == [f"opening:{s}" for s in SELLERS]
        assert recorder.calls[2] == "counters"
        assert recorder.calls[3:5] == [f"final:{s}" for s in SELLERS]
        assert recorder.calls[5] == "award"

    def test_stage_one_and_stage_four_consume_zero_calls(self) -> None:
        """A template and a routing table are not inference."""
        recorder = _Recorder()
        events, _, _ = _drive(recorder)

        rfq = next(e for e in events if e.stage == NegotiationStage.RFQ.value)
        routing = next(
            e for e in events if e.stage == NegotiationStage.COUNTER_DELIVERY.value
        )
        assert rfq.payload["model_calls"] == 0
        assert routing.payload["model_calls"] == 0

    def test_the_first_event_declares_the_run_s_cost_up_front(self) -> None:
        recorder = _Recorder()
        events, _, _ = _drive(recorder)

        budget = events[0].payload["declared_budget"]
        assert budget == {"total": 8, "negotiation": 6, "explanation": 2}


class TestTheMessageLog:
    def test_no_message_has_a_seller_at_both_ends(self) -> None:
        recorder = _Recorder()
        _, outcome, telemetry = _drive(recorder)

        assert opacity.seller_to_seller_count(outcome.bus) == 0
        assert telemetry.seller_to_seller_messages == 0

    def test_the_log_event_is_the_server_s_record_not_a_client_tally(self) -> None:
        """The visitor checks the opacity claim against this, so it has to come
        from the same `bus.log()` that `persist_run` writes."""
        recorder = _Recorder()
        events, outcome, _ = _drive(recorder)

        log_event = next(e for e in events if e.kind == "message_log")
        rows = log_event.payload["messages"]

        assert len(rows) == len(outcome.bus.log())
        assert [row["sequence"] for row in rows] == sorted(
            row["sequence"] for row in rows
        )
        assert log_event.payload["seller_to_seller_count"] == 0
        # Every row names exactly one sender and one recipient, and never two
        # sellers -- which is the claim the table is there to let someone check.
        assert not [
            row
            for row in rows
            if row["sender"] in SELLERS and row["recipient"] in SELLERS
        ]

    def test_the_rfq_reaches_both_sellers_as_two_addressed_messages(self) -> None:
        recorder = _Recorder()
        _, outcome, _ = _drive(recorder)

        rfq_messages = [
            env for env in outcome.bus.log() if env.stage == NegotiationStage.RFQ.value
        ]
        assert sorted(env.recipient for env in rfq_messages) == SELLERS

    def test_each_seller_s_context_holds_only_its_own_mail(self) -> None:
        recorder = _Recorder()
        _drive(recorder)

        for context in recorder.contexts:
            assert all(env.recipient == context.agent_id for env in context.inbox)
            assert isinstance(context.own_constraints, PrivateConstraint)
            assert context.own_constraints.seller_id == context.agent_id


class TestOneSellerFailing:
    def test_the_surviving_track_keeps_its_bid(self) -> None:
        """Without `return_exceptions=True` the sibling is cancelled and the
        bid that was about to succeed is destroyed."""
        recorder = _Recorder(fail={SELLERS[0]})
        _, outcome, _ = _drive(recorder)

        assert len(outcome.opening_bids) == 1
        assert outcome.opening_bids[0].seller_id == SELLERS[1]

    def test_the_run_continues_in_degraded_mode_and_still_awards(self) -> None:
        recorder = _Recorder(fail={SELLERS[0]})
        events, outcome, _ = _drive(recorder)

        assert outcome.award is not None
        assert SELLERS[0] in outcome.degradation
        assert any(e.kind == "award" for e in events)

    def test_a_degraded_run_makes_fewer_than_six_calls_and_says_so(self) -> None:
        recorder = _Recorder(fail={SELLERS[0]})
        _, outcome, _ = _drive(recorder)

        # One opening bid lost, one final bid never asked for.
        assert outcome.budget.negotiation_stage_calls == 4

    def test_both_sellers_failing_stops_before_the_counter_offers(self) -> None:
        recorder = _Recorder(fail=set(SELLERS))
        events, outcome, _ = _drive(recorder)

        assert outcome.opening_bids == []
        assert "counters" not in recorder.calls
        assert any(e.payload.get("code") == "all_sellers_failed" for e in events)


class TestTheDifferentiationRetry:
    def test_it_replaces_rather_than_adds_a_negotiation_call(self) -> None:
        """The whole risk this phase names: a nudge that *adds* a call breaks
        the six-call claim."""
        identical = {
            seller: _bid(seller, price=400, days=20, qty=200, warranty=24)
            for seller in SELLERS
        }
        recorder = _Recorder(opening=identical)
        _, outcome, _ = _drive(recorder)

        assert f"opening:{SELLERS[0]}:nudged" in recorder.calls
        # Seven provider requests, still six negotiation calls.
        assert outcome.budget.used == 7
        assert outcome.budget.negotiation_stage_calls == 6

    def test_it_does_not_fire_when_the_bids_already_differ(self) -> None:
        recorder = _Recorder()
        _, outcome, _ = _drive(recorder)

        assert not any(":nudged" in call for call in recorder.calls)
        assert outcome.budget.used == 6

    def test_it_is_recorded_in_the_degradation_flags(self) -> None:
        identical = {
            seller: _bid(seller, price=400, days=20, qty=200, warranty=24)
            for seller in SELLERS
        }
        _, outcome, _ = _drive(_Recorder(opening=identical))

        assert "differentiation_retry" in outcome.degradation


class TestTheAwardReconciliation:
    def test_an_award_contradicting_its_own_scoring_is_regenerated_once(self) -> None:
        # Scores favour SELLERS[0]; the award declares SELLERS[1].
        contradictory = _award(SELLERS[1], scores={SELLERS[0]: 90.0, SELLERS[1]: 10.0})
        recorder = _Recorder(award=contradictory)
        _, outcome, _ = _drive(recorder)

        assert "award:retry" in recorder.calls
        assert recorder.award_prompts[-1]

    def test_a_persistent_mismatch_is_flagged_rather_than_corrected(self) -> None:
        """Substituting the implied winner would replace one unverified claim
        with another and hide that anything went wrong."""
        contradictory = _award(SELLERS[1], scores={SELLERS[0]: 90.0, SELLERS[1]: 10.0})
        recorder = _Recorder(award=contradictory)
        events, outcome, _ = _drive(recorder)

        assert outcome.award_reconciled is False
        assert outcome.reconciliation_note
        # The model's own declared winner is what is shown.
        assert outcome.award is not None
        assert outcome.award.winner_id == SELLERS[1]

        award_event = next(e for e in events if e.kind == "award")
        assert award_event.payload["reconciled"] is False

    def test_a_consistent_award_is_not_regenerated(self) -> None:
        recorder = _Recorder(award=_award(SELLERS[0]))
        _, outcome, _ = _drive(recorder)

        assert "award:retry" not in recorder.calls
        assert outcome.award_reconciled is True


class TestTheLeakLintAbortsTheRun:
    def test_a_counter_offer_carrying_a_rival_constraint_is_never_delivered(
        self,
    ) -> None:
        rival = opacity.constraints_for(SELLERS[1], SCENARIO.id)
        assert isinstance(rival, PrivateConstraint)

        leaking = CounterOfferSet(
            offers=[
                CounterOffer(
                    seller_id=SELLERS[0],
                    targeted_term="price",
                    ask="Match it.",
                    justification=(f"Your competitor can go to {rival.cost_floor:g}."),
                ),
                CounterOffer(
                    seller_id=SELLERS[1],
                    targeted_term="delivery",
                    ask="Sooner please.",
                    justification="Delivery is weighted highly.",
                ),
            ]
        )
        recorder = _Recorder(counters=leaking)

        with pytest.raises(opacity.ConstraintLeakError):
            _drive(recorder)

        # Aborted before the final bids were ever requested.
        assert not any(call.startswith("final:") for call in recorder.calls)


class TestTheSequencerIsADriverNotACoordinator:
    def test_it_reaches_no_provider(self) -> None:
        """Parsed from the imports rather than grepped: this module's docstring
        talks about models on purpose."""
        tree = ast.parse(inspect.getsource(sequencer))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)

        for module in imported:
            assert not module.startswith(
                ("pydantic_ai", "litellm", "httpx", "openai")
            ), f"{module} reaches a provider"

    def test_no_model_slug_appears_anywhere_in_the_package(self) -> None:
        """Choosing which family serves a capability is the registry's job."""
        package = Path(sequencer.__file__).parent
        markers = ("openrouter/", "groq/", ":free", "gpt-oss", "llama-3")

        for path in package.rglob("*.py"):
            text = path.read_text().lower()
            for marker in markers:
                assert marker not in text, f"{path.name} names a model slug"

    def test_run_agent_step_offers_no_tools_parameter(self) -> None:
        """Arithmetic as much as privacy: a tool-using step takes an
        unpredictable number of provider requests."""
        from backend.app.collab.runtime import run_agent_step

        assert "tools" not in inspect.signature(run_agent_step).parameters
