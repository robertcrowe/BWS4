# Built with Spec4 AI - https://spec4.ai
"""The Router app's HTTP surface.

`GET /history` reads the shared agreement and latency histories.

`POST /rerun` re-runs a misrouted preset once through its expected route.

`POST /run` admits a run (moderation for free text, then a two-unit hold) and
streams its stages; a refusal is an ordinary HTTP error before any stream.

`GET /presets` serves the curated catalogue, the fixed decision settings and
the four generated route descriptions -- no model, no quota, nothing the
visitor supplies. Served from the API rather than duplicated in the frontend
for the same reason as the ReAct presets: the request a run actually routes is
resolved server-side from these constants, so a frontend copy would be a
second source of truth free to drift.

If the route descriptions could not be generated (the database was unreachable
at boot), the endpoint still answers 200 but with `available: false`, no route
descriptions and a null block, rather than serving a retrieval line with an
invented subject list.

`POST /retry` re-attempts the route-description warm-up after such a failure.
It never touches the usage allowance. While the Router is unavailable, `/run`
and `/rerun` refuse before moderation and before any hold.

**This router is thin on purpose.** The catalogue projection lives in the
slice; what is here is the HTTP binding.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncGenerator

import structlog
from fastapi import APIRouter, Depends, HTTPException

# Imported from the package root: only the root declares these in `__all__`.
from sse_starlette import EventSourceResponse, ServerSentEvent

from backend.app.db.session import async_session_factory
from backend.app.router import history, service
from backend.app.router.run_schemas import RerunRequest, RunRefusal, RunRequest
from backend.app.router.schemas import (
    HistoryResponse,
    PresetsResponse,
    RetryResponse,
    public_history,
    public_presets,
)
from backend.app.router.state import get_route_descriptions, warm_route_descriptions
from backend.app.services.moderation import Moderator, get_stateless_moderator

logger = structlog.get_logger()

router = APIRouter(prefix="/api/router", tags=["router"])

#: The 503 message when a retry could not prepare the route descriptions.
DESCRIPTIONS_NOT_READY = (
    "The Router is temporarily unavailable: its route descriptions could not be "
    "prepared because the indexed document titles could not be read. Try again "
    "shortly."
)


@router.get("/presets")
async def get_presets() -> PresetsResponse:
    """Return availability, the presets, decision settings and route descriptions.

    Free: no model call, no quota and no database read -- it only looks at the
    in-process holder. It never retries a failed warm-up; `POST /retry` does.

    Returns:
        Whether the Router is available; each preset's id, request text,
        expected route and reason; the decision margin and cost order; and the
        four route descriptions with the exact block the router receives and its
        SHA-256 (empty and null while unavailable). Never an answer.
    """
    return public_presets(get_route_descriptions())


@router.post("/retry")
async def retry() -> RetryResponse:
    """Re-attempt the route-description warm-up, without a restart.

    Reads the indexed document titles and, on success, fills the in-process
    holder so the Router is available again. Free: no model call, and it never
    reserves usage or touches the allowance tables. Already available is a
    success that reads nothing.

    Returns:
        `available: true`.

    Raises:
        HTTPException: 503 `descriptions_not_ready` when the warm-up fails
            again; the Router stays unavailable.
    """
    try:
        await warm_route_descriptions()
    except Exception:  # noqa: BLE001 - reported to the visitor as still unavailable
        logger.exception("router_retry_failed")
        raise HTTPException(
            status_code=503,
            detail=RunRefusal(
                code=service.CODE_NOT_READY, message=DESCRIPTIONS_NOT_READY
            ).model_dump(),
        ) from None
    logger.info("router_retry_succeeded")
    return RetryResponse(available=True)


#: The 503 detail when the shared histories cannot be read.
HISTORY_UNAVAILABLE = (
    "The Router's agreement and latency history could not be read just now. "
    "Nothing is shown rather than invented figures."
)


@router.get("/history")
async def get_history() -> HistoryResponse:
    """Return the shared agreement history and the typical search-route time.

    Per-preset agreed, disagreed and declined counts with a rate only from five
    observations; the overall rate; and the rolling median of real search-route
    runs with its sample size. Computed in SQL from the two append-only tables,
    so it survives restarts and redeploys.

    Opens its own session, like the run stream, so no route in this module
    takes a request-scoped one.

    Returns:
        The history.

    Raises:
        HTTPException: 503 when the history cannot be read.
    """
    try:
        async with async_session_factory() as session:
            snapshot = await history.read_history(session)
    except Exception:  # noqa: BLE001 - reported candidly as unavailable
        logger.exception("router_history_read_failed")
        raise HTTPException(status_code=503, detail=HISTORY_UNAVAILABLE) from None
    return public_history(snapshot)


#: Seconds between keep-alive comments, matching the other streaming apps.
PING_SECONDS = 15


def _event(event: service.StreamEvent) -> ServerSentEvent:
    """Encode one envelope as a named SSE event.

    Args:
        event: The event.

    Returns:
        The encoded event.
    """
    return ServerSentEvent(event=event.name, data=json.dumps(event.payload))


@router.post("/run")
async def run(
    payload: RunRequest,
    moderator: Moderator = Depends(get_stateless_moderator),
) -> EventSourceResponse:
    """Admit a run, then stream its stages.

    Admission -- the availability check, moderation for free text, then the
    two-unit hold -- happens here, before any response starts, so a refusal is
    an ordinary HTTP error with a `{code, message}` detail: no stream, no run,
    no hold. Only an admitted run streams.

    `get_stateless_moderator` because the gate opens its own session; the
    stream opens its own too. Neither uses `Depends(get_db_session)`, whose
    session would close while the stream is still running.

    Args:
        payload: The validated request body.
        moderator: The shared safety gate.

    Returns:
        The event stream.

    Raises:
        HTTPException: 422 moderation blocked / preset mismatch, 503
            moderation unavailable / descriptions not ready, 429 shared cap.
    """
    try:
        admitted = await service.admit(payload, moderator)
    except service.RunRefusedError as refusal:
        raise HTTPException(
            status_code=refusal.status,
            detail=RunRefusal(code=refusal.code, message=refusal.message).model_dump(),
        ) from None
    return EventSourceResponse(_run_stream(admitted), ping=PING_SECONDS)


@router.post("/rerun")
async def rerun(payload: RerunRequest) -> EventSourceResponse:
    """Re-run a misrouted preset once through its expected route.

    The router does not run. Eligibility is recomputed server-side from the
    preset catalogue and the ticket recorded when the original run ended; an
    ineligible, unknown or repeated re-run, or one the shared cap cannot
    cover, is refused with an ordinary HTTP error before anything is held.

    Args:
        payload: The preset id and the original run's id.

    Returns:
        The event stream.

    Raises:
        HTTPException: 503 descriptions not ready (checked first), 404 unknown
            or expired run, 409 already re-run, 422 ineligible or mismatched,
            429 shared cap.
    """
    try:
        admitted = await service.admit_rerun(payload)
    except service.RunRefusedError as refusal:
        raise HTTPException(
            status_code=refusal.status,
            detail=RunRefusal(code=refusal.code, message=refusal.message).model_dump(),
        ) from None
    return EventSourceResponse(
        _stream(service.stream_rerun(admitted), admitted.run_id), ping=PING_SECONDS
    )


async def _run_stream(
    admitted: service.AdmittedRun,
) -> AsyncGenerator[ServerSentEvent, None]:
    """Put each envelope on the wire as it is produced; stop on disconnect.

    Args:
        admitted: The admitted run.

    Yields:
        One SSE event per envelope.
    """
    async for event in _stream(service.stream_run(admitted), admitted.run_id):
        yield event


async def _stream(
    stream: AsyncGenerator[service.StreamEvent, None], run_id: uuid.UUID
) -> AsyncGenerator[ServerSentEvent, None]:
    """Put each envelope on the wire as it is produced; stop on disconnect.

    Args:
        stream: The service's event stream.
        run_id: The run, for logs.

    Yields:
        One SSE event per envelope.
    """
    delivered = 0
    try:
        async for event in stream:
            delivered += 1
            yield _event(event)
    except asyncio.CancelledError:
        # Abandoning an `async for` does not close the inner generator; closing
        # it explicitly stops spending and runs its settle.
        await stream.aclose()
        logger.info("router_run_abandoned", run_id=str(run_id), events=delivered)
        raise
    logger.info("router_run_stream_closed", run_id=str(run_id), events=delivered)
