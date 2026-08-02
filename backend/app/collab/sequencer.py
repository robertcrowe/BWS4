# Built with Spec4 AI - https://spec4.ai
"""The six-stage driver. It sequences the negotiation; it does not conduct one.

**This module makes no model call of its own and holds no opinion about the
negotiation.** It reserves budget, composes the RFQ, advances six stages in a
fixed order, fans out the two concurrent ones, routes every message through the
opacity-policed bus, runs the post-stage checks, streams each stage, and keeps
the reveal sealed until after the award.

That restriction is the pattern, not a style preference. The negotiating
judgment -- which bid is better, where to press, who wins -- lives inside the
**buyer agent**, a peer with its own private position. The moment this file
starts reasoning over both sellers' state and deciding, the example has stopped
being peer collaboration and become orchestrated subagents with extra steps:
there would be a coordinator holding the union of everyone's private
information, which is precisely the thing the tier above orchestration exists
to avoid. A test asserts this module reaches no provider.

## The six stages

1. **RFQ** -- composed deterministically in Phase 2, delivered to both sellers
   as two separately addressed messages. **Zero model calls.**
2. **Opening bids** -- both sellers concurrently. Two calls.
3. **Counter-offers** -- the buyer, once, producing both counters. One call.
4. **Counter delivery** -- bus routing only. **Zero model calls**, logged as
   routing so the stage is visible without pretending it cost something.
5. **Best-and-final bids** -- both sellers concurrently. Two calls.
6. **Award** -- the buyer. One call.

Six model calls, and the two free stages are free because a template and a
routing table are not inference.

## Counters, and why there are two of them

`negotiation_stage_calls` is the pattern's claim (six). `budget.used` is the
spend, including repairs, retries and the differentiation nudge, bounded by the
reservation. A repair *replaces* the call it repairs in the first counter while
still costing a real request in the second. Collapsing them would make one of
the two claims unverifiable.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import structlog

from backend.app.collab import agents, explanations, opacity, validator
from backend.app.collab.counterfactual import Counterfactual, compute_counterfactual
from backend.app.collab.protocol import Artifact, DataPart, Message, Role, TextPart
from backend.app.collab.rfq import QuotationRequest
from backend.app.collab.runtime import (
    EXPLANATION_CALLS,
    NEGOTIATION_CALLS,
    BranchOutcome,
    FanOut,
    RunBudget,
    RunBudgetExceededError,
    fan_out,
)
from backend.app.collab.scenarios import PriorityWeighting, Scenario
from backend.app.collab.schemas import (
    Award,
    Bid,
    CounterOffer,
    NegotiationStage,
)
from backend.app.collab.scoring import to_scored_bid
from backend.app.collab.telemetry import RunTelemetry
from backend.app.services.agent_runtime import AgentLaneError
from backend.app.services.message_bus import PeerMessageBus, PeerMessageEnvelope

logger = structlog.get_logger()


@dataclass
class StageEvent:
    """One thing the client is told, as it happens.

    Attributes:
        stage: Which stage produced it.
        kind: What it is -- `quotation_request`, `bid`, `counter_offers`,
            `routing`, `award`, `degraded` or `error`.
        payload: JSON-serialisable body.
    """

    stage: str
    kind: str
    payload: dict[str, Any]


@dataclass
class NegotiationOutcome:
    """Everything a completed run produced, for persistence.

    Attributes:
        run_id: The run's identifier.
        request: The composed RFQ.
        opening_bids: The bids received at stage 2.
        counter_offers: The counters delivered at stage 4.
        final_bids: The bids received at stage 5.
        award: The award, or None when stage 6 could not complete.
        award_reconciled: False when the award did not follow from its own
            scoring. Surfaced, never corrected.
        reconciliation_note: What did not reconcile, when it did not.
        degradation: Per-agent degradation reasons.
        reveal: The post-award unsealing payload, or None when the round did
            not conclude. **Never populated before the award.**
        sensitivity: The priority-sensitivity projection, or None.
        stage_timings: Per-stage wall-clock in milliseconds.
        budget: The run's counters.
        bus: The run's message bus, whose log is persisted as `peer_messages`.
    """

    run_id: str
    request: QuotationRequest
    opening_bids: list[Bid] = field(default_factory=list)
    counter_offers: list[CounterOffer] = field(default_factory=list)
    final_bids: list[Bid] = field(default_factory=list)
    award: Award | None = None
    award_reconciled: bool = True
    reconciliation_note: str = ""
    degradation: dict[str, str] = field(default_factory=dict)
    reveal: dict[str, Any] | None = None
    sensitivity: dict[str, Any] | None = None
    stage_timings: dict[str, int] = field(default_factory=dict)
    budget: RunBudget = field(default_factory=RunBudget)
    bus: PeerMessageBus = field(default_factory=PeerMessageBus)


def _text_message(text: str) -> Message:
    """Wrap prose in an A2A message."""
    return Message(
        message_id=f"msg-{uuid.uuid4().hex[:12]}",
        role=Role.AGENT,
        parts=[TextPart(text=text, media_type="text/plain")],
    )


def _artifact(name: str, data: dict[str, Any]) -> Artifact:
    """Wrap a produced work item in an A2A artifact."""
    return Artifact(
        artifact_id=f"art-{uuid.uuid4().hex[:12]}",
        name=name,
        parts=[DataPart(data=data, media_type="application/json")],
    )


def _log_row(envelope: PeerMessageEnvelope) -> dict[str, Any]:
    """Project one envelope to the row the message log renders.

    Carries the work item whole rather than a summary of it: the log is where a
    visitor goes to check what was actually routed, and a summary is the server
    telling them what to conclude.

    Args:
        envelope: The delivered envelope.

    Returns:
        Its row: sequence, timestamp, addressing, stage, and the A2A work item.
    """
    return {
        "sequence": envelope.sequence,
        "timestamp": envelope.timestamp.isoformat(),
        "sender": envelope.sender,
        "recipient": envelope.recipient,
        "stage": envelope.stage,
        "work_item": envelope.work_item.model_dump(by_alias=True, mode="json"),
    }


class _Clock:
    """Wall-clock for one stage, in milliseconds."""

    def __init__(self) -> None:
        self.started = time.monotonic()

    def elapsed_ms(self) -> int:
        """Return milliseconds since this clock was created."""
        return int((time.monotonic() - self.started) * 1000)


async def run_negotiation(
    *,
    run_id: str,
    scenario: Scenario,
    weighting: PriorityWeighting,
    request: QuotationRequest,
    telemetry: RunTelemetry,
    budget: RunBudget | None = None,
) -> AsyncGenerator[StageEvent | NegotiationOutcome, None]:
    """Drive the six stages, yielding one event per stage as it completes.

    Yields `StageEvent`s throughout and a final `NegotiationOutcome` last, so a
    caller can stream the first and persist the second without the sequencer
    knowing about either SSE or the database.

    Args:
        run_id: The run's identifier.
        scenario: The scenario being negotiated.
        weighting: The visitor's stated priorities.
        request: The RFQ, already composed deterministically.
        telemetry: The run's accumulating summary.
        budget: The run's counters. A fresh one when omitted.

    Yields:
        `StageEvent` per stage, then exactly one `NegotiationOutcome`.
    """
    budget = budget or RunBudget()
    bus = PeerMessageBus()
    outcome = NegotiationOutcome(run_id=run_id, request=request, budget=budget, bus=bus)
    sellers = list(opacity.SELLER_IDS_SET)
    sellers.sort()

    # ---- Stage 1: the RFQ. Zero model calls. -----------------------------
    clock = _Clock()
    for seller_id in sellers:
        opacity.deliver(
            bus,
            PeerMessageEnvelope(
                sender=opacity.BUYER_ID,
                recipient=seller_id,
                stage=NegotiationStage.RFQ.value,
                work_item=_text_message(request.text),
            ),
            scenario_id=scenario.id,
            run_id=run_id,
            public_text=request.text,
        )
    outcome.stage_timings[NegotiationStage.RFQ.value] = clock.elapsed_ms()
    yield StageEvent(
        stage=NegotiationStage.RFQ.value,
        kind="quotation_request",
        payload={
            "request": request.as_payload(),
            "model_calls": 0,
            "declared_budget": {
                "total": NEGOTIATION_CALLS + EXPLANATION_CALLS,
                "negotiation": NEGOTIATION_CALLS,
                "explanation": EXPLANATION_CALLS,
            },
            "sellers": sellers,
        },
    )

    # ---- Stage 2: both opening bids, concurrently. Two calls. ------------
    #
    # Streamed **as each branch settles**, not collected and emitted together.
    # That difference is the demonstration: two suppliers bidding at the same
    # time looks identical to two bidding in turn if the client only learns
    # about both at the end. A live run confirmed the batched version put both
    # events on the wire in the same second.
    clock = _Clock()
    opening = FanOut()
    async for item in _streamed_bid_round(
        sellers=sellers,
        scenario=scenario,
        request=request,
        bus=bus,
        budget=budget,
        run_id=run_id,
        counters=None,
        collect=opening,
    ):
        yield item

    for branch in opening.branches:
        if branch.ok and isinstance(branch.value, Bid):
            outcome.opening_bids.append(branch.value)
        else:
            outcome.degradation[branch.label] = branch.status
            telemetry.record_degradation(branch.label, branch.status)

    # The differentiation post-check may re-issue one bid. It REPLACES that
    # seller's call: the stage counter does not move, the budget does. Because
    # the original was already streamed, the replacement is emitted as its own
    # event carrying `reissued` -- the visitor sees that a bid was re-requested
    # rather than watching one silently change underneath them.
    if validator.needs_differentiation(outcome.opening_bids):
        replaced = await _reissue_for_differentiation(
            outcome=outcome,
            scenario=scenario,
            request=request,
            bus=bus,
            budget=budget,
            run_id=run_id,
        )
        if replaced:
            outcome.degradation["differentiation_retry"] = replaced
            yield StageEvent(
                stage=NegotiationStage.OPENING_BIDS.value,
                kind="bid",
                payload={**outcome.opening_bids[0].model_dump(), "reissued": True},
            )

    # Published to the bus after the round rather than inside a branch: a leak
    # detected here must abort the *run*, and inside a `gather` branch it would
    # be caught by `return_exceptions=True` and demoted to one failed column.
    for bid in outcome.opening_bids:
        _publish_bid(
            bus,
            bid,
            scenario_id=scenario.id,
            run_id=run_id,
            public_text=request.text,
        )
    outcome.stage_timings[NegotiationStage.OPENING_BIDS.value] = clock.elapsed_ms()

    if not outcome.opening_bids:
        yield StageEvent(
            stage=NegotiationStage.OPENING_BIDS.value,
            kind="error",
            payload={
                "code": "all_sellers_failed",
                "message": (
                    "Neither supplier returned an opening bid, so there is "
                    "nothing to negotiate over. Nothing further was spent."
                ),
            },
        )
        yield outcome
        return

    # ---- Stage 3: the buyer's counter-offers. One call. ------------------
    clock = _Clock()
    bidding_sellers = [bid.seller_id for bid in outcome.opening_bids]
    try:
        counter_step = await agents.buyer_counter_offers(
            request=request,
            weighting=weighting,
            bids=outcome.opening_bids,
            budget=budget,
        )
        budget.count_stage_call()
    except (AgentLaneError, RunBudgetExceededError) as exc:
        yield StageEvent(
            stage=NegotiationStage.COUNTER_OFFERS.value,
            kind="error",
            payload={
                "code": "counter_offers_failed",
                "message": (
                    "The buyer could not produce counter-offers, so the round "
                    "stopped after the opening bids. Those remain below."
                ),
            },
        )
        logger.warning("collab_counter_offers_failed", run_id=run_id, error=str(exc))
        outcome.degradation["buyer"] = "counter_offers_failed"
        yield outcome
        return

    repair = validator.repair_counter_offers(
        counter_step.output, expected_sellers=bidding_sellers
    )
    outcome.counter_offers = repair.offers
    for note in repair.repairs:
        outcome.degradation.setdefault("counter_offer_repairs", note)

    yield StageEvent(
        stage=NegotiationStage.COUNTER_OFFERS.value,
        kind="counter_offers",
        payload={
            "offers": [offer.model_dump() for offer in repair.offers],
            "repairs": repair.repairs,
        },
    )
    outcome.stage_timings[NegotiationStage.COUNTER_OFFERS.value] = clock.elapsed_ms()

    # ---- Stage 4: deliver the counters. Zero model calls. ----------------
    # The leak lint runs inside `opacity.deliver`, so a counter carrying the
    # rival's sealed values aborts here and is never emitted to the client.
    clock = _Clock()
    for offer in repair.offers:
        opacity.deliver(
            bus,
            PeerMessageEnvelope(
                sender=opacity.BUYER_ID,
                recipient=offer.seller_id,
                stage=NegotiationStage.COUNTER_DELIVERY.value,
                work_item=_artifact("counter_offer", offer.model_dump()),
            ),
            scenario_id=scenario.id,
            run_id=run_id,
            public_text=request.text,
        )
    outcome.stage_timings[NegotiationStage.COUNTER_DELIVERY.value] = clock.elapsed_ms()
    yield StageEvent(
        stage=NegotiationStage.COUNTER_DELIVERY.value,
        kind="routing",
        payload={
            "delivered": [offer.seller_id for offer in repair.offers],
            "model_calls": 0,
        },
    )

    # ---- Stage 5: both best-and-final bids, concurrently. Two calls. -----
    clock = _Clock()
    by_seller = {offer.seller_id: offer for offer in repair.offers}
    final = FanOut()
    async for item in _streamed_bid_round(
        sellers=bidding_sellers,
        scenario=scenario,
        request=request,
        bus=bus,
        budget=budget,
        run_id=run_id,
        counters=by_seller,
        collect=final,
    ):
        yield item

    for branch in final.branches:
        if branch.ok and isinstance(branch.value, Bid):
            outcome.final_bids.append(branch.value)
            _publish_bid(
                bus,
                branch.value,
                scenario_id=scenario.id,
                run_id=run_id,
                public_text=request.text,
            )
        else:
            outcome.degradation[branch.label] = f"final_{branch.status}"
            telemetry.record_degradation(branch.label, f"final_{branch.status}")
            yield StageEvent(
                stage=NegotiationStage.FINAL_BIDS.value,
                kind="degraded",
                payload={"seller_id": branch.label, "status": branch.status},
            )
    outcome.stage_timings[NegotiationStage.FINAL_BIDS.value] = clock.elapsed_ms()

    if not outcome.final_bids:
        yield StageEvent(
            stage=NegotiationStage.FINAL_BIDS.value,
            kind="error",
            payload={
                "code": "no_final_bids",
                "message": (
                    "Neither supplier returned a best-and-final bid, so no "
                    "award could be made. The opening bids remain below."
                ),
            },
        )
        yield outcome
        return

    # ---- Stage 6: the award. One call. -----------------------------------
    clock = _Clock()
    async for event in _award_stage(
        outcome=outcome,
        weighting=weighting,
        request=request,
        budget=budget,
        run_id=run_id,
    ):
        yield event
    outcome.stage_timings[NegotiationStage.AWARD.value] = clock.elapsed_ms()

    # ---- The two post-award explanations. Calls 7 and 8 of the reserved 8. ---
    #
    # Gated on the award being present, and the gate is *here* rather than in
    # the client: the reveal payload is the sealed material, so emitting it
    # before the round completes would break the example's central claim. When
    # the award never arrived, `outcome.award` is None and this whole block is
    # skipped -- there is nothing to unseal for a round that did not conclude.
    if outcome.award is not None:
        clock = _Clock()
        async for event in _explanation_stage(
            outcome=outcome,
            scenario=scenario,
            weighting=weighting,
            budget=budget,
            run_id=run_id,
            telemetry=telemetry,
        ):
            yield event
        outcome.stage_timings["explanations"] = clock.elapsed_ms()

    telemetry.negotiation_stage_calls = budget.negotiation_stage_calls
    telemetry.total_model_calls = budget.used
    telemetry.seller_to_seller_messages = opacity.seller_to_seller_count(bus)
    for stage, ms in outcome.stage_timings.items():
        telemetry.record_stage(stage, ms)

    # The message log, emitted from the bus rather than tallied by the client.
    # The visitor uses it to check the app's headline claim for themselves, so
    # it has to be the server's record of what was routed -- a browser-side
    # tally would only prove what the browser was shown. This is the same
    # `bus.log()` that `persist_run` writes to `peer_messages`, so what is on
    # screen and what a `SELECT` returns cannot disagree.
    yield StageEvent(
        stage="message_log",
        kind="message_log",
        payload={
            "messages": [_log_row(envelope) for envelope in bus.log()],
            "seller_to_seller_count": opacity.seller_to_seller_count(bus),
        },
    )

    if budget.negotiation_stage_calls != NEGOTIATION_CALLS:
        # The number the pattern claim rests on, distinct from the total spend.
        logger.warning(
            "collab_negotiation_call_count_unexpected",
            run_id=run_id,
            expected=NEGOTIATION_CALLS,
            actual=budget.negotiation_stage_calls,
            total_provider_requests=budget.used,
        )

    yield outcome


async def _explanation_stage(
    *,
    outcome: NegotiationOutcome,
    scenario: Scenario,
    weighting: PriorityWeighting,
    budget: RunBudget,
    run_id: str,
    telemetry: RunTelemetry,
) -> AsyncGenerator[StageEvent, None]:
    """Run both post-award explanations and emit each as it lands.

    The two are dispatched together and streamed **independently**, so a slow
    sensitivity call does not hold up the reveal. Same single-writer queue the
    bid rounds use: two concurrent producers writing one response can interleave
    halfway through an event, and one drain point makes that impossible rather
    than unlikely.

    Neither panel can fail visibly. `explanations.py` renders a deterministic
    template before it calls anything and returns that when the model's answer
    does not survive checking, so what arrives here is always a complete panel
    -- badged `fallback` when it came from arithmetic rather than prose.

    Args:
        outcome: The completed run. Mutated in place with both payloads.
        scenario: The scenario negotiated.
        weighting: The visitor's stated priorities.
        budget: The run's counters.
        run_id: The run's identifier.
        telemetry: The run's summary, given the per-panel fallback outcome.

    Yields:
        A `reveal` event and a `sensitivity` event, in whichever order they
        complete.
    """
    counterfactual = compute_counterfactual(
        scenario, weighting, [to_scored_bid(bid) for bid in outcome.final_bids]
    )
    queue: asyncio.Queue[StageEvent | None] = asyncio.Queue()

    async def _drive() -> None:
        try:
            reveal, sensitivity = await explanations.explain_run(
                scenario=scenario,
                weighting=weighting,
                award=outcome.award,
                opening_bids=outcome.opening_bids,
                final_bids=outcome.final_bids,
                counterfactual=counterfactual,
                budget=budget,
                run_id=run_id,
            )
            if reveal is not None:
                telemetry.record_explanation(
                    "reveal",
                    fallback=reveal.fallback,
                    violations=reveal.violations,
                )
                outcome.reveal = {
                    **reveal.payload,
                    "fallback_generated": reveal.fallback,
                    "violations": reveal.violations,
                }
                await queue.put(
                    StageEvent(stage="reveal", kind="reveal", payload=outcome.reveal)
                )
            if sensitivity is not None:
                telemetry.record_explanation(
                    "sensitivity",
                    fallback=sensitivity.fallback,
                    violations=sensitivity.violations,
                )
                outcome.sensitivity = {
                    **sensitivity.payload,
                    "fallback_generated": sensitivity.fallback,
                    "violations": sensitivity.violations,
                    "computed": _counterfactual_payload(counterfactual),
                }
                await queue.put(
                    StageEvent(
                        stage="sensitivity",
                        kind="sensitivity",
                        payload=outcome.sensitivity,
                    )
                )
        finally:
            await queue.put(None)

    driver = asyncio.create_task(_drive())
    try:
        while (event := await queue.get()) is not None:
            yield event
        await driver
    finally:
        if not driver.done():
            driver.cancel()


def _counterfactual_payload(counterfactual: Counterfactual | None) -> dict[str, Any]:
    """Project the computed projection for the wire.

    Sent alongside the narration so the panel can show the two weightings side
    by side. The arithmetic is the claim; the prose is the explanation of it,
    and a visitor is entitled to both.

    Args:
        counterfactual: The computed projection, or None.

    Returns:
        The weightings, the outcome and the decisive terms, or an empty dict.
    """
    if counterfactual is None:
        return {}
    return {
        "original_weights": counterfactual.original_weights,
        "alternative_weights": counterfactual.alternative_weights,
        "alternative_label": counterfactual.alternative_label,
        "original_winner": counterfactual.original_winner,
        "alternative_winner": counterfactual.alternative_winner,
        "outcome": counterfactual.outcome,
        "decisive_axes": [axis.value for axis in counterfactual.decisive_axes],
    }


async def _streamed_bid_round(
    *,
    sellers: list[str],
    scenario: Scenario,
    request: QuotationRequest,
    bus: PeerMessageBus,
    budget: RunBudget,
    run_id: str,
    counters: dict[str, CounterOffer] | None,
    collect: FanOut,
) -> AsyncGenerator[StageEvent, None]:
    """Run a concurrent bidding stage, yielding each bid the moment it lands.

    **One queue, one writer, drained by this generator.** Two concurrent
    branches writing to a response can interleave halfway through an event;
    a single drain point makes that impossible rather than unlikely. It is the
    same shape the orchestrated app's specialist fan-out uses, and for the same
    reason -- the visitor has to see one column finish while the other is still
    working, or the parallelism is invisible and the demonstration is lost.

    Args:
        sellers: The sellers to ask, in order.
        scenario: The scenario being negotiated.
        request: The public RFQ.
        bus: The run's message bus.
        budget: The run's counters.
        run_id: The run's identifier.
        counters: Counter-offers keyed by seller for a final round, or None.
        collect: Filled in with the completed `FanOut` before this generator
            returns, so the caller has both the stream and the outcomes.

    Yields:
        One `bid` event per branch, as that branch settles.
    """
    stage = (
        NegotiationStage.OPENING_BIDS
        if counters is None
        else NegotiationStage.FINAL_BIDS
    )
    queue: asyncio.Queue[Bid | None] = asyncio.Queue()

    async def _drive() -> FanOut:
        try:
            return await _bid_round(
                sellers=sellers,
                scenario=scenario,
                request=request,
                bus=bus,
                budget=budget,
                run_id=run_id,
                counters=counters,
                emit=queue.put,
            )
        finally:
            # The sentinel goes in a `finally`, so the drain loop below ends
            # when the work does rather than on a poll timer -- including when
            # the whole round raised.
            await queue.put(None)

    driver = asyncio.create_task(_drive())
    try:
        while (bid := await queue.get()) is not None:
            yield StageEvent(stage=stage.value, kind="bid", payload=bid.model_dump())
        collect.branches = (await driver).branches
    finally:
        if not driver.done():
            driver.cancel()


async def _bid_round(
    *,
    sellers: list[str],
    scenario: Scenario,
    request: QuotationRequest,
    bus: PeerMessageBus,
    budget: RunBudget,
    run_id: str,
    counters: dict[str, CounterOffer] | None,
    emit: Callable[[Bid], Awaitable[None]] | None = None,
) -> FanOut:
    """Run one concurrent bidding stage across both sellers.

    Each branch assembles its own context through `opacity.assemble_context`,
    so neither is ever handed the other's material. The two branches share no
    state beyond the budget counter.

    Args:
        sellers: The sellers to ask, in order.
        scenario: The scenario being negotiated.
        request: The public RFQ.
        bus: The run's message bus.
        budget: The run's counters.
        run_id: The run's identifier.
        counters: The counter-offers keyed by seller for a final round, or None
            for the opening round.
        emit: Awaited with each bid the moment its branch completes, so the
            caller can put it on the wire before the other branch finishes.

    Returns:
        The `FanOut` for this stage. A single surviving seller still returns
        both branches, one of them failed.
    """

    async def _one(seller_id: str) -> Bid:
        context = opacity.assemble_context(
            seller_id, bus=bus, scenario_id=scenario.id, rfq_text=request.text
        )
        if counters is None:
            step = await agents.seller_opening_bid(context, budget=budget)
        else:
            step = await agents.seller_final_bid(
                context, counter=counters[seller_id], budget=budget
            )
        budget.count_stage_call()
        if emit is not None:
            await emit(step.output)
        return step.output

    if len(sellers) == 1:
        # A degraded round: one seller already failed, so there is nothing to
        # run concurrently. Wrapped in the same shape so callers do not branch.
        only = sellers[0]
        try:
            return _single(await _one(only), only)
        except (AgentLaneError, RunBudgetExceededError, TimeoutError) as exc:
            logger.warning("collab_branch_failed", branch=only, error=str(exc))
            return _single_failure(only, exc)

    return await fan_out((sellers[0], _one(sellers[0])), (sellers[1], _one(sellers[1])))


def _single(bid: Bid, label: str) -> FanOut:
    """Wrap one successful bid in the fan-out shape."""
    return FanOut(branches=[BranchOutcome(label=label, status="completed", value=bid)])


def _single_failure(label: str, error: BaseException) -> FanOut:
    """Wrap one failed bid in the fan-out shape."""
    return FanOut(branches=[BranchOutcome(label=label, status="failed", error=error)])


async def _reissue_for_differentiation(
    *,
    outcome: NegotiationOutcome,
    scenario: Scenario,
    request: QuotationRequest,
    bus: PeerMessageBus,
    budget: RunBudget,
    run_id: str,
) -> str:
    """Re-issue one opening bid with a constraint-salience nudge.

    **Replaces rather than adds.** The re-issued bid overwrites the original in
    `outcome.opening_bids` and `budget.count_stage_call()` is not called again,
    so the six-call claim holds. The provider request is real and is charged to
    `budget.used`, which is what the run's two spare requests are for.

    Args:
        outcome: The run's accumulating result. Mutated in place.
        scenario: The scenario being negotiated.
        request: The public RFQ.
        bus: The run's message bus.
        budget: The run's counters.
        run_id: The run's identifier.

    Returns:
        A short note for the degradation record, or an empty string when the
        re-issue could not be afforded or failed.
    """
    target = outcome.opening_bids[0].seller_id
    try:
        context = opacity.assemble_context(
            target, bus=bus, scenario_id=scenario.id, rfq_text=request.text
        )
        step = await agents.seller_opening_bid(
            context, budget=budget, nudge=validator.DIFFERENTIATION_NUDGE
        )
    except (AgentLaneError, RunBudgetExceededError, TimeoutError) as exc:
        logger.info(
            "collab_differentiation_retry_skipped", run_id=run_id, error=str(exc)
        )
        return ""

    outcome.opening_bids[0] = step.output
    logger.info("collab_differentiation_retry", run_id=run_id, seller=target)
    return f"{target}'s opening bid was re-issued once for differentiation"


async def _award_stage(
    *,
    outcome: NegotiationOutcome,
    weighting: PriorityWeighting,
    request: QuotationRequest,
    budget: RunBudget,
    run_id: str,
) -> AsyncGenerator[StageEvent, None]:
    """Run the award and reconcile it against its own scoring.

    On mismatch, one regeneration is attempted naming the inconsistency. On a
    persistent mismatch the award is emitted **with a flag**, not corrected:
    substituting the implied winner would replace one unverified claim with
    another and hide that anything went wrong.

    Args:
        outcome: The run's accumulating result. Mutated in place.
        weighting: The visitor's stated priorities.
        request: The public RFQ.
        budget: The run's counters.
        run_id: The run's identifier.

    Yields:
        The award event, or an error event when the award could not be made.
    """
    seller_ids = [bid.seller_id for bid in outcome.final_bids]
    try:
        step = await agents.buyer_award(
            request=request,
            weighting=weighting,
            final_bids=outcome.final_bids,
            budget=budget,
        )
        budget.count_stage_call()
    except (AgentLaneError, RunBudgetExceededError) as exc:
        logger.warning("collab_award_failed", run_id=run_id, error=str(exc))
        outcome.degradation["buyer"] = "award_failed"
        yield StageEvent(
            stage=NegotiationStage.AWARD.value,
            kind="error",
            payload={
                "code": "award_failed",
                "message": (
                    "The buyer could not produce an award. Every bid above is "
                    "still shown."
                ),
            },
        )
        return

    award = step.output
    check = validator.reconcile_award(award, weighting=weighting, seller_ids=seller_ids)

    if not check.consistent:
        logger.info(
            "collab_award_reconciliation_retry", run_id=run_id, problem=check.problem
        )
        try:
            retry = await agents.buyer_award(
                request=request,
                weighting=weighting,
                final_bids=outcome.final_bids,
                budget=budget,
                inconsistency=check.problem,
            )
            award = retry.output
            check = validator.reconcile_award(
                award, weighting=weighting, seller_ids=seller_ids
            )
        except (AgentLaneError, RunBudgetExceededError) as exc:
            logger.info(
                "collab_award_regeneration_skipped", run_id=run_id, error=str(exc)
            )

    outcome.award = award
    outcome.award_reconciled = check.consistent
    outcome.reconciliation_note = check.problem
    if not check.consistent:
        logger.warning(
            "collab_award_did_not_reconcile", run_id=run_id, problem=check.problem
        )

    yield StageEvent(
        stage=NegotiationStage.AWARD.value,
        kind="award",
        payload={
            "award": award.model_dump(),
            "reconciled": check.consistent,
            "reconciliation_note": check.problem,
            "model_calls_used": budget.used,
            "negotiation_stage_calls": budget.negotiation_stage_calls,
        },
    )


def _publish_bid(
    bus: PeerMessageBus, bid: Bid, *, scenario_id: str, run_id: str, public_text: str
) -> None:
    """Route a seller's bid to the buyer through the opacity-policed bus.

    Addressed to the buyer and to nobody else, which is what keeps the message
    log free of seller-to-seller traffic by construction rather than by
    convention.

    Args:
        bus: The run's message bus.
        bid: The bid to publish.
        scenario_id: The scenario being negotiated.
        run_id: The run's identifier.
        public_text: The RFQ, excluded from the leak check.
    """
    opacity.deliver(
        bus,
        PeerMessageEnvelope(
            sender=bid.seller_id,
            recipient=opacity.BUYER_ID,
            stage=bid.stage,
            work_item=_artifact("bid", bid.model_dump()),
        ),
        scenario_id=scenario_id,
        run_id=run_id,
        public_text=public_text,
    )
