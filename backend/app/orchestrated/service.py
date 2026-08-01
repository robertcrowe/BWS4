# Built with Spec4 AI - https://spec4.ai
"""The delegation phase, in the one order that keeps its guarantees.

Five steps, and the sequence is the design:

1. **Preset or free-form.** A curated preset is verified server-side to
   byte-match a known question and skips moderation entirely. Trusting a
   client-supplied `preset_id` would make "this is a preset" an assertion
   anyone could make about any text.
2. **Moderate free-form input.** A refusal returns here, before anything is
   reserved and before any model is called.
3. **The showcase-wide hourly gate.**
4. **Reserve the whole three-call budget as a hold.**
5. **Call the coordinator.**

Reversing any adjacent pair breaks something specific. Moderating after
reserving would charge a visitor for a question that was never going to run.
Reserving after the coordinator call would let a delegation decision reach the
screen that the allowance can no longer execute -- the capability's named
failure between showing the decision and confirming dispatch. Gating after
reserving would hold budget the gate had already refused.

## Exactly one model call, whatever happens

The coordinator is called once. Repair is deterministic and pure
(`validator.py`), so a malformed decision costs nothing extra; if it cannot be
repaired the run is abandoned and the hold refunded rather than re-prompted. The
budget counter charges per *provider request*, so even a framework-level retry
would be visible rather than silently doubling the run's cost.

## The dispatch phase

`confirm_dispatch()` is the second half, and it is a **separate HTTP request**
because the human decision between the two is the pattern. The go-ahead cannot
be a flag on the first call: a flag has a default, and a default would let a
delegation decision nobody read dispatch itself.

Three properties of that step are load-bearing and none is obvious:

1. **The hold is redeemed before anything is dispatched, not after.** It is the
   replay guard. Without it, the same `decision_id` posted a hundred times buys
   two hundred specialist calls; with it, the second attempt finds a hold that
   is no longer `reserved` and is refused. This is why a both-specialists-failed
   run cannot then refund the hold -- see `DISPATCH_EVENT_ERROR` below.
2. **The posted decision is re-validated on arrival.** It travelled to the
   client and back, so it is client-controlled input, exactly like the plan the
   planning app's run endpoint receives. Structure is re-checked and brief
   length is bounded before a single word of it reaches a model.
3. **Both branch coroutines are created before either is awaited.** Serialising
   them would leave every assertion in this file true and destroy the only thing
   the app exists to show.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.observability import report_abort
from backend.app.orchestrated import coordinator, merge, specialists, validator
from backend.app.orchestrated.presets import CURATED_PRESETS
from backend.app.orchestrated.runtime import (
    MAX_PROVIDER_REQUESTS,
    STEP_REQUEST_LIMIT,
    VISITOR_FACING_CALL_COUNT,
    BranchOutcome,
    FanOut,
    RunBudget,
    RunBudgetExceededError,
    fan_out,
)
from backend.app.orchestrated.schemas import (
    Brief,
    CoordinatorDraft,
    DelegationDecision,
    MergedAnswer,
    SpecialistAnswer,
    SpecialistId,
    SpecialistStatus,
    SubagentResult,
)
from backend.app.services import allowance_holds, shared
from backend.app.services.agent_runtime import AgentLaneError, StepResult
from backend.app.services.moderation import (
    ModerationCategory,
    ModerationVerdict,
    Moderator,
    hash_question,
)

logger = structlog.get_logger()

#: Tag on every shared-service invocation this app makes.
ORCHESTRATED_APP_NAME = "Orchestrated-Subagents Example App"

#: What the hold claims: the delegation call, the two specialists, and the
#: coordinator's closing turn.
RUN_CALL_BUDGET = MAX_PROVIDER_REQUESTS

#: Provider requests held back for the coordinator's closing synthesis turn.
#:
#: **Enforced by lowering the fan-out's ceiling, not by subtraction after the
#: fact.** An advisory reserve was not enough, and a live run proved it: a
#: tool-less specialist step took *two* provider requests, because PydanticAI
#: binds typed output through a synthetic output tool and re-prompts when a
#: model botches the call. Delegation (1) plus a two-request specialist (2) plus
#: its partner (1) reached the ceiling of four, and the merge was refused with
#: three requests' worth of work already spent.
#:
#: One whole step's allowance, not one request: the merge is a step like any
#: other and can re-prompt like any other.
#:
#: A specialist is not entitled to more than the run can afford, so the fan-out
#: runs against a ceiling lower by exactly that reserve. A branch that needs a
#: request the reserve is holding fails *that column* -- which the
#: partial-failure path already
#: shows honestly -- rather than silently costing the run its fan-in. The same
#: lesson the planning app learned: without a reserve, retries spend a run down
#: to raw material with nothing left to compose it.
SYNTHESIS_RESERVE: Final[int] = STEP_REQUEST_LIMIT

#: Longest brief accepted on a dispatch request.
#:
#: The coordinator is asked for 40-120 words, so this is roughly four times the
#: upper bound -- loose enough that a verbose but genuine brief passes, tight
#: enough that the endpoint is not a general-purpose prompt channel. The briefs
#: arrive from the client, so something has to bound them.
MAX_BRIEF_CHARS: Final[int] = 2_000


class Outcome(StrEnum):
    """Why a delegation attempt ended the way it did.

    Each value is a different thing to show a visitor, and the differences are
    actionable: reword, wait, or retry. Collapsing them into one generic error
    would leave someone unable to tell which.

    **`MODERATION_BLOCKED` and `MODERATION_UNAVAILABLE` are separate on purpose.**
    The shared gate distinguishes "this text was refused" from "nothing could
    check it", and flattening that here would put the whole distinction to
    waste: a visitor whose question was never examined would be told it was
    rejected. Caught by a live run against a deployment with no moderation key,
    where every free-form question was reported as blocked.
    """

    READY = "ready"
    MODERATION_BLOCKED = "moderation_blocked"
    MODERATION_UNAVAILABLE = "moderation_unavailable"
    USAGE_LIMIT_REACHED = "usage_limit_reached"
    COORDINATOR_FAILED = "coordinator_failed"
    INVALID_DELEGATION = "invalid_delegation"
    DISPATCH_UNKNOWN = "dispatch_unknown"
    DISPATCH_EXPIRED = "dispatch_expired"
    SPECIALISTS_FAILED = "specialists_failed"
    SYNTHESIS_FAILED = "synthesis_failed"


@dataclass
class DelegationOutcome:
    """The result of the delegation phase.

    Attributes:
        outcome: Which of the four endings this was.
        decision_id: The run's id, and the hold's key. Present even on failure
            so a log line can be tied to a refusal.
        decision: The dispatchable decision, when `outcome` is READY.
        visitor_message: What to show, when it is not.
        hold_key: The reserved hold, when one is outstanding.
        model_calls: Provider requests actually spent.
    """

    outcome: Outcome
    decision_id: str
    decision: DelegationDecision | None = None
    visitor_message: str | None = None
    hold_key: str | None = None
    model_calls: int = 0

    @property
    def ready(self) -> bool:
        """True when there is a decision to show the visitor."""
        return self.outcome is Outcome.READY


def find_preset(preset_id: str | None, question: str) -> str | None:
    """Confirm server-side that a claimed preset really is one.

    The client sends a `preset_id`, and that claim is worth nothing on its own:
    accepting it would let any text skip moderation by attaching an id. So the
    id is looked up in the curated set and the submitted text must **byte-match**
    the stored wording. Anything else is treated as free-form and moderated.

    Args:
        preset_id: The id the client claims, if any.
        question: The submitted text.

    Returns:
        The preset id when it is genuine, otherwise None.
    """
    if not preset_id:
        return None

    for preset in CURATED_PRESETS:
        if preset.preset_id == preset_id and preset.question == question:
            return preset.preset_id
    return None


async def begin_run(
    session: AsyncSession,
    *,
    question: str,
    preset_id: str | None,
    moderate: Moderator,
) -> DelegationOutcome:
    """Run the delegation phase and return a decision or a refusal.

    Google-style docstring per project convention.

    Args:
        session: An async SQLAlchemy session for gate, hold and log writes.
        question: The visitor's question.
        preset_id: The preset the client claims this came from, if any.
        moderate: The shared moderation gate, injected so a route can substitute
            it and so this module does not reach for a provider itself.

    Returns:
        The outcome. Exactly one provider request is made on the READY path and
        on the coordinator-failure path; none at all on the other two.
    """
    decision_id = uuid.uuid4().hex
    verified_preset = find_preset(preset_id, question)

    # 1 + 2. A curated preset is pre-vetted, so the gate is skipped entirely --
    # no latency, and no dependency on the moderation service being reachable
    # for the common path.
    if verified_preset is None:
        verdict: ModerationVerdict = await moderate(question, ORCHESTRATED_APP_NAME)
        if not verdict.allowed:
            refusal = (
                Outcome.MODERATION_UNAVAILABLE
                if verdict.category is ModerationCategory.UNAVAILABLE
                else Outcome.MODERATION_BLOCKED
            )
            logger.info(
                "orchestrated_delegation_refused",
                decision_id=decision_id,
                outcome=refusal.value,
                moderation_category=verdict.category.value,
            )
            # Nothing reserved, nothing gated, nothing called.
            return DelegationOutcome(
                outcome=refusal,
                decision_id=decision_id,
                visitor_message=verdict.visitor_message,
            )

    # 3. The showcase-wide hourly gate, before any budget is claimed.
    try:
        await shared.reserve_capability(
            session,
            shared.CAPABILITY_GENERATION,
            app_name=ORCHESTRATED_APP_NAME,
            units=RUN_CALL_BUDGET,
        )
    except shared.ServiceUnavailableError as exc:
        logger.info(
            "orchestrated_delegation_refused",
            decision_id=decision_id,
            outcome=Outcome.USAGE_LIMIT_REACHED.value,
        )
        return DelegationOutcome(
            outcome=Outcome.USAGE_LIMIT_REACHED,
            decision_id=decision_id,
            visitor_message=str(exc),
        )

    # 4. Claim the whole budget before the decision exists, so a confirmed
    # dispatch either completes or was refused up front.
    await allowance_holds.reserve(
        session,
        hold_key=decision_id,
        capability=shared.CAPABILITY_GENERATION,
        app_name=ORCHESTRATED_APP_NAME,
        units=RUN_CALL_BUDGET,
    )

    # 5. One model call.
    budget = RunBudget()
    try:
        step = await coordinator.decide(question, budget=budget)
    except (AgentLaneError, RunBudgetExceededError) as exc:
        await allowance_holds.refund(session, decision_id)
        logger.warning(
            "orchestrated_delegation_failed",
            decision_id=decision_id,
            outcome=Outcome.COORDINATOR_FAILED.value,
            error_type=type(exc).__name__,
            model_calls=budget.used,
        )
        report_abort(
            Outcome.COORDINATOR_FAILED.value,
            decision_id=decision_id,
            error_type=type(exc).__name__,
        )
        return DelegationOutcome(
            outcome=Outcome.COORDINATOR_FAILED,
            decision_id=decision_id,
            visitor_message=(
                "The coordinator couldn't be reached, so no specialists were chosen. "
                "Try again in a moment."
            ),
            model_calls=budget.used,
        )

    check = validator.validate_and_repair(step.output, question=question)

    if not check.ok or check.decision is None:
        await allowance_holds.refund(session, decision_id)
        logger.warning(
            "orchestrated_delegation_failed",
            decision_id=decision_id,
            outcome=Outcome.INVALID_DELEGATION.value,
            errors=check.errors,
            model_calls=budget.used,
        )
        report_abort(
            Outcome.INVALID_DELEGATION.value,
            decision_id=decision_id,
            errors=len(check.errors),
        )
        return DelegationOutcome(
            outcome=Outcome.INVALID_DELEGATION,
            decision_id=decision_id,
            visitor_message=(
                "The coordinator returned a delegation that couldn't be run, so "
                "nothing was dispatched. Try again."
            ),
            model_calls=budget.used,
        )

    await shared.log_invocation(
        session,
        app_name=ORCHESTRATED_APP_NAME,
        capability=shared.CAPABILITY_GENERATION,
        summary=_log_summary(check.decision, step.model),
    )
    logger.info(
        "orchestrated_delegation_ready",
        decision_id=decision_id,
        preset_id=verified_preset,
        pairing=sorted(s.value for s in check.decision.chosen_specialists),
        brief_jaccard=round(check.jaccard, 3),
        repaired=check.repaired,
        repair_rules=check.rules_fired,
        fit_quality=check.decision.fit_quality.value,
        model_calls=budget.used,
        call_ceiling=budget.ceiling,
        model=step.model,
    )

    return DelegationOutcome(
        outcome=Outcome.READY,
        decision_id=decision_id,
        decision=check.decision,
        hold_key=decision_id,
        model_calls=budget.used,
    )


def _log_summary(decision: DelegationDecision, model: str) -> str:
    """Build the cross-app log line for one delegation.

    Carries the pairing, the fit and the serving model -- and no question text,
    following the same rule the chained-calls and planning apps set: usage is
    logged, authored content is not.

    Args:
        decision: The validated decision.
        model: The slug that served the call.

    Returns:
        The summary line.
    """
    pairing = "+".join(sorted(item.value for item in decision.chosen_specialists))
    return f"Delegation: {pairing} ({decision.fit_quality.value} fit) via {model}"


# --------------------------------------------------------------------------
# The dispatch phase
# --------------------------------------------------------------------------

#: Event names on the dispatch stream. The client dispatches on these, so they
#: are constants rather than literals scattered through the emit calls.
DISPATCH_EVENT_STATUS: Final[str] = "specialist_status"
DISPATCH_EVENT_ANSWER: Final[str] = "specialist_answer"
DISPATCH_EVENT_COMPLETE: Final[str] = "fan_out_complete"
DISPATCH_EVENT_MERGED: Final[str] = "merged_answer"
DISPATCH_EVENT_ERROR: Final[str] = "error"

#: How a specialist's branch is doing, before it has an answer.
BRANCH_RUNNING: Final[str] = "running"

#: What to run for one specialist. Injected so the dispatcher can be tested
#: without a provider, on the same reasoning as `tools/agent.py`'s
#: `execute_search`: the concurrency, the retry guard and the event ordering
#: are what this module owns, and none of them needs a real model to exercise.
SpecialistRunner = Callable[
    [SpecialistId, str, str, RunBudget], Awaitable[StepResult[SpecialistAnswer]]
]

#: How to run the closing synthesis turn. Injected for the same reason as
#: `SpecialistRunner`: the ordering, the budget arithmetic and the failure
#: handling around the fan-in are what this module owns, and none of them needs
#: a real model to exercise.
Synthesiser = Callable[..., Awaitable[tuple[MergedAnswer, dict[str, object]]]]


@dataclass(frozen=True)
class DispatchEvent:
    """One thing that happened during the fan-out, ready for the wire.

    Attributes:
        name: The SSE event name the client dispatches on.
        payload: The JSON-serialisable body.
    """

    name: str
    payload: dict[str, object] = field(default_factory=dict)


async def run_specialist(
    specialist_id: SpecialistId, brief: str, question: str, budget: RunBudget
) -> StepResult[SpecialistAnswer]:
    """Run one specialist's model call, selected by id.

    The default `SpecialistRunner`. Selection goes through the registry rather
    than an import, so the coordinator's enum-constrained choice is the only
    thing that decides which persona runs.

    Args:
        specialist_id: Which roster member to run.
        brief: What that specialist was asked to cover.
        question: The visitor's question.
        budget: The run's provider-request counter.

    Returns:
        The model's answer and the slug that served it.
    """
    agent = specialists.get_specialist(specialist_id)
    return await agent.answer(brief=brief, question=question, budget=budget)


def _retry_permitted(budget: RunBudget) -> bool:
    """Decide whether a failed specialist may be tried once more.

    The capability allows one retry on a transient transport failure, and the
    guard it must respect is that the retry cannot eat the request the merge
    needs. So a retry is permitted only while the run has slack *above* the
    synthesis reserve.

    **At the shipped ceiling this returns False, and that is the correct
    answer rather than a bug.** Do the arithmetic: four requests, one spent on
    delegation, two more the moment both specialists are issued -- which happens
    before either can fail, since they are concurrent. One request remains and
    it belongs to the merge. Retrying would buy a second column at the price of
    having nothing to compose the two into.

    It is also worth remembering what has already been tried by the time this
    is asked. The lane runs a `FallbackModel` over the whole chain, so a
    transport failure has already been retried against every other configured
    model; `AgentLaneError` means all of them failed. A further attempt is a
    ninth try, not a first.

    Args:
        budget: The run's counter.

    Returns:
        True only when a retry would leave the synthesis reserve intact.
    """
    return budget.remaining() > SYNTHESIS_RESERVE


def _failure_result(
    specialist_id: SpecialistId, status: SpecialistStatus, message: str
) -> SubagentResult:
    """Build the result for a branch that produced nothing.

    Args:
        specialist_id: Which column failed.
        status: `FAILED` or `TIMED_OUT`.
        message: What to show the visitor. Never the provider's own error
            string -- that belongs in the operator's logs.

    Returns:
        The stamped result.
    """
    return SubagentResult(specialist_id=specialist_id, status=status, error=message)


def _result_payload(result: SubagentResult) -> dict[str, object]:
    """Render one specialist result for the wire.

    Args:
        result: The settled result.

    Returns:
        The JSON-serialisable body of a `specialist_answer` event.
    """
    return {
        "specialist_id": result.specialist_id.value,
        "status": result.status.value,
        "answer": result.answer,
        "key_points": result.key_points,
        "error": result.error,
    }


def preset_id_for(question: str) -> str | None:
    """Find the curated preset this question byte-matches, if any.

    Used by the run summary so `preset_id` is a *server-side* fact rather than
    a client claim. The dispatch request carries no preset id at all, and
    accepting one would let any run label itself curated.

    Args:
        question: The submitted text.

    Returns:
        The preset id, or None for free-form input.
    """
    for preset in CURATED_PRESETS:
        if preset.question == question:
            return preset.preset_id
    return None


def revalidate_posted_decision(
    decision: DelegationDecision,
) -> validator.DelegationCheck | None:
    """Re-check a decision that has been to the client and back.

    The dispatch request carries the decision as JSON, so it is client-supplied
    however it originated -- the same position the planning app's run endpoint
    is in with its posted plan, and it gets the same treatment: never trusted,
    always re-checked. Running it back through the pure validator re-imposes
    exactly two distinct roster specialists with a brief each, so a hand-edited
    payload cannot dispatch three specialists or one.

    Brief *text* is bounded rather than reconstructed. It cannot be verified --
    nothing was stored to compare it against -- so the honest control is a
    length cap here plus delimiter neutralisation at the prompt boundary. What
    that leaves is a visitor able to influence the wording of a prompt they
    already influenced by asking the question; what it prevents is that wording
    growing without limit or forging the framing around the question.

    Args:
        decision: The decision as posted.

    Returns:
        The check -- carrying the re-validated decision, the brief overlap and
        any repair rules that fired, all of which the run summary reports --
        or None if the decision cannot be repaired into a dispatchable one or
        its briefs exceed `MAX_BRIEF_CHARS`.
    """
    if any(len(brief.instruction) > MAX_BRIEF_CHARS for brief in decision.briefs):
        return None

    check = validator.validate_and_repair(
        CoordinatorDraft(
            chosen_specialists=list(decision.chosen_specialists),
            rationale=decision.rationale,
            briefs=list(decision.briefs),
            fit_quality=decision.fit_quality,
        ),
        question=decision.rationale,
    )
    return check if check.ok else None


async def _claim_dispatch(session: AsyncSession, decision_id: str) -> Outcome | None:
    """Verify and redeem the hold that authorises this dispatch.

    Redeeming *before* the specialists run is what makes a `decision_id`
    single-use. A second dispatch of the same id finds the hold already
    redeemed and is refused, which is the only thing standing between this
    endpoint and an unbounded supply of free model calls.

    Args:
        session: An async SQLAlchemy session.
        decision_id: The run's id, which is also the hold's key.

    Returns:
        None when the dispatch may proceed, or the outcome to report.
    """
    try:
        await allowance_holds.redeem(session, decision_id)
    except allowance_holds.HoldNotFoundError:
        # No delegation was ever made under this id -- or it was made against a
        # different deployment.
        return Outcome.DISPATCH_UNKNOWN
    except allowance_holds.HoldStateError:
        # Already redeemed, refunded, or swept by the expiry sweep. Deliberately
        # not re-reserved: silently taking fresh budget would turn an expired
        # decision into a free second run.
        return Outcome.DISPATCH_EXPIRED
    return None


async def _run_branch(
    *,
    brief: Brief,
    question: str,
    budget: RunBudget,
    runner: SpecialistRunner,
    emit: Callable[[DispatchEvent], Awaitable[None]],
    timings: dict[str, float],
    settled: set[str],
) -> SubagentResult:
    """Run one specialist and report on it as it goes.

    Emits its own `running` status the instant it starts and its own answer the
    instant it settles, rather than returning them to be published once both
    branches are done. Batching would make the two columns appear together at
    the slower branch's pace, which is precisely the appearance of parallelism
    without the substance.

    A hard failure is caught here so the branch returns a result rather than
    raising: the sibling must not be disturbed. A **timeout** is deliberately
    not caught -- it arrives as cancellation from the fan-out helper's per-branch
    `asyncio.timeout`, passes straight through `except Exception`, and is
    converted by the driver. That keeps the helper's own timeout handling on the
    live path instead of shadowed by a local `try`.

    Args:
        brief: Which specialist to run and what to ask it.
        question: The visitor's question.
        budget: The run's provider-request counter.
        runner: How to run a specialist.
        emit: Publishes one event to the single stream writer.
        timings: Written into, keyed by specialist id, so the driver can report
            per-branch latency and the skew between the two dispatches.
        settled: Ids that have published their own answer event. The driver
            publishes for whoever is missing, which is how a **timed-out**
            column reaches the screen at all -- cancellation ends this coroutine
            before its own emit, and without the driver's backstop that column
            would sit showing `running` forever.

    Returns:
        This column's result. Never raises for a model failure.
    """
    specialist_id = brief.specialist_id
    started = time.monotonic()
    timings[f"{specialist_id.value}_started"] = started

    await emit(
        DispatchEvent(
            DISPATCH_EVENT_STATUS,
            {"specialist_id": specialist_id.value, "status": BRANCH_RUNNING},
        )
    )

    result: SubagentResult
    try:
        try:
            step = await runner(specialist_id, brief.instruction, question, budget)
        except AgentLaneError:
            if not _retry_permitted(budget):
                raise
            logger.info(
                "orchestrated_specialist_retried",
                specialist_id=specialist_id.value,
                remaining=budget.remaining(),
            )
            step = await runner(specialist_id, brief.instruction, question, budget)
        result = specialists.build_result(brief, step)
    except Exception as exc:  # noqa: BLE001 - the lane raises several unrelated types
        logger.warning(
            "orchestrated_specialist_failed",
            specialist_id=specialist_id.value,
            error_type=type(exc).__name__,
        )
        result = _failure_result(
            specialist_id,
            SpecialistStatus.FAILED,
            "This specialist couldn't be reached, so its column is empty.",
        )

    timings[f"{specialist_id.value}_seconds"] = round(time.monotonic() - started, 3)
    settled.add(specialist_id.value)
    await emit(DispatchEvent(DISPATCH_EVENT_ANSWER, _result_payload(result)))
    return result


def _settle(outcome: BranchOutcome, brief: Brief) -> SubagentResult:
    """Turn one fan-out branch into this column's result.

    Args:
        outcome: What the fan-out helper reported for this branch.
        brief: The brief that branch was given.

    Returns:
        The branch's own result when it completed, or a stamped failure.
    """
    if outcome.status == "completed" and isinstance(outcome.value, SubagentResult):
        return outcome.value
    if outcome.status == "timed_out":
        return _failure_result(
            brief.specialist_id,
            SpecialistStatus.TIMED_OUT,
            "This specialist was still working when the run stopped waiting.",
        )
    return _failure_result(
        brief.specialist_id,
        SpecialistStatus.FAILED,
        "This specialist couldn't be reached, so its column is empty.",
    )


async def confirm_dispatch(
    session: AsyncSession,
    *,
    decision_id: str,
    decision: DelegationDecision,
    question: str,
    budget: RunBudget | None = None,
    runner: SpecialistRunner = run_specialist,
    synthesiser: Synthesiser = merge.synthesise,
) -> AsyncGenerator[DispatchEvent, None]:
    """Run the two specialists concurrently, reporting each as it happens.

    Google-style docstring per project convention.

    The order is: claim the hold, re-validate what was posted, then dispatch.
    Nothing reaches a model until both gates have passed, which is what the
    capability means by no specialist request preceding the confirmation.

    Args:
        session: An async SQLAlchemy session for the hold and log writes.
        decision_id: The delegation this dispatch confirms, and the hold's key.
        decision: The decision as the client posted it back.
        question: The visitor's question, re-sent with the decision.
        budget: The run's counter. Defaults to a fresh one with the delegation
            call already charged, since that call has happened by now.
        runner: How to run a specialist. Substituted in tests.
        synthesiser: How to run the closing merge. Substituted in tests.

    Yields:
        A `specialist_status` per branch as it starts, a `specialist_answer` per
        branch as it settles, and finally either `fan_out_complete` or `error`.
    """
    outcome = await _claim_dispatch(session, decision_id)
    if outcome is not None:
        logger.info(
            "orchestrated_dispatch_refused",
            decision_id=decision_id,
            outcome=outcome.value,
        )
        yield DispatchEvent(
            DISPATCH_EVENT_ERROR,
            {
                "outcome": outcome.value,
                "message": (
                    "This delegation is no longer valid — it may have expired or "
                    "already been run. Ask the question again to get a fresh one."
                ),
                "decision_id": decision_id,
                "retryable": False,
            },
        )
        return

    check = revalidate_posted_decision(decision)
    if check is None or check.decision is None:
        logger.warning(
            "orchestrated_dispatch_refused",
            decision_id=decision_id,
            outcome=Outcome.INVALID_DELEGATION.value,
        )
        yield DispatchEvent(
            DISPATCH_EVENT_ERROR,
            {
                "outcome": Outcome.INVALID_DELEGATION.value,
                "message": (
                    "That delegation couldn't be run as sent, so nothing was "
                    "dispatched. Ask the question again."
                ),
                "decision_id": decision_id,
                "retryable": True,
            },
        )
        return

    # The delegation call is already spent by the time a dispatch arrives, and
    # its true cost is unknowable here -- the client cannot be asked, and the
    # delegation happened in a different request. Assuming it took its whole
    # step allowance is the safe direction: the run under-spends rather than
    # over-committing budget it does not have.
    checked = check.decision
    run_budget = budget if budget is not None else RunBudget(used=STEP_REQUEST_LIMIT)
    first_brief, second_brief = checked.briefs[0], checked.briefs[1]

    queue: asyncio.Queue[DispatchEvent | None] = asyncio.Queue()
    timings: dict[str, float] = {}
    settled: set[str] = set()

    async def emit(event: DispatchEvent) -> None:
        await queue.put(event)

    def branch(brief: Brief) -> Awaitable[SubagentResult]:
        return _run_branch(
            brief=brief,
            question=question,
            budget=run_budget,
            runner=runner,
            emit=emit,
            timings=timings,
            settled=settled,
        )

    # Both coroutines exist before either is awaited. Awaiting the first here
    # would serialise the run: every result below would still be correct, and
    # the one thing this app exists to demonstrate would be gone.
    first, second = branch(first_brief), branch(second_brief)

    async def drive() -> FanOut:
        try:
            return await fan_out(
                (first_brief.specialist_id.value, first),
                (second_brief.specialist_id.value, second),
            )
        finally:
            # A sentinel rather than polling: the drain loop below ends when the
            # fan-out says so, not on a timer.
            await queue.put(None)

    driver: asyncio.Task[FanOut] = asyncio.create_task(drive())
    fan: FanOut | None = None
    # Hold the merge's request back for the duration of the fan-out. A branch
    # that would spend it is refused instead, so the run can always finish.
    run_budget.ceiling -= SYNTHESIS_RESERVE
    try:
        # The single writer. Both branches publish into the queue and only this
        # loop yields, so two concurrent producers can never interleave halfway
        # through one event on the wire.
        while (event := await queue.get()) is not None:
            yield event
        fan = await driver
    finally:
        run_budget.ceiling += SYNTHESIS_RESERVE
        # A client that disconnects mid-fan-out abandons this generator. Without
        # this the two specialist tasks would keep running against a stream
        # nobody is reading.
        if not driver.done():
            driver.cancel()

    if fan is None:  # pragma: no cover - only reachable on cancellation
        return

    results = [
        _settle(outcome, brief)
        for outcome, brief in zip(
            fan.branches, (first_brief, second_brief), strict=True
        )
    ]
    survivors = [result for result in results if result.ok]

    # A branch cancelled by the per-branch timeout never reached its own emit.
    # Publishing here is what stops that column showing `running` for the rest
    # of the visitor's session.
    for result in results:
        if result.specialist_id.value not in settled:
            yield DispatchEvent(DISPATCH_EVENT_ANSWER, _result_payload(result))

    skew_ms = round(
        abs(
            timings.get(f"{first_brief.specialist_id.value}_started", 0.0)
            - timings.get(f"{second_brief.specialist_id.value}_started", 0.0)
        )
        * 1000,
        1,
    )
    summary = RunSummary(
        decision_id=decision_id,
        question=question,
        preset_id=preset_id_for(question),
        pairing=sorted(brief.specialist_id.value for brief in checked.briefs),
        brief_jaccard=round(check.jaccard, 3),
        repaired=check.repaired,
        repair_rules=list(check.rules_fired),
        fit_quality=checked.fit_quality.value,
        statuses={
            result.specialist_id.value: result.status.value for result in results
        },
        latencies={
            key: value for key, value in timings.items() if key.endswith("_seconds")
        },
        dispatch_skew_ms=skew_ms,
        survivors=len(survivors),
        hold_state=allowance_holds.STATE_REDEEMED,
        hold_units=RUN_CALL_BUDGET,
    )

    if not survivors:
        summary.finish(Outcome.SPECIALISTS_FAILED, run_budget)
        await _emit_run_summary(session, summary)
        report_abort(
            Outcome.SPECIALISTS_FAILED.value,
            decision_id=decision_id,
            model_calls=run_budget.used,
        )
        # Both columns are empty, so there is nothing for a merge to integrate.
        # The hold is already redeemed and cannot be given back -- the two
        # provider requests were genuinely made, and this project's standing
        # rule is that over-counting a shared free tier is the safe direction to
        # be wrong in. What is returned is the *visitor's* run: `refund_run`
        # tells the client not to count this against their session allowance,
        # which is the allowance the capability's escalation path is about.
        yield DispatchEvent(
            DISPATCH_EVENT_ERROR,
            {
                "outcome": Outcome.SPECIALISTS_FAILED.value,
                "message": (
                    "Neither specialist could be reached, so there's nothing to "
                    "merge. This didn't count against your runs — try again."
                ),
                "decision_id": decision_id,
                "retryable": True,
                "refund_run": True,
            },
        )
        return

    yield DispatchEvent(
        DISPATCH_EVENT_COMPLETE,
        {
            "decision_id": decision_id,
            "survivors": [result.specialist_id.value for result in survivors],
            "model_call_count": VISITOR_FACING_CALL_COUNT,
        },
    )

    # The fan-in: the run's fourth and final provider request. The columns are
    # already on screen, so a failure here reports itself without taking them
    # down with it.
    try:
        merged, fan_in = await synthesiser(
            question=question,
            decision=checked,
            results=results,
            budget=run_budget,
        )
    except (AgentLaneError, RunBudgetExceededError) as exc:
        logger.warning(
            "orchestrated_synthesis_failed",
            decision_id=decision_id,
            error_type=type(exc).__name__,
            model_calls=run_budget.used,
        )
        summary.finish(Outcome.SYNTHESIS_FAILED, run_budget)
        await _emit_run_summary(session, summary)
        report_abort(
            Outcome.SYNTHESIS_FAILED.value,
            decision_id=decision_id,
            error_type=type(exc).__name__,
            model_calls=run_budget.used,
        )
        yield DispatchEvent(
            DISPATCH_EVENT_ERROR,
            {
                "outcome": Outcome.SYNTHESIS_FAILED.value,
                "message": (
                    "The specialists answered, but they couldn't be merged into "
                    "one response. Their answers are still shown above."
                ),
                "decision_id": decision_id,
                "retryable": True,
            },
        )
        return

    summary.merge = fan_in
    summary.finish(Outcome.READY, run_budget)
    await _emit_run_summary(session, summary)

    yield DispatchEvent(DISPATCH_EVENT_MERGED, _merged_payload(merged, decision_id))


def _merged_payload(merged: MergedAnswer, decision_id: str) -> dict[str, object]:
    """Render the merged answer for the wire.

    Args:
        merged: The checked merged answer.
        decision_id: The run's id.

    Returns:
        The JSON-serialisable body of the `merged_answer` event.
    """
    note = merged.disagreement_note
    return {
        "decision_id": decision_id,
        "text": merged.text,
        "sources_used": [item.value for item in merged.sources_used],
        "disagreement_note": {
            "summary": note.summary,
            "agreements": note.agreements,
            "complements": note.complements,
            "contradictions": [
                {
                    "claim_a": item.claim_a,
                    "claim_b": item.claim_b,
                    "specialist_a": item.specialist_a.value
                    if item.specialist_a
                    else None,
                    "specialist_b": item.specialist_b.value
                    if item.specialist_b
                    else None,
                }
                for item in note.contradictions
            ],
            "comparable": note.comparable,
        },
        "model_call_count": VISITOR_FACING_CALL_COUNT,
    }


# --------------------------------------------------------------------------
# One run, one summary
# --------------------------------------------------------------------------

#: The consolidated per-run telemetry event.
#:
#: Phases 2-5 each logged their own slice -- a delegation event, a fan-out
#: event, a fan-in event -- which meant answering "what did that run actually
#: do?" required joining three records by `decision_id` and hoping none had been
#: dropped. This is the single record the whole run reduces to, and it is
#: emitted on **every** terminal path so a failed run is as legible as a
#: successful one.
RUN_SUMMARY_EVENT: Final[str] = "orchestrated_run_summary"


@dataclass
class RunSummary:
    """Everything worth knowing about one run, and nothing that identifies anyone.

    **`question` is held here but never emitted.** `as_event()` publishes only a
    salted hash of it, reusing the moderation service's own helper so telemetry
    and `moderation_log` agree on what a question's identity is. The privacy
    requirement is that raw visitor text is not retained, and the way to make
    that hold is for the serialiser -- not each caller -- to be the thing that
    enforces it.

    Attributes:
        decision_id: The run, and the hold's key.
        question: The visitor's question. Hashed on the way out, never logged.
        preset_id: The curated preset this matched, verified server-side.
        pairing: The two specialists that ran, sorted.
        brief_jaccard: Wording overlap between the two briefs.
        repaired: Whether deterministic repair changed the posted decision.
        repair_rules: Which repairs fired.
        fit_quality: The coordinator's own read on the pairing.
        statuses: Final status per specialist.
        latencies: Seconds per specialist branch.
        dispatch_skew_ms: Milliseconds between the two dispatches.
        survivors: Columns that produced an answer.
        hold_state: What became of the allowance hold.
        hold_units: How much it claimed.
        merge: The fan-in checks' own telemetry, when a merge happened.
        outcome: How the run ended.
        model_calls: Provider requests spent.
        call_ceiling: The cap they were spent against.
    """

    decision_id: str
    question: str
    preset_id: str | None
    pairing: list[str]
    brief_jaccard: float
    repaired: bool
    repair_rules: list[str]
    fit_quality: str
    statuses: dict[str, str]
    latencies: dict[str, float]
    dispatch_skew_ms: float
    survivors: int
    hold_state: str
    hold_units: int
    merge: dict[str, object] = field(default_factory=dict)
    outcome: str = ""
    model_calls: int = 0
    call_ceiling: int = 0

    def finish(self, outcome: Outcome, budget: RunBudget) -> None:
        """Stamp how the run ended and what it spent.

        Args:
            outcome: The terminal outcome.
            budget: The run's counter, read for its final totals.
        """
        self.outcome = outcome.value
        self.model_calls = budget.used
        self.call_ceiling = budget.ceiling

    def as_event(self) -> dict[str, object]:
        """Render the summary for structlog, with the question hashed.

        Returns:
            The event fields. `question_hash` replaces the text entirely --
            there is no code path that emits the question itself.
        """
        return {
            "decision_id": self.decision_id,
            "question_hash": hash_question(self.question),
            "question_source": "preset" if self.preset_id else "freeform",
            "preset_id": self.preset_id,
            "pairing": self.pairing,
            "brief_jaccard": self.brief_jaccard,
            "delegation_repaired": self.repaired,
            "repair_rules": self.repair_rules,
            "fit_quality": self.fit_quality,
            "specialist_statuses": self.statuses,
            "specialist_latencies": self.latencies,
            "dispatch_skew_ms": self.dispatch_skew_ms,
            "survivors": self.survivors,
            "hold_state": self.hold_state,
            "hold_units": self.hold_units,
            "outcome": self.outcome,
            "model_calls": self.model_calls,
            "call_ceiling": self.call_ceiling,
            "visitor_facing_calls": VISITOR_FACING_CALL_COUNT,
            **{f"merge_{key}": value for key, value in self.merge.items()},
        }

    def as_log_line(self) -> str:
        """Render the one-line summary written to `service_log_entries`.

        Carries the shape of the run and none of its content, following the
        rule the chained-calls and planning apps set: usage is logged, authored
        text is not.

        Returns:
            The summary line for the cross-app request log.
        """
        statuses = ", ".join(
            f"{key}={value}" for key, value in sorted(self.statuses.items())
        )
        merged = "merged" if self.merge else "no merge"
        return (
            f"Run {self.outcome}: {'+'.join(self.pairing)} ({statuses}), {merged}, "
            f"{self.model_calls}/{self.call_ceiling} provider requests, "
            f"skew {self.dispatch_skew_ms}ms"
        )


async def _emit_run_summary(session: AsyncSession, summary: RunSummary) -> None:
    """Log one run summary and record it in the cross-app request log.

    Both destinations, from one object, so the structured event and the
    operator-facing row cannot describe different runs.

    Args:
        session: An async SQLAlchemy session.
        summary: The finished run.
    """
    logger.info(RUN_SUMMARY_EVENT, **summary.as_event())
    await shared.log_invocation(
        session,
        app_name=ORCHESTRATED_APP_NAME,
        capability=shared.CAPABILITY_GENERATION,
        summary=summary.as_log_line(),
    )
