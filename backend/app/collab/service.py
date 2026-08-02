# Built with Spec4 AI - https://spec4.ai
"""Starting a collaboration run: validate, gate, hold, compose. In that order.

This phase builds everything up to the first model call and nothing past it.
`begin_run` is the deterministic front half of the run: it checks the two
inputs, charges the showcase-wide hourly gate, reserves the whole call budget,
and composes the request for quotation. Phase 3 adds the six negotiation turns
behind it.

## The ordering is the design, and each swap breaks something specific

1. **Validate first.** An invalid scenario id should cost nothing. Reserving
   before checking would spend a run's budget on a request that was never going
   to execute, and leave a refund path that can be forgotten.
2. **Gate before holding.** `reserve_capability` is the showcase-wide meter
   every example shares; the hold is this run's claim on what is left. Holding
   first would promise budget the gate had not agreed to.
3. **Hold before composing.** The capability is explicit that a run is never
   *begun* unless it can finish. Composing first would produce a request for
   quotation the visitor can see and the allowance cannot execute -- the
   orchestrated app's named failure, one screen over.

## Reserved units, and how the number was settled

`RUN_HOLD_UNITS` is `runtime.MAX_PROVIDER_REQUESTS` -- 12: six negotiation
calls, the two post-award explanation calls, and four held back for the repairs
the sequencer makes explicitly. The visitor-facing number stays 6, because that
is what the *negotiation* costs; the rest is the run being able to finish.

**A logical call is not a provider request, and this project has already been
broken in production by conflating them.** PydanticAI binds typed output
through a synthetic output tool and re-prompts when a model botches the call,
so one logical step can cost two provider requests; v5 measured 2 of 6
orchestrated steps doing exactly that.

Phase 3 chose the first of the two ways out this docstring used to leave open:
`runtime.STEP_REQUEST_LIMIT = 1`, so PydanticAI cannot re-prompt silently and
every repair is a replacement the sequencer authorises and records. That choice
stands and is deliberately *not* padded -- raising it would buy reliability by
making repairs invisible, in the one example built to demonstrate visible peer
exchanges. What was padded instead is this hold, because at 8 the run had no
room for the repairs it does make: measured on the Phase 6 smoke run, an award
regeneration fired correctly and paid for itself by costing the sensitivity
panel its model narration.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Final

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.collab import runtime, sequencer
from backend.app.collab.opacity import COLLAB_APP_NAME, ConstraintLeakError
from backend.app.collab.rfq import QuotationRequest, compose_rfq
from backend.app.collab.scenarios import PriorityWeighting, Scenario
from backend.app.collab.telemetry import RunTelemetry
from backend.app.collab.validation import (
    InvalidRequestError,
    validate_request,
)
from backend.app.core.config import get_settings
from backend.app.core.observability import report_abort
from backend.app.db.models import NegotiationRecord, PeerMessage, UsageLimit
from backend.app.services import allowance_holds, shared

logger = structlog.get_logger()

#: The six stages that spend a model call: two opening bids, two counter-offers,
#: two best-and-final bids. The RFQ and the routing of counter-offers are
#: deterministic and cost nothing.
NEGOTIATION_STAGE_CALLS: Final[int] = 6

#: The private-position reveal and the priority-sensitivity counterfactual, both
#: written after the award.
EXPLANATION_CALLS: Final[int] = 2

#: What is reserved before anything begins. See the module docstring.
#:
#: Sourced from `runtime.MAX_PROVIDER_REQUESTS` rather than re-derived from the
#: two counts above, so the hold and the ceiling cannot drift apart: a hold
#: smaller than the ceiling promises budget the run is allowed to overspend, and
#: a hold larger than it charges for requests that can never be made. They were
#: equal by coincidence of arithmetic until the repair headroom was added to one
#: of them.
RUN_HOLD_UNITS: Final[int] = runtime.MAX_PROVIDER_REQUESTS

#: What the visitor is told a run costs. The negotiation is the run; the two
#: explanation calls are what the app does *about* the run once it is over.
VISITOR_FACING_CALL_COUNT: Final[int] = NEGOTIATION_STAGE_CALLS


class Outcome(StrEnum):
    """How an attempt to start a run ended.

    `INVALID_REQUEST` and `USAGE_LIMIT_REACHED` must not be collapsed: one the
    visitor fixes by choosing differently, the other they cannot fix at all and
    can only wait out. That distinction is the same one the moderation gate
    draws between blocked and unavailable, for the same reason.
    """

    READY = "ready"
    INVALID_REQUEST = "invalid_request"
    USAGE_LIMIT_REACHED = "usage_limit_reached"


@dataclass(frozen=True)
class Allowance:
    """What is left of the shared hourly gate, and when it resets.

    Attributes:
        remaining: Units still available this hour, never negative.
        cap: The hour's cap.
        resets_at: When the window rolls over and the counter zeroes.
    """

    remaining: int
    cap: int
    resets_at: datetime


@dataclass(frozen=True)
class RunStart:
    """The result of trying to begin a run.

    Attributes:
        outcome: Whether the run may proceed.
        run_id: The run's identifier. Also the allowance hold's key and the
            `negotiation_runs` primary key, so all three are joinable.
        scenario: The resolved scenario, when the request was valid.
        weighting: The resolved weighting, when the request was valid.
        quotation_request: The composed RFQ, present only on `READY`.
        hold_units: How many units were reserved, on `READY`.
        code: A machine-readable refusal code, on `INVALID_REQUEST`.
        visitor_message: What to show, when refused.
        allowance: What is left and when it resets, on
            `USAGE_LIMIT_REACHED`. The capability requires a cap refusal carry
            both rather than reading as a generic error.
        telemetry: The run's accumulating summary.
    """

    outcome: Outcome
    run_id: str
    scenario: Scenario | None = None
    weighting: PriorityWeighting | None = None
    quotation_request: QuotationRequest | None = None
    hold_units: int = 0
    code: str | None = None
    visitor_message: str | None = None
    allowance: Allowance | None = None
    telemetry: RunTelemetry | None = None


async def read_allowance(session: AsyncSession) -> Allowance:
    """Read what is left of the generation gate this hour.

    Applies the **same strictly-older window comparison** that
    `reserve_capability` applies. A reader that skipped it would report last
    hour's leftover count as this hour's figure, which is the documented way to
    get this wrong -- the removed console had to do this too, and
    `shared.utc_window()` is public for exactly this reason.

    Args:
        session: An async SQLAlchemy session.

    Returns:
        The remaining units, the cap, and when the window rolls over. A
        capability with no row yet reports its full cap, which is accurate:
        nothing has been spent.
    """
    window = shared.utc_window()
    result = await session.execute(
        select(UsageLimit).where(UsageLimit.capability == shared.CAPABILITY_GENERATION)
    )
    row = result.scalar_one_or_none()

    if row is None:
        # Only reachable before the very first generation call of a deployment;
        # `reserve_capability` creates the row lazily. The configured cap is
        # read straight from settings rather than through `shared`'s private
        # capability-to-setting map.
        cap = get_settings().generation_hourly_limit
        return Allowance(remaining=cap, cap=cap, resets_at=window + timedelta(hours=1))

    used = 0 if row.window_start is None or row.window_start < window else row.used
    return Allowance(
        remaining=max(0, row.cap - used),
        cap=row.cap,
        resets_at=window + timedelta(hours=1),
    )


async def begin_run(
    session: AsyncSession,
    *,
    run_id: str,
    scenario_id: str,
    weighting_id: str | None = None,
    weights: dict[str, int] | None = None,
) -> RunStart:
    """Validate, gate, reserve, and compose the RFQ. No model call is made.

    Args:
        session: An async SQLAlchemy session.
        run_id: The run's identifier, used as the allowance hold's key.
        scenario_id: The scenario the visitor chose.
        weighting_id: A preset weighting id, if they chose a preset.
        weights: An explicit per-axis vector, if they supplied one.

    Returns:
        A `RunStart`. On `READY` the budget is held and the request for
        quotation is composed; on either refusal nothing has been reserved and
        nothing needs refunding.
    """
    # 1. Validate. An invalid request costs nothing.
    try:
        validated = validate_request(
            scenario_id=scenario_id, weighting_id=weighting_id, weights=weights
        )
    except InvalidRequestError as exc:
        logger.info(
            "collab_run_refused",
            run_id=run_id,
            outcome=Outcome.INVALID_REQUEST.value,
            code=exc.code,
        )
        return RunStart(
            outcome=Outcome.INVALID_REQUEST,
            run_id=run_id,
            code=exc.code,
            visitor_message=str(exc),
        )

    telemetry = RunTelemetry(
        run_id=run_id,
        scenario_id=validated.scenario.id,
        weighting_id=validated.weighting.id,
    )

    # 2. The showcase-wide hourly gate, before any budget is claimed.
    try:
        await shared.reserve_capability(
            session,
            shared.CAPABILITY_GENERATION,
            app_name=COLLAB_APP_NAME,
            units=RUN_HOLD_UNITS,
        )
    except shared.ServiceUnavailableError as exc:
        allowance = await read_allowance(session)
        telemetry.outcome = Outcome.USAGE_LIMIT_REACHED.value
        telemetry.emit()
        return RunStart(
            outcome=Outcome.USAGE_LIMIT_REACHED,
            run_id=run_id,
            scenario=validated.scenario,
            weighting=validated.weighting,
            visitor_message=str(exc),
            allowance=allowance,
            telemetry=telemetry,
        )

    # 3. Claim the whole budget, so a run is never begun that cannot finish.
    await allowance_holds.reserve(
        session,
        hold_key=run_id,
        capability=shared.CAPABILITY_GENERATION,
        app_name=COLLAB_APP_NAME,
        units=RUN_HOLD_UNITS,
    )
    telemetry.hold_units = RUN_HOLD_UNITS

    # 4. Compose the request for quotation. Still no model call.
    request = compose_rfq(validated.scenario, validated.weighting)

    logger.info(
        "collab_run_started",
        run_id=run_id,
        scenario_id=validated.scenario.id,
        weighting_id=validated.weighting.id,
        hold_units=RUN_HOLD_UNITS,
        visitor_facing_calls=VISITOR_FACING_CALL_COUNT,
    )
    return RunStart(
        outcome=Outcome.READY,
        run_id=run_id,
        scenario=validated.scenario,
        weighting=validated.weighting,
        quotation_request=request,
        hold_units=RUN_HOLD_UNITS,
        telemetry=telemetry,
    )


async def abandon_run(session: AsyncSession, run_id: str, *, reason: str) -> bool:
    """Refund a run's reserved units because it will not spend them.

    Called on every path that ends a run before its calls are made. Refunding
    and redeeming are both releases -- one because the calls happened, one
    because they never will -- and a run that failed before spending anything
    must not cost the showcase the same as one that succeeded.

    Args:
        session: An async SQLAlchemy session.
        run_id: The run whose hold to release.
        reason: Why, for the log line.

    Returns:
        True if a reserved hold was released, False if there was nothing to
        release. Missing and already-terminal holds are **not** raised: this is
        called from failure paths, and a refund that raised would turn a
        recoverable failure into a second one.
    """
    try:
        await allowance_holds.refund(session, run_id)
    except (allowance_holds.HoldNotFoundError, allowance_holds.HoldStateError):
        logger.info("collab_run_refund_skipped", run_id=run_id, reason=reason)
        return False

    logger.info("collab_run_refunded", run_id=run_id, reason=reason)
    return True


async def persist_run(
    session: AsyncSession,
    *,
    outcome: sequencer.NegotiationOutcome,
    scenario_id: str,
    weighting_id: str,
) -> None:
    """Write the immutable run record and one row per peer message.

    Called once at run end. The message log is persisted as a **stored
    projection** rather than left as a client-side tally, which is what makes
    the app's headline opacity claim provable: `SELECT count(*) FROM
    peer_messages WHERE sender <> 'buyer' AND recipient <> 'buyer'` is one
    predicate, and it is expected to return zero for every run ever recorded. A
    tally computed in the browser would only prove what the browser was shown.

    The reveal and sensitivity columns carry the two post-award panels when the
    round concluded, and stay null when it did not. That distinction matters:
    a null column means the award never happened, not that the explanation came
    back empty.

    Args:
        session: An async SQLAlchemy session.
        outcome: Everything the run produced.
        scenario_id: The scenario negotiated.
        weighting_id: The weighting applied.
    """
    record = NegotiationRecord(
        id=outcome.run_id,
        scenario_id=scenario_id,
        weighting_id=weighting_id,
        negotiation_stage_call_count=outcome.budget.negotiation_stage_calls,
        total_model_calls_used=outcome.budget.used,
        quotation_request=outcome.request.as_payload(),
        opening_bids={"bids": [bid.model_dump() for bid in outcome.opening_bids]},
        counter_offers={
            "offers": [offer.model_dump() for offer in outcome.counter_offers]
        },
        final_bids={"bids": [bid.model_dump() for bid in outcome.final_bids]},
        award=(
            {
                "award": outcome.award.model_dump(),
                "reconciled": outcome.award_reconciled,
                "reconciliation_note": outcome.reconciliation_note,
            }
            if outcome.award is not None
            else None
        ),
        # Written only when the award exists -- `run_negotiation` skips the
        # whole explanation stage otherwise, so a round that did not conclude
        # leaves these null rather than holding an empty object. "Not produced"
        # and "produced nothing" have to stay distinguishable.
        reveal=outcome.reveal,
        sensitivity=outcome.sensitivity,
        stage_timings=dict(outcome.stage_timings),
        degradation_flags=dict(outcome.degradation),
    )
    session.add(record)

    for envelope in outcome.bus.log():
        session.add(
            PeerMessage(
                run_id=outcome.run_id,
                sequence=envelope.sequence,
                sender=envelope.sender,
                recipient=envelope.recipient,
                stage=envelope.stage,
                work_item=envelope.work_item.model_dump(by_alias=True, mode="json"),
            )
        )

    await session.commit()


async def stream_run(
    session: AsyncSession,
    *,
    run_id: str,
    scenario_id: str,
    weighting_id: str | None = None,
    weights: dict[str, int] | None = None,
) -> AsyncGenerator[sequencer.StageEvent, None]:
    """Run one negotiation end to end, yielding one event per stage.

    Ties together what the two phases built: Phase 2's validate-gate-hold-compose
    front half, this phase's six-stage sequencer, and the persistence at the
    end. The caller turns the events into SSE and knows nothing else.

    A refusal yields exactly one `error` event and stops. Nothing is persisted
    and nothing is held, so a capped run never produces a partial record --
    which is the capability's rule, not a nicety.

    Args:
        session: An async SQLAlchemy session.
        run_id: The run's identifier.
        scenario_id: The scenario the visitor chose.
        weighting_id: A preset weighting id, if they chose a preset.
        weights: An explicit per-axis vector, if they supplied one.

    Yields:
        One `StageEvent` per stage, or a single `error` event on refusal.
    """
    start = await begin_run(
        session,
        run_id=run_id,
        scenario_id=scenario_id,
        weighting_id=weighting_id,
        weights=weights,
    )

    if start.outcome is not Outcome.READY:
        payload: dict[str, object] = {
            "code": start.code or start.outcome.value,
            "outcome": start.outcome.value,
            "message": start.visitor_message or "",
        }
        if start.allowance is not None:
            payload["remaining"] = start.allowance.remaining
            payload["cap"] = start.allowance.cap
            payload["resets_at"] = start.allowance.resets_at.isoformat()
        yield sequencer.StageEvent(stage="refused", kind="error", payload=payload)
        return

    assert start.scenario is not None  # noqa: S101 - READY implies both
    assert start.weighting is not None  # noqa: S101
    assert start.quotation_request is not None  # noqa: S101
    assert start.telemetry is not None  # noqa: S101

    telemetry = start.telemetry
    final: sequencer.NegotiationOutcome | None = None
    try:
        async for item in sequencer.run_negotiation(
            run_id=run_id,
            scenario=start.scenario,
            weighting=start.weighting,
            request=start.quotation_request,
            telemetry=telemetry,
        ):
            if isinstance(item, sequencer.NegotiationOutcome):
                final = item
            else:
                yield item
    except ConstraintLeakError as exc:
        # A hard safety stop. The offending artifact was never delivered and is
        # never emitted; the run ends here rather than continuing past a real
        # confidentiality defect.
        logger.error("collab_run_aborted_on_leak", run_id=run_id, error=str(exc))
        # Sentry's auto-enabling integrations capture what *raises* through a
        # request; this is caught deliberately and turned into a stream event so
        # the visitor keeps their partial results, so it needs reporting
        # explicitly. No-ops with no DSN -- which matters, because this is
        # inside an exception handler where a raise would turn a graceful
        # degradation into a 500.
        report_abort(
            "collab_leak_detected",
            run_id=run_id,
            scenario_id=scenario_id,
        )
        telemetry.leak_lint_hits += 1
        telemetry.outcome = "leak_detected"
        telemetry.emit()
        await abandon_run(session, run_id, reason="leak_detected")
        yield sequencer.StageEvent(
            stage="aborted",
            kind="error",
            payload={
                "code": "leak_detected",
                "message": (
                    "The negotiation was stopped because an outgoing message "
                    "carried a rival supplier's private position. Nothing "
                    "further was sent."
                ),
            },
        )
        return

    if final is None:
        telemetry.outcome = "no_result"
        telemetry.emit()
        report_abort("collab_no_result", run_id=run_id, scenario_id=scenario_id)
        await abandon_run(session, run_id, reason="no_result")
        return

    await persist_run(
        session,
        outcome=final,
        scenario_id=start.scenario.id,
        weighting_id=start.weighting.id,
    )

    # The hold is redeemed rather than refunded: the calls were genuinely made.
    try:
        await allowance_holds.redeem(session, run_id)
    except (allowance_holds.HoldNotFoundError, allowance_holds.HoldStateError):
        logger.info("collab_hold_not_redeemable", run_id=run_id)

    telemetry.outcome = "complete" if final.award is not None else "degraded"
    telemetry.emit()
