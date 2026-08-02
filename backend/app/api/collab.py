# Built with Spec4 AI - https://spec4.ai
"""The multi-agent collaboration app's HTTP surface.

Two endpoints. `GET /identity-cards` serves the three A2A-shaped cards
from module constants -- no model, no database, no quota, and nothing a visitor
supplies. It is the analogue of the orchestrated app's `/roster`, and it is
served from the API for the same reason: the cards are what the run is
validated against server-side, so a frontend copy would be a second source of
truth free to drift from the one the negotiation actually uses.

Serialisation is by alias, so the response carries A2A's own camelCase spelling
(`protocolVersion`, `toolAccess`, `defaultInputModes`). That is asserted in the
endpoint's test rather than trusted to configuration -- an alias generator that
silently stopped applying would still return a perfectly valid-looking body.

`POST /run` streams the negotiation, one event per stage. It is a stream rather
than a JSON response because the two bidding stages are concurrent and take
seconds each: the point of the demonstration is that both seller columns are
visibly in progress together, and a response assembled at the end would show a
visitor the result of parallelism without the parallelism.

**This router is thin on purpose.** Every decision -- validation, the hourly
gate, the allowance hold, the six stages, the post-checks, persistence -- lives
in the slice service. What is here is the request body, the event encoding, and
the disconnect handling.

Like the planning and orchestrated run endpoints, `/run` deliberately does not
use `Depends(get_db_session)`: a dependency's session is bound to the request
scope and this response outlives the handler, because the generator runs while
the body streams. The session is opened inside the generator instead.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncGenerator
from typing import Any

import structlog
from fastapi import APIRouter
from pydantic import BaseModel, Field

# Imported from the package root rather than `sse_starlette.sse`: only the
# root declares these in `__all__`, and this module is type-checked strictly
# (unlike the pre-v6 routers, which inherit an exemption).
from sse_starlette import EventSourceResponse, ServerSentEvent

from backend.app.collab.protocol import AgentCard
from backend.app.collab.scenarios import IDENTITY_CARDS
from backend.app.collab.service import stream_run
from backend.app.db.session import async_session_factory

logger = structlog.get_logger()

router = APIRouter(prefix="/api/collab", tags=["collab"])

#: Seconds between keep-alive comments. Render's proxy closes an idle
#: connection, and a bidding stage against a free model can run for tens of
#: seconds with nothing to say.
PING_SECONDS = 15


class IdentityCard(BaseModel):
    """One agent's published card, with what the bus and the UI need alongside it.

    `id`, `role` and `color` are this app's, not A2A's -- an `AgentCard`
    describes an agent rather than addressing one. Keeping them beside the card
    rather than inside it is what lets `protocol.py` stay a faithful statement
    of the protocol's shape.

    Attributes:
        id: The agent's address on the message bus.
        role: `buyer` or `seller`.
        color: Accent for this agent's track.
        card: What the peer publishes about itself.
    """

    id: str
    role: str
    color: str
    card: AgentCard


class IdentityCardsResponse(BaseModel):
    """Response body of `GET /api/collab/identity-cards`.

    Attributes:
        agents: The three participants, buyer first.
    """

    agents: list[IdentityCard]


@router.get("/identity-cards", response_model_by_alias=True)
async def get_identity_cards() -> IdentityCardsResponse:
    """Return the three peer identity cards for inspection.

    Static and free: this is what each party publishes about itself, readable
    before a run starts and while one is in flight. Private negotiating
    positions are not here and are not derivable from what is -- a card is the
    public face, and the sealed constraints stay sealed until the run ends.

    Returns:
        The buyer and both rival sellers, each with its A2A-shaped card.
    """
    return IdentityCardsResponse(
        agents=[
            IdentityCard(
                id=agent.id,
                role=agent.role,
                color=agent.color,
                card=agent.card,
            )
            for agent in IDENTITY_CARDS
        ]
    )


class RunRequest(BaseModel):
    """Body of `POST /api/collab/run`.

    Both fields are closed sets: a scenario id from the catalogue and either a
    preset weighting id or an explicit numeric vector. **No free text reaches
    this app at all**, which is why it needs no moderation gate -- the one
    example in the showcase that genuinely does not.

    Attributes:
        scenario_id: The scenario the visitor chose.
        weighting_id: A preset weighting id.
        weights: An explicit per-axis vector, when not using a preset.
    """

    scenario_id: str = Field(min_length=1, max_length=64)
    weighting_id: str | None = Field(default=None, max_length=64)
    weights: dict[str, int] | None = None


def _event(name: str, payload: dict[str, Any]) -> ServerSentEvent:
    """Encode one stage event as a named SSE event.

    Args:
        name: The event name the client listens for.
        payload: JSON-serialisable body.

    Returns:
        The encoded event.
    """
    return ServerSentEvent(event=name, data=json.dumps(payload))


@router.post("/run")
async def run(payload: RunRequest) -> EventSourceResponse:
    """Start a negotiation and stream one event per stage.

    A 200 with the refusal carried as an `error` event, following the
    convention the planning and orchestrated apps set: a run that produced
    stages and then stopped must not push the client's error branch and
    discard them. A refusal before stage 1 yields exactly one error event and
    nothing else, so a capped run never leaves a partial record.

    Args:
        payload: The validated request body.

    Returns:
        The event stream.
    """
    return EventSourceResponse(_run_stream(payload), ping=PING_SECONDS)


async def _run_stream(payload: RunRequest) -> AsyncGenerator[ServerSentEvent, None]:
    """Drive the run and put each stage on the wire as it completes.

    Args:
        payload: The validated request body.

    Yields:
        One SSE event per stage.
    """
    run_id = f"collab-{uuid.uuid4().hex[:16]}"
    delivered = 0

    async with async_session_factory() as session:
        stream = stream_run(
            session,
            run_id=run_id,
            scenario_id=payload.scenario_id,
            weighting_id=payload.weighting_id,
            weights=payload.weights,
        )
        try:
            async for event in stream:
                delivered += 1
                yield _event(event.kind, {"stage": event.stage, **event.payload})
        except asyncio.CancelledError:
            # Abandoning an `async for` does not close the inner generator, so
            # the sellers would keep bidding against a stream nobody reads --
            # spending quota on a run the visitor walked away from. Closing it
            # explicitly is what makes the stop immediate.
            await stream.aclose()
            logger.info("collab_run_abandoned", run_id=run_id, events=delivered)
            raise

    logger.info("collab_run_stream_closed", run_id=run_id, events=delivered)
