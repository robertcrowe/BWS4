# Built with Spec4 AI - https://spec4.ai
"""The agent_loop_runtime: plan, wait for the visitor, then execute step by step.

This is the orchestrator the capability describes -- and the shape of the loop
is the teaching point. It is bounded, sequential, and **user-advanced**: the two
public entry points are separate functions because there is a human decision
between them, and no executor call can fire without a second, explicit call into
this module. That gap is the human-in-the-loop checkpoint, expressed as an API
boundary rather than as a flag somebody could forget to check.

## Three guarantees this module owns

1. **The quota gate runs before every model call.** `_gate` is handed to the
   lane's `GatedModel`, so it fires per model *request*, not per step -- a
   tool-using research step makes several, and gating the step would spend
   several units against one check.
2. **The call ceiling is deterministic code.** `CallBudget.charge()` sits in
   that same hook and refuses the call over the ceiling before any provider is
   reached. Never a prompt instruction.
3. **Failures are reported, not hidden.** A research step that fails is marked
   failed and the run continues; the synthesis step then sees the failure and is
   asked to acknowledge the gap. Nothing invents a result to keep the shape of
   the output tidy.

## What is deliberately absent

There is no persistence of the visitor's city, interests, or generated
itinerary. Usage is reserved and invocations are logged -- with step numbers,
models, counts and outcomes, never authored text -- following the same rule the
chained-calls app established: unlogged is not unmetered, and metered is not a
licence to keep the content.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Literal

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import AsyncRetrying, RetryError, retry_if_not_exception_type, stop_after_attempt

from backend.app.db.models import SearchQuery
from backend.app.planning import agents, validator
from backend.app.planning.budget import CallBudget, CallCeilingExceeded
from backend.app.planning.sanitize import (
    InvalidInputError,
    sanitize_city,
    sanitize_interests,
)
from backend.app.planning.schemas import (
    KIND_RESEARCH,
    STATUS_COMPLETED,
    STATUS_FAILED,
    Itinerary,
    Plan,
    PlanStep,
    StepResult,
)
from backend.app.services import shared
from backend.app.services.agent_runtime import AgentLaneError, StepRequestLimitExceeded
from backend.app.services.web_search import (
    ExaClientError,
    ExaRateLimitError,
    ExaResult,
    search,
)

logger = structlog.get_logger()

#: Tag on every shared_framework_services invocation this app makes. Matches the
#: directory entry's display name so the cross-app log reads like the landing
#: page.
PLANNING_APP_NAME = "Planning-Agent Example App"

#: Per-step wall-clock limit.
#:
#: The capability specifies 30s, and **30s is measurably wrong for this step**.
#: A research step is not one model call: it is up to three, plus up to two Exa
#: searches. Measured against the live stack, one Exa search alone takes ~5s and
#: a complete step ranged from 4.1s to 40.7s -- so the 30s bound fires on
#: healthy steps, and because a timeout is retried, each one costs a second full
#: step's worth of model calls. A live run spent its entire budget that way and
#: halted before composing anything.
#:
#: 90s implements what the 30s was for -- bounding a hung step -- at a threshold
#: this step can actually meet. The visitor is not left staring at nothing
#: meanwhile: Phase 3 streams each result as it lands, which is what the
#: responsiveness NFR actually asks for.
STEP_TIMEOUT_SECONDS = 90

#: Fewest model requests a research step can possibly succeed in: one turn to
#: call the search tool, one to read the results and answer. A step given fewer
#: cannot finish, so starting one only burns a call to prove it.
MIN_RESEARCH_REQUESTS = 2

#: Requests held back from research so the synthesis step can always run.
#:
#: Without this the run spends everything on research and halts with notes and
#: no itinerary -- observed on a live run. An itinerary composed from partial
#: research and honest about the gap is worth more than complete research with
#: nothing composed from it.
#:
#: It matches `agents.SYNTHESIS_REQUEST_LIMIT` rather than counting one call,
#: and the difference is the schema retry. Reserving one held back enough for
#: synthesis to be *attempted* but not enough for PydanticAI to re-ask when the
#: first response failed validation -- so the run could still reach the end with
#: nothing composed, by a narrower route than the one this constant was added to
#: close.
SYNTHESIS_RESERVE = agents.SYNTHESIS_REQUEST_LIMIT

#: Attempts per research step: the initial one plus the single retry the
#: capability allows. Retries cost model calls, which the ceiling counts -- so a
#: retried step can be what takes a run to its budget, and that is intended.
STEP_ATTEMPTS = 2

_NO_RESULTS_SUMMARY = (
    "The web search returned no usable results for this step, so it contributed "
    "nothing to the itinerary."
)


class PlanningError(Exception):
    """Base class for planning failures, carrying a machine-readable code."""

    code = "planning_failed"


class InvalidGoalError(PlanningError):
    """Raised when the submitted city or interests cannot be used."""

    code = "invalid_goal"


class UsageLimitReachedError(PlanningError):
    """Raised when today's shared generation budget is spent.

    Distinct from `PlanUnavailableError` for the reason every app in this repo
    keeps them apart: a spent cap resets at the top of the hour and an unreachable
    provider does not, and an operator told only "503" learns neither.
    """

    code = "usage_limit_reached"


class PlanUnavailableError(PlanningError):
    """Raised when no usable plan could be produced, even after one replan."""

    code = "plan_unavailable"


@dataclass(frozen=True)
class PlanOutcome:
    """A plan, ready to show the visitor and awaiting their go-ahead.

    Attributes:
        goal: The rendered goal block, carried forward so execution works from
            the same statement the planner did.
        plan: The validated, possibly trimmed plan.
        trimmed_note: What was dropped for budget reasons, or None.
        replanned: Whether the first attempt was rejected by the checker.
        model: The slug that produced the plan.
        calls_used: Model calls spent so far. Passed into `execute_plan` so the
            ceiling covers the whole run rather than restarting at the
            checkpoint.
    """

    goal: str
    plan: Plan
    trimmed_note: str | None
    replanned: bool
    model: str
    calls_used: int


@dataclass(frozen=True)
class ExecutionEvent:
    """One thing worth telling the visitor about, as the run produces it.

    An async iterator of these is what Phase 3 turns into SSE events. Modelled
    as a small tagged union rather than three separate streams so ordering is
    preserved by construction: a `halted` event cannot arrive before the step
    results it is halting after.

    Attributes:
        kind: `step_result`, `itinerary`, or `halted`.
        step_result: Set when kind is `step_result`.
        itinerary: Set when kind is `itinerary`.
        notice: Plain-language explanation, set when kind is `halted`.
        code: Machine-readable reason for a halt.
    """

    kind: Literal["step_result", "itinerary", "halted"]
    step_result: StepResult | None = None
    itinerary: Itinerary | None = None
    notice: str | None = None
    code: str | None = None


@dataclass
class _StepRun:
    """Mutable bookkeeping for one research step's tool activity."""

    queries: list[str] = field(default_factory=list)
    search_failed: bool = False
    quota_exhausted: bool = False


