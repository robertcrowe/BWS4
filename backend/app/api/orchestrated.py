# Built with Spec4 AI - https://spec4.ai
"""The orchestrated-subagents app's HTTP surface: the roster, and the run stream.

`GET /roster` serves two module constants -- no model, no database, no quota.
Serving it from the API rather than duplicating it in the frontend is what keeps
one list authoritative: the coordinator's decision is validated against exactly
these ids, so a frontend copy that drifted would offer a visitor a specialist
the server would refuse.

`POST /run` starts a run and streams the coordinator's delegation decision.
`POST /dispatch` is the visitor's go-ahead and streams both specialists' columns
as they fill. **They are two requests because the human decision between them is
the pattern** -- a flag on the first would have a default, and a default would
let a delegation nobody read dispatch itself. The merge event arrives in a later
phase behind the same stream.

**The decision is streamed rather than returned**, even though it is currently
the only event. That is not ceremony: the capability requires every intermediate
step be visible rather than withheld until the run completes, and a JSON
response now would have to become a stream later -- changing the client contract
at exactly the point the run gets long enough for the difference to matter.

The response is a 200 with the refusal carried as an event, following the
convention the planning app set: a run that produced something and then stopped
must not push the client's error branch and discard it. Refusals here carry a
machine-readable `outcome`, because "your question was refused", "nothing could
check your question", "the showcase is busy" and "the coordinator broke" each
call for different copy -- reword, retry, wait, retry.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator

import structlog
from fastapi import APIRouter
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse, ServerSentEvent

from backend.app.db.session import async_session_factory
from backend.app.orchestrated.presets import public_presets
from backend.app.orchestrated.roster import public_roster
from backend.app.orchestrated.runtime import VISITOR_FACING_CALL_COUNT
from backend.app.orchestrated.schemas import DelegationDecision, RosterResponse
from backend.app.orchestrated.service import begin_run, confirm_dispatch
from backend.app.services.moderation import Moderator, moderate

logger = structlog.get_logger()

router = APIRouter()

#: Longest question accepted. Matches the moderation service's own default cap,
#: so an over-long question is refused at the schema rather than after a call.
MAX_QUESTION_CHARS = 500


class RunRequest(BaseModel):
    """A question, and the preset it claims to have come from.

    `preset_id` is a *claim*, not a credential: `service.find_preset()` verifies
    it byte-matches a curated question before letting it skip moderation.
    """

    question: str = Field(..., max_length=MAX_QUESTION_CHARS)
    preset_id: str | None = None


@router.get("/api/orchestrated/roster")
async def roster() -> RosterResponse:
    """Return the fixed specialist roster and the curated preset questions.

    Both are static module constants, so this needs no warm-up and cannot fail
    for a reason worth reporting -- which is why it is a plain typed return
    rather than the `JSONResponse` the quota-spending routes in this package
    use to carry error codes.

    Returns:
        The four specialists and the curated presets.
    """
    return RosterResponse(specialists=public_roster(), presets=public_presets())


def _event(name: str, payload: dict) -> ServerSentEvent:
    """Build one named SSE event with a JSON data payload.

    Args:
        name: The event name the client dispatches on.
        payload: The JSON-serialisable body.

    Returns:
        The event, ready to yield.
    """
    return ServerSentEvent(event=name, data=json.dumps(payload))


@router.post("/api/orchestrated/run")
async def run(payload: RunRequest) -> EventSourceResponse:
    """Start a run and stream its delegation decision.

    In this phase the stream is one `delegation` event -- or one `error` event --
    and then closes. **No specialist request is issued here**: dispatch waits on
    the visitor's explicit confirmation, which arrives as a separate request in a
    later phase.

    There is no `Depends(get_db_session)` on the signature, for the reason the
    planning app's run endpoint documents: a dependency's session is bound to
    the request scope, and this response outlives the handler.

    Args:
        payload: The question and any claimed preset id.

    Returns:
        An SSE stream carrying either a `delegation` event or an `error` event
        with a machine-readable `outcome`.
    """
    return EventSourceResponse(_stream(payload, moderate))


async def _stream(
    payload: RunRequest, moderator: Moderator
) -> AsyncGenerator[ServerSentEvent, None]:
    """Drive the delegation phase and translate its outcome onto the wire.

    Args:
        payload: The validated request body.
        moderator: The moderation gate to use.

    Yields:
        One event, then the stream closes.
    """
    completed = False
    async with async_session_factory() as session:
        try:
            outcome = await begin_run(
                session,
                question=payload.question,
                preset_id=payload.preset_id,
                moderate=moderator,
            )
        except asyncio.CancelledError:
            # The visitor navigated away before the coordinator answered.
            # Nothing further is dispatched; the hold, if one was taken, is
            # swept by the expiry sweep rather than left claiming budget.
            logger.info("orchestrated_run_abandoned", phase="delegation")
            raise

        if outcome.ready and outcome.decision is not None:
            completed = True
            yield _event(
                "delegation",
                {
                    "decision_id": outcome.decision_id,
                    "chosen_specialists": [
                        specialist.value
                        for specialist in outcome.decision.chosen_specialists
                    ],
                    "rationale": outcome.decision.rationale,
                    "briefs": [
                        {
                            "specialist_id": brief.specialist_id.value,
                            "instruction": brief.instruction,
                        }
                        for brief in outcome.decision.briefs
                    ],
                    "fit_quality": outcome.decision.fit_quality.value,
                    "model_call_count": VISITOR_FACING_CALL_COUNT,
                },
            )
        else:
            yield _event(
                "error",
                {
                    "outcome": outcome.outcome.value,
                    "message": outcome.visitor_message
                    or "The run could not be started.",
                    "decision_id": outcome.decision_id,
                },
            )

    logger.info(
        "orchestrated_run_stream_closed",
        phase="delegation",
        delivered="delegation" if completed else "error",
    )


class DispatchRequest(BaseModel):
    """The visitor's explicit go-ahead to run the two chosen specialists.

    The decision travels back rather than being looked up, because nothing
    stores it: only the *hold* is persisted, keyed by `decision_id`. That makes
    this body client-controlled input, so `service.revalidate_posted_decision`
    re-checks its structure and bounds its briefs before any of it reaches a
    model -- the same treatment the planning app's run endpoint gives a posted
    plan.
    """

    decision_id: str = Field(..., min_length=1, max_length=64)
    decision: DelegationDecision
    question: str = Field(..., max_length=MAX_QUESTION_CHARS)


@router.post("/api/orchestrated/dispatch")
async def dispatch(payload: DispatchRequest) -> EventSourceResponse:
    """Run the two chosen specialists side by side and stream both columns.

    **A separate request from `/run`, and that is the human-in-the-loop gate.**
    There is no flag on the delegation call that could default to true and no
    effect that could fire on its own: dispatching requires someone to have read
    the decision and asked for it.

    Per-specialist events are emitted independently and immediately -- a status
    as each branch starts, an answer as each settles -- so a fast specialist's
    column fills while the slow one is still working, rather than both appearing
    together at the slower one's pace.

    Args:
        payload: The decision id, the decision as shown, and the question.

    Returns:
        An SSE stream of `specialist_status`, `specialist_answer` and finally
        `fan_out_complete` or `error`.
    """
    return EventSourceResponse(_dispatch_stream(payload))


async def _dispatch_stream(
    payload: DispatchRequest,
) -> AsyncGenerator[ServerSentEvent, None]:
    """Drive the fan-out and put each event on the wire as it arrives.

    Args:
        payload: The validated request body.

    Yields:
        Each dispatch event, in the order the single writer produced them.
    """
    delivered = 0
    async with async_session_factory() as session:
        stream = confirm_dispatch(
            session,
            decision_id=payload.decision_id,
            decision=payload.decision,
            question=payload.question,
        )
        try:
            async for event in stream:
                delivered += 1
                yield _event(event.name, event.payload)
        except asyncio.CancelledError:
            # Abandoning an `async for` does not close the inner generator, so
            # the specialists would keep running against a stream nobody reads.
            # Closing it explicitly is what makes the stop immediate.
            await stream.aclose()
            logger.info("orchestrated_run_abandoned", phase="dispatch")
            raise

    logger.info("orchestrated_run_stream_closed", phase="dispatch", events=delivered)
