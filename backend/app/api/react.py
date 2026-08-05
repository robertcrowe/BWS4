# Built with Spec4 AI - https://spec4.ai
"""The ReAct loop app's HTTP surface: the presets, the run stream, the trace.

`GET /presets` serves the curated catalogue from module constants -- no model,
no database, no quota, nothing the visitor supplies. Served from the API rather
than duplicated in the frontend for the same reason as the orchestrated roster
and the collaboration identity cards: the question a run actually asks is
resolved server-side from these constants, so a frontend copy would be a second
source of truth free to drift from the one the loop uses. **It carries no
answer to any preset, because the catalogue holds none** -- see
`react/presets.py`.

`POST /run` streams the run, one envelope per event. It is a stream rather than
a JSON response because the whole point of the demonstration is watching the
loop decide: a thought, then an action, then the observation it produced, then
the next thought built on it. A response assembled at the end would show a
visitor the result of an interleaved loop with the interleaving removed.

`GET /run/{run_id}` reads one completed trace back whole. It is what the
client's stored run ids are for: there is no server-side visitor identity here,
so a visitor returning to the page re-fetches their trace by id rather than
being trusted to have cached it correctly.

**This router is thin on purpose.** The catalogue projection, the stream and
the persistence live in the slice service; what is here is the request body,
the event encoding, the session lifetime and the disconnect handling.

Like the planning, orchestrated and collaboration run endpoints, `/run`
deliberately does **not** use `Depends(get_db_session)`: a dependency's session
is bound to the request scope and this response outlives the handler, because
the generator is still running -- and still writing the run's row -- while the
body streams. The session is opened inside the generator instead.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncGenerator

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

# Imported from the package root rather than `sse_starlette.sse`: only the root
# declares these in `__all__`, and this module is type-checked strictly (unlike
# the pre-v6 routers, which inherit an exemption).
from sse_starlette import EventSourceResponse, ServerSentEvent

from backend.app.db.session import async_session_factory, get_db_session
from backend.app.react import service, suitability
from backend.app.react.presets import PRESET_QUESTIONS
from backend.app.react.schemas import (
    PresetsResponse,
    QuestionSuitability,
    RunRequest,
    TraceResponse,
)
from backend.app.services import text_gate
from backend.app.services.moderation import (
    Moderator,
    get_moderator,
    get_stateless_moderator,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/api/react", tags=["react"])

#: Seconds between keep-alive comments, matching `api/collab.py`. Render's
#: proxy closes an idle connection, and a cycle that is waiting on a model and
#: then on a search can run for tens of seconds with nothing to say.
PING_SECONDS = 15


@router.get("/presets")
async def get_presets() -> PresetsResponse:
    """Return the five curated multi-hop questions.

    Static and free: no model call, no quota, and nothing a visitor supplied.
    It answers on a deployment with no provider keys at all, which is what
    makes it safe to fetch on page load.

    Returns:
        The catalogue's questions and display metadata, and the run's
        server-fixed search-cycle budget. Never an answer to any of them.
    """
    return service.public_presets()


def _event(name: str, payload: dict[str, object]) -> ServerSentEvent:
    """Encode one envelope as a named SSE event.

    Args:
        name: The event name the client listens for.
        payload: JSON-serialisable body.

    Returns:
        The encoded event.
    """
    return ServerSentEvent(event=name, data=json.dumps(payload))


@router.post("/run")
async def run(
    payload: RunRequest,
    moderator: Moderator = Depends(get_stateless_moderator),
) -> EventSourceResponse:
    """Start a run and stream one envelope per event.

    A 200 with any refusal carried as an `error` event, following the
    convention the planning, orchestrated and collaboration apps set: a run
    that produced cycles and then stopped must not push the client's error
    branch and discard them.

    A free-form question passes the shared moderation gate first; a curated
    preset does not, because the gate recognises the app's own canonical text
    rather than accepting an id. `get_stateless_moderator` rather than the
    session-bound one, for the same reason planning's `/run` uses it: this
    response outlives its handler, so it must not hold a request-scoped
    session. The cost is one `moderation_log` row, which is the documented
    trade for a streaming route.

    Args:
        payload: The validated request body. Exactly one of
            `preset_question_id` and `visitor_question` is present.
        moderator: The shared safety gate.

    Returns:
        The event stream.
    """
    return EventSourceResponse(_run_stream(payload, moderator), ping=PING_SECONDS)


async def _run_stream(
    payload: RunRequest, moderator: Moderator
) -> AsyncGenerator[ServerSentEvent, None]:
    """Drive the run and put each envelope on the wire as it is produced.

    Args:
        payload: The validated request body.
        moderator: The shared safety gate, injected so a test can substitute it.

    Yields:
        One SSE event per envelope.
    """
    run_id = uuid.uuid4()
    delivered = 0

    # The shared gate, before anything is reserved or spent. A curated preset
    # never reaches it: `PRESET_QUESTIONS` is the server's own canonical text
    # and the gate byte-matches against it, so a preset id is never a claim that
    # buys a bypass. The gate costs no model allowance of its own, which is what
    # lets it run first.
    if payload.visitor_question is not None:
        # A session of its own, opened and closed before the stream begins. The
        # streaming rule forbids a *request-scoped* session here, not any
        # session -- and without one the gate's verdict would go unrecorded for
        # a client that starts a run without checking the question first.
        async with async_session_factory() as gate_session:
            gate = await text_gate.check_free_text(
                payload.visitor_question,
                app_name=service.REACT_APP_NAME,
                curated=PRESET_QUESTIONS,
                session=gate_session,
                moderator=moderator,
            )
        if not gate.allowed and gate.code is not None:
            yield _event(
                "error",
                {
                    "code": gate.code,
                    "message": gate.message or "",
                    "stub": False,
                },
            )
            logger.info("react_run_refused", run_id=str(run_id), reason=gate.code)
            return

    # Reused from the cache, never re-asked. The check already ran while the
    # visitor was typing; spending a second call to record the same verdict on
    # the run row would be paying twice for one answer. A cache miss records
    # nothing, which is correct -- the columns mean "this is what the check
    # said", not "a check was attempted".
    verdict = (
        suitability.cached(payload.visitor_question)
        if payload.visitor_question is not None
        else None
    )

    async with async_session_factory() as session:
        stream = service.stream_run(
            session, run_id=run_id, request=payload, suitability=verdict
        )
        try:
            async for event in stream:
                delivered += 1
                yield _event(event.name, event.payload)
        except asyncio.CancelledError:
            # Abandoning an `async for` does not close the inner generator, so
            # the loop would keep cycling against a stream nobody reads --
            # spending model and search quota on a run the visitor walked away
            # from, which matters most here because this is the gallery's most
            # expensive example per run. Closing it explicitly is what makes
            # the stop immediate, and it is what runs the generator's `finally`
            # so the run's unspent reservation is given back.
            await stream.aclose()
            logger.info("react_run_abandoned", run_id=str(run_id), events=delivered)
            raise

    logger.info("react_run_stream_closed", run_id=str(run_id), events=delivered)


class SuitabilityRequest(BaseModel):
    """Body of `POST /api/react/suitability`.

    Attributes:
        visitor_question: The visitor's own question. Presets never reach here.
        session_id: The browser session, for the per-session check cap.
    """

    visitor_question: str = Field(
        min_length=1, max_length=suitability.MAX_QUESTION_CHARS
    )
    session_id: str = Field(min_length=1, max_length=64)


class SuitabilityResponse(BaseModel):
    """Response body of `POST /api/react/suitability`.

    `verdict` is null for the neutral state, which is what every failure path
    resolves to. **The response is a 200 either way**: an advisory that could
    not be produced is not an error the visitor needs to see, and returning a
    5xx would push the client's error branch for a hint.

    Attributes:
        verdict: The assessment, or null when nothing could assess it.
        checks_remaining: How many checks this session may still spend, so the
            client can stop asking rather than discovering the cap.
    """

    verdict: QuestionSuitability | None
    checks_remaining: int


@router.post("/suitability")
async def check_suitability(
    payload: SuitabilityRequest,
    moderator: Moderator = Depends(get_moderator),
) -> SuitabilityResponse:
    """Advise whether a free-form question will exercise the loop.

    **This never blocks a run, and it never spends the visitor's two-run
    allowance.** It costs one call against the shared framework cap and nothing
    else; a refusal, a timeout or an exhausted chain all resolve to a null
    verdict the UI renders as a soft note.

    The moderation gate still applies: a question refused here is refused, and
    the refusal is reported as the same status the rest of the gallery uses so
    a visitor meets one treatment rather than six. Unlike `/run`, this is an
    ordinary request-scoped route, so it takes the **session-bound** moderator
    and the verdict lands in `moderation_log` -- a salted hash, the category and
    the latency, and never the question.

    Args:
        payload: The question and the session id.
        moderator: The shared safety gate.

    Returns:
        The verdict or the neutral state, plus the session's remaining checks.

    Raises:
        HTTPException: 422 when the question was refused, 503 when nothing
            could examine it. The two must stay distinguishable: one the
            visitor fixes by rewording, the other they cannot fix at all.
    """
    gate = await text_gate.check_free_text(
        payload.visitor_question,
        app_name=service.REACT_APP_NAME,
        curated=PRESET_QUESTIONS,
        moderator=moderator,
    )
    if not gate.allowed and gate.code is not None:
        raise HTTPException(
            status_code=text_gate.status_for(gate.code),
            detail=gate.message or "",
        )

    verdict = await suitability.assess(
        payload.visitor_question, session_id=payload.session_id
    )
    return SuitabilityResponse(
        verdict=verdict,
        checks_remaining=suitability.checks_remaining(payload.session_id),
    )


@router.get("/run/{run_id}")
async def get_run(
    run_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> TraceResponse:
    """Return one completed run's trace, whole.

    A request-scoped session is correct here, unlike on `/run`: this response
    is assembled and returned before the handler exits.

    Args:
        run_id: The run's id, as a UUID string.
        session: The request-scoped database session.

    Returns:
        The stored trace.

    Raises:
        HTTPException: 404 when no run carries that id, including when the id
            is not a well-formed UUID -- an unparseable id names no run, which
            is the same answer.
    """
    try:
        parsed = uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="No such run.") from None

    trace = await service.load_run(session, parsed)
    if trace is None:
        raise HTTPException(status_code=404, detail="No such run.")
    return trace