def goal_for(*, city: str, interests: str) -> str:
    """Sanitise the visitor's inputs and render the goal block.

    Shared by planning and execution so both work from a byte-identical goal.
    The execution request arrives separately, carrying the city and interests
    again, and re-deriving the block here is what keeps the synthesis step
    describing the same trip the planner decomposed.

    Args:
        city: The submitted city, unsanitised.
        interests: The submitted interests, unsanitised.

    Returns:
        The goal block to send to every step of the run.

    Raises:
        InvalidGoalError: If either field is blank or over-long after cleaning.
    """
    try:
        return agents.build_goal(sanitize_city(city), sanitize_interests(interests))
    except InvalidInputError as exc:
        raise InvalidGoalError(str(exc)) from exc


async def create_plan(session: AsyncSession, *, city: str, interests: str) -> PlanOutcome:
    """Run the planner call and return a plan for the visitor to review.

    **Executes nothing.** This is the first half of the two-phase invocation;
    the research and synthesis steps do not run until `execute_plan` is called
    after the visitor's explicit go-ahead.

    Google-style docstring per project convention.

    Args:
        session: An async SQLAlchemy session for usage/logging bookkeeping.
        city: The submitted city, unsanitised.
        interests: The submitted interests, unsanitised.

    Returns:
        The plan, plus what it cost and whether it needed a second attempt.

    Raises:
        InvalidGoalError: If city or interests are blank or over-long.
        UsageLimitReachedError: If today's generation cap is spent.
        PlanUnavailableError: If the model chain failed, or if the checker
            rejected both the plan and its replan.
    """
    goal = goal_for(city=city, interests=interests)

    # One run reserved before the planner fires. Deliberately charged here
    # rather than at execution: the planner call is where a run starts spending
    # real quota, and a visitor who reviews a plan and walks away has still
    # spent it. Reserving at the go-ahead instead would leave `/plan` able to
    # burn generation units with nothing counting the runs. It also matches the
    # capability, which checks the allowance "before the planner call is made"
    # and says re-running a step costs no further allowance.
    #
    # Known consequence, measured: executing the *same* plan twice charges one
    # planning unit, not two, because only this function charges. So the
    # planning cap bounds planning sessions rather than executions. That is the
    # intended reading, and the per-call generation gate -- which no request
    # body can reach -- remains what actually bounds the spend.
    try:
        await shared.reserve_capability(
            session, shared.CAPABILITY_PLANNING, app_name=PLANNING_APP_NAME
        )
    except shared.ServiceUnavailableError as exc:
        raise UsageLimitReachedError(
            "This demo's hourly planning-run budget is spent. It exists so one app "
            "cannot drain the model budget the other example apps share. It resets "
            "at the top of the hour."
        ) from exc

    budget = CallBudget()
    gate = _gate(session, budget)

    problems: list[str] | None = None
    check: validator.PlanCheck | None = None

    # Two attempts at most: the initial plan, then one replan carrying the
    # checker's complaints. The capability allows exactly one, and a loop that
    # kept trying would be the runaway this tier is most prone to.
    for attempt in (1, 2):
        try:
            step = await agents.run_planner(goal=goal, problems=problems, on_request=gate)
        except AgentLaneError as exc:
            await _log(session, "planner", f"attempt {attempt} failed: model chain")
            raise PlanUnavailableError(
                "The planner could not be reached, so no plan was produced."
            ) from exc
        except shared.ServiceUnavailableError as exc:
            # The gate refused before the provider was reached. Reported as its
            # own error because a spent hourly cap and an unreachable model are
            # different operator problems with different remedies.
            raise UsageLimitReachedError(str(exc)) from exc
        except CallCeilingExceeded as exc:
            raise PlanUnavailableError(str(exc)) from exc

        check = validator.check_plan(step.output)
        logger.info(
            "planning_plan_validated",
            attempt=attempt,
            passed=check.ok,
            errors=len(check.errors),
            steps_planned=len(step.output.steps),
            steps_kept=len(check.plan.steps) if check.plan else 0,
            trimmed=check.trimmed_note is not None,
            model=step.model,
        )

        if check.ok and check.plan is not None:
            await _log(
                session,
                "planner",
                f"plan accepted on attempt {attempt}: {len(check.plan.steps)} steps "
                f"via {step.model}",
            )
            return PlanOutcome(
                goal=goal,
                plan=check.plan,
                trimmed_note=check.trimmed_note,
                replanned=attempt > 1,
                model=step.model,
                calls_used=budget.used,
            )

        problems = check.errors

    await _log(session, "planner", "plan rejected twice by the checker")
    raise PlanUnavailableError(
        "The planner produced a plan that could not be executed, and the corrected "
        "attempt had the same problem. Nothing was run. "
        + (check.errors[0] if check and check.errors else "")
    )


