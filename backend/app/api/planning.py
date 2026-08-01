# Built with Spec4 AI - https://spec4.ai
"""The planning-agent example app's HTTP surface: plan, then run.

**Two endpoints because there is a human decision between them.** `/plan` runs
the planner and stops; `/run` executes the steps. Nothing here can execute an
unreviewed plan, because executing requires a second request that only the
visitor can make -- the capability's `human_in_the_loop` checkpoint expressed as
the shape of the API rather than as a flag somebody could default to true.

This replaces the Phase 1 stub. The **event names are unchanged** (`plan`,
`step_result`, `itinerary`) so the frontend hook's contract survives, but the
payloads are now the capability's real shapes rather than fixtures, and a fourth
event name -- `error` -- carries categorised failures.

## Failures are events, not broken streams

A run that fails halfway has already produced results the visitor is reading. So
`/run` answers 200 and reports trouble as an `error` event carrying a
machine-readable `code`, exactly as the chained-calls API returns a partial
chain as a 200 rather than a 5xx. Breaking the stream instead would discard the
very output the capability's escalation path requires be shown.

`/plan` is different and does use status codes: it either produces a plan or it
does not, and there is no partial result to protect.

## The posted plan is re-checked, never trusted

`/run` receives a plan as JSON from the client, so it is client-controlled
input. It is validated again on arrival by the same deterministic checker that
gated it on the way out. Without that, a caller could post a twenty-step plan
and have this endpoint execute it.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse, ServerSentEvent

from backend.app.db.session import async_session_factory, get_db_session
from backend.app.planning import service, validator
from backend.app.planning.budget import MAX_MODEL_CALLS
from backend.app.planning.sanitize import MAX_CITY_CHARS, MAX_INTERESTS_CHARS
from backend.app.planning.schemas import Plan, StepResult
from backend.app.planning.service import (
    InvalidGoalError,
    PlanUnavailableError,
    UsageLimitReachedError,
)
from backend.app.services import text_gate
from backend.app.services.moderation import (
    Moderator,
    get_moderator,
    get_stateless_moderator,
)

logger = structlog.get_logger()

router = APIRouter()

#: Tag on this app's moderation calls.
PLANNING_APP_NAME = "Planning-Agent Example App"


def goal_text(city: str, interests: str) -> str:
    """Render the two goal fields as the one string the gate examines.

    Checked together rather than separately: a goal is only meaningful as the
    pair, and two calls would double the latency and the log rows to answer one
    question.

    Args:
        city: The destination.
        interests: What the visitor wants from the day.

    Returns:
        The combined goal.
    """
    return f"{city}: {interests}"


#: What the planner call costs, assumed by `/run` rather than accepted from the
#: client. A client that could set the starting count could reset its own
#: per-run ceiling; assuming the minimum is both ungameable and honest, since a
#: plan can only have come from at least one planner call. The real spend
#: protection is the per-call gate underneath, which no request body can reach.
PLANNER_CALL_COST = 1


class PlanRequest(BaseModel):
    """The goal a run is planned from."""

    city: str = Field(..., max_length=MAX_CITY_CHARS)
    interests: str = Field(..., max_length=MAX_INTERESTS_CHARS)


class RunRequest(PlanRequest):
    """The visitor's explicit go-ahead, carrying the plan they reviewed.

    The plan travels back through the client because the server stores nothing
    between the two requests -- the same trade the chained-calls retry path
    makes, and for the same privacy reason. Sending back the plan that was
    displayed is also what makes the go-ahead meaningful: re-planning here would
    execute a plan the visitor never saw.
    """

    plan: Plan


@router.post("/api/planning/plan")
async def plan(
    payload: PlanRequest,
    session: AsyncSession = Depends(get_db_session),
    moderator: Moderator = Depends(get_moderator),
) -> JSONResponse:
    """Produce a plan for the visitor to review. Executes nothing.

    Google-style docstring per project convention.

    Args:
        payload: The city and interests to plan around.
        session: An async DB session for usage/logging bookkeeping.
        moderator: The shared safety gate. This app offers no presets, so the
            city and the interests are both the visitor's own words and both
            are checked -- as one string, since a goal is only meaningful as
            the pair.

    Returns:
        200 with the validated plan, any trim note, and what it cost. Otherwise
        422 `invalid_goal`, or 503 carrying `usage_limit_reached` (an hourly
        budget is spent; it resets at the top of the hour and retrying cannot
        help immediately) or
        `plan_unavailable` (the planner failed, or produced an unusable plan
        twice). Those stay distinguishable because they are different operator
        problems.
    """
    gate = await text_gate.check_free_text(
        goal_text(payload.city, payload.interests),
        app_name=PLANNING_APP_NAME,
        session=session,
        moderator=moderator,
    )
    if not gate.allowed and gate.code is not None:
        return _error_body(
            text_gate.status_for(gate.code), gate.code, gate.message or ""
        )

    try:
        outcome = await service.create_plan(
            session, city=payload.city, interests=payload.interests
        )
    except InvalidGoalError as exc:
        return _error_body(422, exc.code, str(exc))
    except (UsageLimitReachedError, PlanUnavailableError) as exc:
        logger.error("planning_plan_failed", code=exc.code, error=str(exc))
        return _error_body(503, exc.code, str(exc))

    return JSONResponse(
        status_code=200,
        content={
            "plan": outcome.plan.model_dump(),
            "trimmed_note": outcome.trimmed_note,
            "replanned": outcome.replanned,
            "model": outcome.model,
            "calls_used": outcome.calls_used,
            "call_ceiling": MAX_MODEL_CALLS,
        },
    )


class RetrySynthesisRequest(RunRequest):
    """Re-compose the itinerary from research that already finished.

    Carries the step results back with it for the same reason the plan travels
    back on `/run`: the server keeps nothing between requests. Sending the
    results unchanged is also what makes the retry meaningful -- re-running the
    research would produce different findings, so the itinerary that finally
    arrived would not be the one the visitor's step results support.
    """

    results: list[StepResult]


@router.post("/api/planning/retry-synthesis")
async def retry_synthesis(
    payload: RetrySynthesisRequest,
    session: AsyncSession = Depends(get_db_session),
    moderator: Moderator = Depends(get_moderator),
) -> JSONResponse:
    """Re-run only the synthesis step, leaving the research alone.

    The capability's mitigation for a failed final step, and the reason it is a
    plain JSON endpoint rather than a stream: there is exactly one call to make
    and one object to return, so there is nothing to stream.

    It costs no run allowance -- the visitor already spent one on the research
    they are looking at -- though the model call itself is metered like any
    other.

    Args:
        payload: The goal, the executed plan, and the results it produced.
        session: An async DB session for usage/logging bookkeeping.

    Returns:
        200 with the composed itinerary, or 503 with `usage_limit_reached` or
        `plan_unavailable`.
    """
    gate = await text_gate.check_free_text(
        goal_text(payload.city, payload.interests),
        app_name=PLANNING_APP_NAME,
        session=session,
        moderator=moderator,
    )
    if not gate.allowed and gate.code is not None:
        return _error_body(
            text_gate.status_for(gate.code), gate.code, gate.message or ""
        )

    check = validator.check_plan(payload.plan)
    if not check.ok or check.plan is None:
        return _error_body(
            422,
            "invalid_plan",
            "That plan is not executable, so it cannot be re-composed.",
        )

    try:
        goal = service.goal_for(city=payload.city, interests=payload.interests)
        itinerary = await service.retry_synthesis(
            session, goal=goal, plan=check.plan, results=payload.results
        )
    except InvalidGoalError as exc:
        return _error_body(422, exc.code, str(exc))
    except (UsageLimitReachedError, PlanUnavailableError) as exc:
        logger.error("planning_retry_failed", code=exc.code, error=str(exc))
        return _error_body(503, exc.code, str(exc))

    return JSONResponse(status_code=200, content={"itinerary": itinerary.model_dump()})


@router.post("/api/planning/run")
async def run(
    payload: RunRequest,
    moderator: Moderator = Depends(get_stateless_moderator),
) -> EventSourceResponse:
    """Execute an approved plan, streaming each result as it lands.

    This request *is* the advance signal: no executor call exists anywhere that
    can fire without it.

    Note what is absent from the signature: there is no `Depends(get_db_session)`.
    A dependency's session is bound to the request scope, and this response
    outlives the handler -- the generator below runs while the body streams. The
    session is opened inside the generator so it lives exactly as long as the
    work using it, and closes when the stream ends however it ends.

    Args:
        payload: The goal and the plan the visitor reviewed.
        moderator: The shared safety gate. The **stateless** provider, for the
            same reason there is no `Depends(get_db_session)` here: a
            request-scoped dependency must not be bound to a response that
            outlives the handler. The cost is the `moderation_log` row, and
            `/plan` already recorded one for this goal.

    Returns:
        An SSE stream: one `plan` event, one `step_result` per step in plan
        order, then either an `itinerary` event or an `error` event. Failures
        arrive as events rather than as a broken stream, so results already
        produced stay on the visitor's screen.
    """
    return EventSourceResponse(_stream(payload, moderator))


async def _stream(
    payload: RunRequest, moderator: Moderator
) -> AsyncGenerator[ServerSentEvent, None]:
    """Drive the orchestrator and translate its events onto the wire.

    Args:
        payload: The validated request body.
        moderator: The safety gate to run over the goal.

    Yields:
        Server-sent events, in the order the run produces them.
    """
    gate = await text_gate.check_free_text(
        goal_text(payload.city, payload.interests),
        app_name=PLANNING_APP_NAME,
        moderator=moderator,
    )
    if not gate.allowed and gate.code is not None:
        # The goal was already checked at `/plan`, but this request carries its
        # own copy and is not obliged to match -- so it is checked again here
        # rather than trusted. A refusal is an event on a 200 stream, following
        # this endpoint's own convention: results already on screen stay there.
        logger.info("planning_run_refused", code=gate.code)
        yield _event("error", {"code": gate.code, "detail": gate.message})
        return

    check = validator.check_plan(payload.plan)
    if not check.ok or check.plan is None:
        # Client-supplied and therefore not trusted. A plan that fails the same
        # check that gated it on the way out did not come from `/plan`
        # unmodified.
        logger.warning("planning_run_rejected_plan", errors=len(check.errors))
        yield _event(
            "error",
            {
                "code": "invalid_plan",
                "message": (
                    "The submitted plan is not executable, so nothing was run. "
                    "Generate a new plan and try again."
                ),
                "details": check.errors,
            },
        )
        return

    effective = check.plan
    try:
        goal = service.goal_for(city=payload.city, interests=payload.interests)
    except InvalidGoalError as exc:
        yield _event("error", {"code": exc.code, "message": str(exc)})
        return

    # Echoed before anything executes, and it is the *effective* plan: if the
    # arriving plan needed trimming, the visitor must see what will actually run
    # rather than what they sent.
    yield _event(
        "plan",
        {
            "goal": effective.goal,
            "steps": [step.model_dump() for step in effective.steps],
            "trimmed_note": check.trimmed_note,
        },
    )

    completed = 0
    async with async_session_factory() as session:
        stream = service.execute_plan(
            session, goal=goal, plan=effective, calls_used=PLANNER_CALL_COST
        )
        try:
            async for item in stream:
                if item.kind == "step_result" and item.step_result is not None:
                    completed += 1
                    yield _event("step_result", item.step_result.model_dump())
                elif item.kind == "itinerary" and item.itinerary is not None:
                    yield _event("itinerary", item.itinerary.model_dump())
                else:
                    yield _event(
                        "error",
                        {
                            "code": item.code or "run_failed",
                            "message": item.notice or "The run could not be completed.",
                            "steps_completed": completed,
                        },
                    )
        except asyncio.CancelledError:
            # The visitor navigated away or aborted. sse-starlette cancels this
            # generator on disconnect; closing the orchestrator explicitly is
            # what stops the *next* model call from being made, which is the
            # whole reason to handle this rather than let it unwind.
            await stream.aclose()
            logger.info("planning_run_abandoned", steps_completed=completed)
            raise


def _event(name: str, payload: dict) -> ServerSentEvent:
    """Build one named SSE event with a JSON data payload.

    Args:
        name: The SSE event name the client dispatches on.
        payload: The JSON-serialisable body.

    Returns:
        The event, ready to yield.
    """
    return ServerSentEvent(event=name, data=json.dumps(payload))


def _error_body(status: int, code: str, detail: str) -> JSONResponse:
    """Build the error body shape the other example apps' routes return.

    Args:
        status: The HTTP status code.
        code: The machine-readable code the frontend branches on.
        detail: A human-readable explanation.

    Returns:
        A JSONResponse carrying all three.
    """
    return JSONResponse(
        status_code=status, content={"status": "error", "code": code, "detail": detail}
    )
