# Built with Spec4 AI - https://spec4.ai
"""How a run fails, and what it says about itself afterwards.

Two suites in one file because they are the same question from two sides: what
happens when something breaks, and whether an operator can tell.

The degradation cases are the ones a visitor is most likely to hit on a free
tier — a slow seller, an exhausted allowance, a buyer stage that will not
produce conforming output — and each has a *specific* required behaviour rather
than a generic "handle the error":

- a timed-out seller preserves the other track and the run continues, labelled;
- a buyer stage failing halts the run, keeps the partial record, and **refunds
  the reserved-but-unspent units**;
- a cap-exhausted request is refused before stage 1 with nothing persisted.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

from backend.app.collab import explanations, opacity, sequencer, service
from backend.app.collab.rfq import compose_rfq
from backend.app.collab.runtime import RunBudget
from backend.app.collab.scenarios import SCENARIOS_BY_ID, WEIGHTINGS_BY_ID
from backend.app.collab.schemas import Award, Bid, CounterOffer, CounterOfferSet
from backend.app.collab.telemetry import RunTelemetry
from backend.app.services.agent_runtime import AgentLaneError, StepResult

SCENARIO = SCENARIOS_BY_ID["refurbished_laptops_school"]
WEIGHTING = WEIGHTINGS_BY_ID["balanced"]
SELLERS = sorted(opacity.SELLER_IDS_SET)

BIDS = {
    SELLERS[0]: (418.0, 240.0, 25.0, 30.0),
    SELLERS[1]: (372.0, 180.0, 14.0, 12.0),
}


def _bid(seller: str, stage: str) -> Bid:
    price, quantity, days, warranty = BIDS[seller]
    return Bid(
        seller_id=seller,
        stage=stage,
        unit_price=price,
        quantity=quantity,
        delivery_days=days,
        warranty_months=warranty,
        notes=f"{seller} offer",
    )


def _wrap(output: Any) -> StepResult[Any]:
    return StepResult(output=output, model="fake/model")


class Driver:
    """A run whose failures can be dialled in per stage."""

    def __init__(
        self,
        *,
        timeout_seller: str | None = None,
        fail_counters: bool = False,
        fail_award: bool = False,
    ) -> None:
        self.timeout_seller = timeout_seller
        self.fail_counters = fail_counters
        self.fail_award = fail_award

    async def opening(self, context, *, budget, nudge=""):
        budget.spend()
        if context.agent_id == self.timeout_seller:
            # Longer than the branch timeout, so the fan-out reports it as
            # timed out rather than failed -- a distinction the UI keeps.
            await asyncio.sleep(5)
        return _wrap(_bid(context.agent_id, "opening_bids"))

    async def final(self, context, *, counter, budget):
        budget.spend()
        return _wrap(_bid(context.agent_id, "final_bids"))

    async def counters(self, *, request, weighting, bids, budget):
        budget.spend()
        if self.fail_counters:
            raise AgentLaneError("collab_counter_offers", "every model failed")
        return _wrap(
            CounterOfferSet(
                offers=[
                    CounterOffer(
                        seller_id=bid.seller_id,
                        targeted_term="price",
                        ask="Improve it.",
                        justification="Price is weighted.",
                    )
                    for bid in bids
                ]
            )
        )

    async def award(self, *, request, weighting, final_bids, budget, inconsistency=""):
        budget.spend()
        if self.fail_award:
            raise AgentLaneError("collab_award", "every model failed")
        return _wrap(
            Award(
                winner_id=final_bids[0].seller_id,
                rationale="Best on price.",
                priority_references=["price"],
            )
        )

    async def explanation(self, **kwargs: Any) -> Any:
        budget = kwargs.get("budget")
        if isinstance(budget, RunBudget):
            budget.spend()
        raise RuntimeError("no provider in tests")


def drive(driver: Driver, *, timeout: float = 0.2):
    """Run the sequencer with this driver, with a short branch timeout.

    The timeout is applied by wrapping `fan_out` rather than by patching
    `BRANCH_TIMEOUT_SECONDS`: that constant is a *def-time default* on
    `runtime.fan_out`, so rebinding the module attribute changes nothing. This
    way the real `asyncio.timeout` still runs -- the test exercises the timeout
    path rather than a mapping of a hand-thrown `TimeoutError`.
    """
    from backend.app.collab import runtime

    async def _short_fan_out(first, second, **_kwargs):
        return await runtime.fan_out(first, second, timeout=timeout)

    request = compose_rfq(SCENARIO, WEIGHTING)
    telemetry = RunTelemetry(
        run_id="run-1", scenario_id=SCENARIO.id, weighting_id=WEIGHTING.id
    )
    events: list[sequencer.StageEvent] = []
    outcome: sequencer.NegotiationOutcome | None = None

    async def _go() -> None:
        nonlocal outcome
        with (
            patch.object(sequencer.agents, "seller_opening_bid", driver.opening),
            patch.object(sequencer.agents, "seller_final_bid", driver.final),
            patch.object(sequencer.agents, "buyer_counter_offers", driver.counters),
            patch.object(sequencer.agents, "buyer_award", driver.award),
            patch.object(explanations, "run_agent_step", driver.explanation),
            patch.object(sequencer, "fan_out", _short_fan_out),
        ):
            async for item in sequencer.run_negotiation(
                run_id="run-1",
                scenario=SCENARIO,
                weighting=WEIGHTING,
                request=request,
                telemetry=telemetry,
            ):
                if isinstance(item, sequencer.NegotiationOutcome):
                    outcome = item
                else:
                    events.append(item)

    asyncio.run(_go())
    assert outcome is not None
    return events, outcome, telemetry


class TestASellerTimingOut:
    def test_the_other_track_is_preserved_and_the_run_continues(self) -> None:
        _, outcome, telemetry = drive(Driver(timeout_seller=SELLERS[0]))

        assert len(outcome.opening_bids) == 1
        assert outcome.opening_bids[0].seller_id == SELLERS[1]
        assert outcome.award is not None
        assert telemetry.outcome != "no_result"

    def test_the_degradation_is_labelled_rather_than_silent(self) -> None:
        events, outcome, telemetry = drive(Driver(timeout_seller=SELLERS[0]))

        assert outcome.degradation.get(SELLERS[0]) == "timed_out"
        assert telemetry.degradation.get(SELLERS[0]) == "timed_out"
        # And it is distinguishable from an outright failure, which suggests a
        # different next step to a visitor.
        assert "timed_out" in telemetry.degradation[SELLERS[0]]
        assert events

    def test_a_degraded_run_spends_fewer_than_six_negotiation_calls(self) -> None:
        """The count is what the run *did*, not what a clean run would do."""
        _, outcome, _ = drive(Driver(timeout_seller=SELLERS[0]))

        assert outcome.budget.negotiation_stage_calls < 6


class TestABuyerStageFailing:
    def test_the_counter_offer_stage_halts_with_the_partial_record(self) -> None:
        events, outcome, _ = drive(Driver(fail_counters=True))

        assert len(outcome.opening_bids) == 2, "the bids are kept"
        assert outcome.award is None
        error = next(e for e in events if e.kind == "error")
        assert error.payload["code"] == "counter_offers_failed"
        assert "remain" in error.payload["message"]

    def test_the_award_stage_halts_with_every_bid_still_shown(self) -> None:
        events, outcome, _ = drive(Driver(fail_award=True))

        assert len(outcome.final_bids) == 2
        assert outcome.award is None
        error = next(e for e in events if e.kind == "error")
        assert error.payload["code"] == "award_failed"

    def test_no_explanation_runs_when_the_award_never_happened(self) -> None:
        """The reveal is the sealed material. A halted run has nothing to
        unseal, and the gate is what makes that structural."""
        _, outcome, _ = drive(Driver(fail_award=True))

        assert outcome.reveal is None
        assert outcome.sensitivity is None


class TestTheRefundPathOnFailure:
    def test_reserved_but_unspent_units_are_released(self) -> None:
        released: list[str] = []

        async def _refund(_session: object, hold_key: str) -> object:
            released.append(hold_key)
            return object()

        class _Session:
            added: list[object] = []

            async def execute(self, *_a: object, **_k: object) -> object:
                class _R:
                    def scalar_one_or_none(self) -> object:
                        return None

                return _R()

            def add(self, obj: object) -> None:
                self.added.append(obj)

            async def commit(self) -> None:
                pass

        with patch.object(service.allowance_holds, "refund", _refund):
            done = asyncio.run(
                service.abandon_run(_Session(), "run-1", reason="award_failed")  # type: ignore[arg-type]
            )

        assert done is True
        assert released == ["run-1"]


class TestACapExhaustedRequest:
    def test_it_is_refused_before_stage_one_with_nothing_persisted(self) -> None:
        from backend.app.services import shared

        class _Session:
            def __init__(self) -> None:
                self.added: list[object] = []
                self.commits = 0

            async def execute(self, *_a: object, **_k: object) -> object:
                class _R:
                    def scalar_one_or_none(self) -> object:
                        return None

                return _R()

            def add(self, obj: object) -> None:
                self.added.append(obj)

            async def commit(self) -> None:
                self.commits += 1

        async def _gate(*_a: object, **_k: object) -> None:
            raise shared.ServiceUnavailableError("no room this hour")

        session = _Session()

        async def _collect() -> list[Any]:
            return [
                event
                async for event in service.stream_run(
                    session,  # type: ignore[arg-type]
                    run_id="run-1",
                    scenario_id=SCENARIO.id,
                    weighting_id=WEIGHTING.id,
                )
            ]

        with patch.object(shared, "reserve_capability", _gate):
            events = asyncio.run(_collect())

        assert len(events) == 1
        assert events[0].payload["outcome"] == "usage_limit_reached"
        assert session.added == []
        assert session.commits == 0


class TestTheTelemetry:
    def test_a_run_summary_carries_every_field_the_stack_spec_names(self) -> None:
        _, _, telemetry = drive(Driver())
        event = telemetry.as_event()

        for field in (
            "negotiation_stage_calls",
            "total_model_calls",
            "stage_latency_ms",
            "degradation",
            "seller_to_seller_messages",
            "explanation_fallbacks",
            "explanation_violations",
        ):
            assert field in event, f"{field} missing from the run summary"

    def test_per_stage_latencies_cover_every_stage_that_ran(self) -> None:
        _, _, telemetry = drive(Driver())

        assert {"rfq", "opening_bids", "counter_offers", "final_bids", "award"} <= set(
            telemetry.stage_latency_ms
        )

    def test_the_seller_to_seller_count_is_measured_and_zero(self) -> None:
        _, outcome, telemetry = drive(Driver())

        assert telemetry.seller_to_seller_messages == 0
        assert telemetry.seller_to_seller_messages == opacity.seller_to_seller_count(
            outcome.bus
        )

    def test_the_explanation_fallback_rate_is_recorded_per_panel(self) -> None:
        """A panel occasionally falling back is the design working; every panel
        falling back means the validators reject everything the models produce,
        which is a different problem. The rate is what tells them apart."""
        _, _, telemetry = drive(Driver())

        assert telemetry.explanation_fallbacks == {
            "reveal": True,
            "sensitivity": True,
        }

    def test_a_stage_count_other_than_six_is_alerted_on(self) -> None:
        """The number the pattern claim rests on. A run that quietly made five
        calls would still look fine in every other field.

        Captured through `structlog.testing`, not `caplog`: this project
        configures structlog to render its own output, so the stdlib capture
        sees nothing.
        """
        from structlog.testing import capture_logs

        with capture_logs() as logs:
            drive(Driver(timeout_seller=SELLERS[0]))

        alerts = [
            entry
            for entry in logs
            if entry.get("event") == "collab_negotiation_call_count_unexpected"
        ]
        assert alerts, "a run that did not make six calls was not alerted on"
        assert alerts[0]["expected"] == 6
        assert alerts[0]["actual"] != 6

    def test_the_summary_carries_no_bid_figures_or_sealed_values(self) -> None:
        """A leak into an operator's log is still a leak; it has only changed
        audience."""
        _, _, telemetry = drive(Driver())
        rendered = repr(telemetry.as_event())

        for seller in SELLERS:
            corpus = opacity.constraint_corpus(seller, SCENARIO.id)
            assert not opacity.contains_sealed_value(rendered, corpus)
        assert "418" not in rendered and "372" not in rendered


class TestSentryReportsTheAbortPaths:
    def test_the_leak_path_reports_explicitly(self) -> None:
        """Sentry's auto-integrations capture what *raises* through a request.
        These aborts are caught deliberately and turned into stream events, so
        an operator would otherwise never hear about them."""
        import inspect

        source = inspect.getsource(service.stream_run)
        assert "report_abort" in source

    def test_reporting_no_ops_without_a_dsn(self) -> None:
        """It is called from inside exception handlers, where a raise would
        turn a graceful degradation into a 500."""
        from backend.app.core.observability import report_abort

        report_abort("collab_test", run_id="run-1")