async def execute_plan(
    session: AsyncSession,
    *,
    goal: str,
    plan: Plan,
    calls_used: int = 0,
) -> AsyncIterator[ExecutionEvent]:
    """Execute an approved plan step by step, yielding each result as it lands.

    Called only after the visitor's explicit advance signal. Steps run strictly
    in order and each result is yielded before the next step starts, which is
    what lets Phase 3 stream them.

    Args:
        session: An async SQLAlchemy session for usage/logging bookkeeping.
        goal: The goal block from the `PlanOutcome`.
        plan: The approved plan.
        calls_used: Model calls already spent by the planner, so the ceiling
            spans the whole run.

    Yields:
        A `step_result` per research step, then either an `itinerary` or a
        `halted` event. A halt always arrives after whatever succeeded, never
        instead of it.
    """
    budget = CallBudget(used=calls_used)
    gate = _gate(session, budget)
    results: list[StepResult] = []

    for step in plan.steps:
        if step.kind != KIND_RESEARCH:
            continue

        allowance = budget.allowance(
            agents.RESEARCH_REQUEST_LIMIT,
            reserve=SYNTHESIS_RESERVE,
            # A failed step is retried, and `_run_step` applies this figure to
            # *each* attempt -- so the run must be able to afford all of them.
            attempts=STEP_ATTEMPTS,
        )
        if allowance < MIN_RESEARCH_REQUESTS:
            # Not enough left to finish this step, so it is reported as failed
            # rather than attempted. Attempting it would spend a call to reach
            # the same conclusion, and that call is the one the synthesis step
            # needs.
            result = StepResult(
                step_index=step.index,
                status=STATUS_FAILED,
                summary=(
                    "This run reached its model-call budget before this step could run, "
                    "so it was skipped. The itinerary below was composed without it."
                ),
            )
            logger.info("planning_step_skipped", step_index=step.index, reason="budget")
            results.append(result)
            yield ExecutionEvent(kind="step_result", step_result=result)
            continue

        try:
            result = await _run_research_step(
                session, goal=goal, step=step, gate=gate, allowance=allowance
            )
        except (CallCeilingExceeded, shared.ServiceUnavailableError) as exc:
            # Out of budget mid-run. Everything already yielded stays on the
            # visitor's screen -- an agent run must not discard work it has
            # already paid for.
            yield _halted(exc, "The run stopped before the itinerary could be composed.")
            return

        results.append(result)
        yield ExecutionEvent(kind="step_result", step_result=result)

    try:
        synthesis = await agents.run_synthesis(
            goal=goal, plan=plan, results=results, on_request=gate
        )
    except (CallCeilingExceeded, shared.ServiceUnavailableError) as exc:
        yield _halted(exc, "The research finished, but the itinerary could not be composed.")
        return
    except AgentLaneError:
        await _log(session, "synthesis", "failed: model chain")
        logger.warning("planning_synthesis_failed", steps_completed=len(results))
        # A halt, not a failed step: there is nothing after synthesis, and the
        # capability's mitigation is to keep the partial results and offer a
        # retry of this step alone -- which costs no further run allowance.
        yield ExecutionEvent(
            kind="halted",
            code="synthesis_failed",
            notice=(
                "Every research step finished, but the itinerary could not be composed. "
                "The results above are preserved — retrying runs only the final step, so "
                "the research is not repeated."
            ),
        )
        return

    await _log(
        session,
        "synthesis",
        f"itinerary composed from {len(results)} step(s) via {synthesis.model}",
    )
    logger.info(
        "planning_run_completed",
        steps_planned=len(plan.steps),
        steps_executed=len(results),
        steps_failed=sum(1 for item in results if item.status == STATUS_FAILED),
        model_calls=budget.used,
        model=synthesis.model,
    )
    yield ExecutionEvent(kind="itinerary", itinerary=synthesis.output)


