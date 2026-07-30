# Built with Spec4 AI - https://spec4.ai
"""Thin FastAPI handlers for the chained_calls_example_app, mirroring api/single_call.py.

A chain whose second call failed is returned as **200** with
`status: "critique_failed"`, not as an error. Call 1 succeeded and its output is
in the body -- which is exactly what the capability's escalation path requires
be shown -- and a 4xx/5xx would push the client's error branch and discard it.
Only a failure that leaves *nothing* to show (call 1 itself, or a cap that
cannot cover the chain) is an error status.
"""

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.chained_calls import service
from backend.app.chained_calls.pipeline import (
    CHAIN_LENGTH,
    ROLE_CRITIC,
    ROLE_WRITER,
    StoryDraft,
)
from backend.app.chained_calls.schemas import (
    ChainedCallsRequest,
    ChainedCallsResponse,
    ChainPlanResponse,
    ChainStep,
    FinalOutput,
    IntermediateOutput,
    QualitySignal,
    RetryCritiqueRequest,
)
from backend.app.chained_calls.service import (
    ChainOutcome,
    GenerationUnavailableError,
    InvalidStoryPromptError,
    UsageLimitReachedError,
)
from backend.app.db.session import get_db_session

logger = structlog.get_logger()

router = APIRouter()

#: The chain, described before it runs. Served from the same constants the
#: pipeline uses, so the roles a visitor is promised and the roles that actually
#: execute cannot drift apart.
_PLAN = ChainPlanResponse(
    steps=[
        ChainStep(
            position=1,
            role=ROLE_WRITER,
            label="Struggling Writer",
            description=(
                "Takes your story idea and drafts a short story in a self-doubting, "
                "hedging voice. Its output is the only thing the second call sees."
            ),
        ),
        ChainStep(
            position=2,
            role=ROLE_CRITIC,
            label="Harsh Critic",
            description=(
                "Receives that exact draft as its input and critiques it bluntly, "
                "quoting a specific detail from it."
            ),
        ),
    ],
    chain_length=CHAIN_LENGTH,
    length_note=(
        f"This demo runs exactly {CHAIN_LENGTH} chained calls per submission to "
        "conserve a shared free-tier budget. The pattern itself supports chains of "
        "any length -- two is this demo's budget, not the pattern's limit."
    ),
)


@router.get("/api/chained-calls/plan")
async def get_plan() -> JSONResponse:
    """Describe both calls before any of them run.

    Touches no database and calls no model. Exists so the feature's criterion
    that the visitor is told each call's role *before* submitting is served
    from the same constants the pipeline runs on, rather than from frontend
    copy kept in sync by hand.

    Google-style docstring per project convention.

    Returns:
        A 200 JSON response describing each step, the fixed chain length, and
        why the length is fixed.
    """
    return JSONResponse(status_code=200, content=_PLAN.model_dump())


@router.post("/api/chained-calls/generate")
async def generate(
    payload: ChainedCallsRequest,
    session: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    """Run the two-call chain over a story idea.

    Google-style docstring per project convention.

    Args:
        payload: The visitor's story idea.
        session: An async DB session injected per-request, used for the shared
            usage-limit and request-logging bookkeeping.

    Returns:
        A 200 JSON response carrying both labeled output blocks -- or, when the
        critic call failed, the intermediate block with
        `status: "critique_failed"` and a notice. Otherwise a 422 for an
        unusable story idea, or a 503 carrying a machine-readable `code`:
        `usage_limit_reached` (the cap cannot cover both calls; resets at 00:00
        UTC) or `generation_unavailable` (call 1 failed, so there is no chain).
        Those two are reported separately because they are different operator
        problems.
    """
    try:
        outcome = await service.run_chain(session, story_prompt=payload.story_prompt)
    except InvalidStoryPromptError as exc:
        return _error(422, exc.code, str(exc))
    except (UsageLimitReachedError, GenerationUnavailableError) as exc:
        logger.error("chained_calls_failed", code=exc.code, error=str(exc))
        return _error(503, exc.code, str(exc))

    return JSONResponse(status_code=200, content=_body(outcome).model_dump())


@router.post("/api/chained-calls/retry-critique")
async def retry_critique(
    payload: RetryCritiqueRequest,
    session: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    """Re-run only the critic call against a story that already exists.

    The capability's mitigation for a failed second call. Regenerating the
    story would spend a unit reproducing something the visitor is already
    reading, and would produce a *different* story -- so the critique they
    finally get would not be a critique of the draft on their screen.

    Args:
        payload: The intermediate output from an earlier run.
        session: An async DB session for usage/logging bookkeeping.

    Returns:
        A 200 JSON response in the same shape as `generate`. Otherwise a 422
        for a blank or over-long story, or a 503 with `usage_limit_reached`.
    """
    story = payload.intermediate_output.text.strip()
    if not story:
        return _error(
            422, "invalid_intermediate_output", "There is no story text to critique."
        )
    if len(story) > service.MAX_STORY_CHARS:
        return _error(
            422,
            "invalid_intermediate_output",
            f"That story is {len(story)} characters -- the limit is "
            f"{service.MAX_STORY_CHARS}.",
        )

    draft = StoryDraft(title=payload.intermediate_output.title, story=story)

    try:
        outcome = await service.run_critique_only(session, draft=draft)
    except UsageLimitReachedError as exc:
        logger.error("chained_calls_failed", code=exc.code, error=str(exc))
        return _error(503, exc.code, str(exc))

    return JSONResponse(status_code=200, content=_body(outcome).model_dump())


def _body(outcome: ChainOutcome) -> ChainedCallsResponse:
    """Map a service outcome onto the wire response.

    Args:
        outcome: The chain's result, complete or partial.

    Returns:
        The response body, with each block's `role` stamped by its schema
        default rather than carried up from the model.
    """
    final = None
    if outcome.critique is not None:
        final = FinalOutput(
            text=outcome.critique.critique,
            quoted_detail=outcome.critique.quoted_detail,
        )

    signal = None
    if outcome.signal is not None:
        signal = QualitySignal(**vars(outcome.signal))

    return ChainedCallsResponse(
        status=outcome.status,
        intermediate_output=IntermediateOutput(
            title=outcome.draft.title, text=outcome.draft.story
        ),
        final_output=final,
        quality_signal=signal,
        notice=outcome.notice,
        writer_model=outcome.writer_model,
        critic_model=outcome.critic_model,
    )


def _error(status: int, code: str, detail: str) -> JSONResponse:
    """Build the error body shape every route in this app returns.

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