async def retry_synthesis(
    session: AsyncSession, *, goal: str, plan: Plan, results: list[StepResult]
) -> Itinerary:
    """Re-run only the synthesis step against research that already completed.

    The capability's mitigation for a failed final step. Re-running the research
    would spend several more calls reproducing findings the visitor is already
    reading, and would produce *different* findings -- so the itinerary they
    finally got would not be the one their step results support.

    Args:
        session: An async SQLAlchemy session for usage/logging bookkeeping.
        goal: The goal block from the original run.
        plan: The plan that was executed.
        results: The step results from that run.

    Returns:
        The composed itinerary.

    Raises:
        UsageLimitReachedError: If today's generation cap is spent.
        PlanUnavailableError: If the synthesis call failed again.
    """
    budget = CallBudget()
    gate = _gate(session, budget)

    try:
        synthesis = await agents.run_synthesis(
            goal=goal, plan=plan, results=results, on_request=gate
        )
    except AgentLaneError as exc:
        await _log(session, "synthesis-retry", "failed: model chain")
        raise PlanUnavailableError(
            "The itinerary still could not be composed. The research results are unchanged."
        ) from exc
    except shared.ServiceUnavailableError as exc:
        raise UsageLimitReachedError(str(exc)) from exc
    except CallCeilingExceeded as exc:
        raise PlanUnavailableError(str(exc)) from exc

    await _log(session, "synthesis-retry", f"itinerary composed via {synthesis.model}")
    return synthesis.output


async def _run_research_step(
    session: AsyncSession, *, goal: str, step: PlanStep, gate, allowance: int
) -> StepResult:
    """Execute one research step, with a timeout and one retry.

    A step that fails is reported as a failed `StepResult` rather than raised:
    the capability requires research failures not halt the run. Only running out
    of budget propagates, because that ends the run by definition.

    Args:
        session: An async SQLAlchemy session.
        goal: The goal block.
        step: The research step to run.
        gate: The per-model-call hook.
        allowance: Model requests this step may make, already bounded by what
            the run has left after reserving the synthesis call.

    Returns:
        The step's result, completed or failed.

    Raises:
        CallCeilingExceeded: If the run's ceiling is reached.
        ServiceUnavailableError: If a usage cap is reached.
    """
    tracking = _StepRun()

    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(STEP_ATTEMPTS),
            # Three things must not be retried, and each was a real bug or
            # nearly one:
            #
            # - Budget errors end the run by definition; retrying spends what
            #   little is left proving the point.
            # - A step that used its whole request limit failed *deterministically*
            #   -- the model kept calling tools and never settled. A live run
            #   burned four extra calls re-running exactly that, which is what
            #   this clause exists to prevent.
            #
            # Only model faults and timeouts, which are genuinely transient,
            # earn the second attempt the capability allows.
            retry=retry_if_not_exception_type(
                (
                    CallCeilingExceeded,
                    shared.ServiceUnavailableError,
                    StepRequestLimitExceeded,
                )
            ),
            reraise=True,
        ):
            with attempt:
                async with asyncio.timeout(STEP_TIMEOUT_SECONDS):
                    outcome = await agents.run_research(
                        goal=goal,
                        step=step,
                        execute_search=_search_for(session, tracking),
                        on_request=gate,
                        request_limit=allowance,
                    )
    except (CallCeilingExceeded, shared.ServiceUnavailableError):
        # Budget, not a step failure. Ends the whole run, so it propagates.
        raise
    except (AgentLaneError, TimeoutError, RetryError) as exc:
        await _log(session, f"step-{step.index}", f"failed: {type(exc).__name__}")
        logger.warning(
            "planning_step_failed",
            step_index=step.index,
            error_type=type(exc).__name__,
            queries=len(tracking.queries),
        )
        return StepResult(
            step_index=step.index,
            status=STATUS_FAILED,
            summary=(
                "This research step could not be completed, so it contributed nothing "
                "to the itinerary. The itinerary below was composed without it."
            ),
            sources=[],
        )

    # A search the tool could not run is a failed step; a search that ran and
    # found nothing is a completed step with an honest, empty answer. The two
    # look the same in the output shape and mean different things.
    status = STATUS_FAILED if tracking.search_failed and not outcome.sources else STATUS_COMPLETED
    summary = outcome.summary
    if not outcome.sources and status == STATUS_COMPLETED:
        summary = f"{_NO_RESULTS_SUMMARY} The step reported: {outcome.summary}"

    await _log(
        session,
        f"step-{step.index}",
        f"{status}: {len(outcome.sources)} source(s), {len(tracking.queries)} "
        f"search(es), {outcome.requests} model call(s) via {outcome.model}",
    )
    logger.info(
        "planning_step_completed",
        step_index=step.index,
        status=status,
        sources=len(outcome.sources),
        searches=len(tracking.queries),
        reformulated=len(tracking.queries) > 1,
        model_calls=outcome.requests,
    )

    return StepResult(
        step_index=step.index,
        status=status,
        summary=summary,
        sources=outcome.sources,
    )


def _search_for(session: AsyncSession, tracking: _StepRun):
    """Build the injected search callable for one step.

    Everything the executor agent must not know about lives here: the search
    usage cap, `SearchQuery` persistence, and what to do when Exa is unhappy.

    A failed search is reported back to the model as a tool result rather than
    raised, following the tool-use app's established handling -- the model can
    then say honestly that it found nothing, which is a better demonstration
    than an exception that erases the step.

    Args:
        session: An async SQLAlchemy session.
        tracking: Per-step bookkeeping to record what happened.

    Returns:
        An async callable suitable for `agents.run_research`.
    """

    async def execute(query: str) -> list[ExaResult]:
        tracking.queries.append(query)

        try:
            await shared.reserve_capability(
                session, shared.CAPABILITY_SEARCH, app_name=PLANNING_APP_NAME
            )
        except shared.ServiceUnavailableError:
            tracking.quota_exhausted = True
            tracking.search_failed = True
            return []

        session.add(SearchQuery(text=query))
        await session.commit()

        try:
            return await search(query)
        except (ExaRateLimitError, ExaClientError):
            tracking.search_failed = True
            return []

    return execute


def _gate(session: AsyncSession, budget: CallBudget):
    """Build the hook that runs immediately before every model call.

    Two checks, in this order, both before any provider is contacted:

    1. `budget.charge()` -- the run's own ceiling. Refused first because it is
        free to evaluate and reaching it is this tier's characteristic failure.
    2. `reserve_capability` -- the shared per-UTC-day cap that every example app
        draws on.

    Args:
        session: An async SQLAlchemy session.
        budget: The run's call counter.

    Returns:
        An async callable to hand to the lane.
    """

    async def gate() -> None:
        budget.charge()
        await shared.reserve_capability(
            session, shared.CAPABILITY_GENERATION, app_name=PLANNING_APP_NAME
        )

    return gate


def _halted(exc: Exception, prefix: str) -> ExecutionEvent:
    """Build the halted event for a budget stop.

    Args:
        exc: The ceiling or usage-cap error that stopped the run.
        prefix: What had happened by the time it stopped.

    Returns:
        A halted event carrying a machine-readable code and an explanation.
    """
    ceiling_hit = isinstance(exc, CallCeilingExceeded)
    return ExecutionEvent(
        kind="halted",
        code="call_ceiling_reached" if ceiling_hit else "usage_limit_reached",
        notice=f"{prefix} {exc}",
    )


async def _log(session: AsyncSession, stage: str, detail: str) -> None:
    """Record one cross-app log entry for a stage of the run.

    The summary carries stage, counts, models and outcomes and **never the
    visitor's city, interests, or any generated text** -- the same rule the
    chained-calls app set, for the same privacy reason.

    Args:
        session: An async SQLAlchemy session.
        stage: Which part of the run this is.
        detail: Metadata only.
    """
    await shared.log_invocation(
        session,
        app_name=PLANNING_APP_NAME,
        capability=shared.CAPABILITY_GENERATION,
        summary=f"Planning {stage}: {detail}",
    )
