# Built with Spec4 AI - https://spec4.ai
"""The chain itself: reserve for both calls, write, critique, report.

`pipeline.py` holds this app's personas and typed output shapes;
`services/agent_runtime.py` beneath it holds the machinery that runs a typed
call against a cross-provider fallback chain. This module knows the thing
neither of them does: that there are exactly two calls, in one order, and that
the second one's input is the first one's output. Keeping that split means the
interesting line -- where call 1's draft becomes call 2's user message -- is a
single readable statement here rather than something buried in framework
configuration.

**Nothing a visitor writes, and nothing a model writes for them, is stored.**
This app deliberately does *not* call `shared.record_generation_request()`,
which every other example app does: that function persists a prompt excerpt and
a response excerpt to `language_generation_requests`, and the capability's
privacy section forbids keeping the story prompt or the generated story and
critique beyond the request. Usage is still reserved and still logged -- the
`ServiceLogEntry` summaries carry the role, the model, and lengths, and no
authored text at all. Unlogged is not unmetered.

**Both units are reserved before the first call.** The capability's named
failure is the shared cap running out *between* the two calls, leaving a story
with no critique and a visitor with a half-demonstration of a pattern whose
whole point is the hand-off. So the reservation is for the full chain, checked
once, before anything runs -- and a chain that cannot be finished is refused
outright instead of started.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.chained_calls import overlap
from backend.app.chained_calls.overlap import OverlapSignal
from backend.app.chained_calls.pipeline import (
    CHAIN_LENGTH,
    CRITIC_INPUT_TEMPLATE,
    CRITIC_PROMPT_VERSION,
    ROLE_CRITIC,
    ROLE_WRITER,
    WRITER_PROMPT_VERSION,
    AgentLaneError,
    StoryCritique,
    StoryDraft,
    run_step,
)
from backend.app.services import shared

logger = structlog.get_logger()

#: Tag on every shared_framework_services invocation this app makes. Matches
#: the directory entry's display name so the cross-app log reads the same as
#: the landing page.
CHAINED_CALLS_APP_NAME = "Chained-Calls Example App"

#: Longest story idea accepted. A short bound is right here: the input is one
#: sentence of premise, and a longer one is a pasted document spending a shared
#: token budget on a chain that will spend it twice over.
MAX_STORY_PROMPT_CHARS = 600

#: Longest story accepted back on the retry path. Larger than a draft this
#: chain produces, small enough that the endpoint is not a general-purpose way
#: to push arbitrary text at the provider.
MAX_STORY_CHARS = 6000

#: The chain finished both calls.
STATUS_COMPLETE = "complete"
#: Call 1 succeeded and call 2 did not. The intermediate output is still
#: returned, per the capability's escalation path -- showing what was generated
#: beats discarding it because a later step failed.
STATUS_CRITIQUE_FAILED = "critique_failed"

_CRITIQUE_FAILED_NOTICE = (
    "The story was written, but the critic call did not complete. The draft "
    "below is unchanged -- retrying sends only the second call, so the story is "
    "not regenerated."
)


class ChainedCallsError(Exception):
    """Base class for chained-calls failures, carrying a machine-readable code."""

    code = "chained_calls_failed"


class InvalidStoryPromptError(ChainedCallsError):
    """Raised when the submitted story idea is blank or over-long."""

    code = "invalid_story_prompt"


class UsageLimitReachedError(ChainedCallsError):
    """Raised when the shared generation cap cannot cover the whole chain.

    Distinct from GenerationUnavailableError for the same reason as in the
    single-call app: a spent cap resets at 00:00 UTC and an unreachable
    provider does not, and an operator told only "503" learns neither.
    """

    code = "usage_limit_reached"


class GenerationUnavailableError(ChainedCallsError):
    """Raised when call 1 failed, so there is no chain to show at all.

    Only the *writer* failing maps here. A failed critic is not an error
    response: it is a partial result with a status, because the intermediate
    output is exactly what the visitor came to see.
    """

    code = "generation_unavailable"


@dataclass(frozen=True)
class ChainOutcome:
    """The result of running the chain, complete or partial.

    Attributes:
        status: STATUS_COMPLETE or STATUS_CRITIQUE_FAILED.
        draft: Call 1's output. Always present -- a chain with no draft is
            raised as an error rather than returned.
        writer_model: The slug that served call 1.
        critique: Call 2's output, or None when it failed.
        critic_model: The slug that served call 2, or None.
        signal: How well the critique anchored itself in the story, or None
            when there is no critique to measure. A quality signal, never a
            verdict on whether the critique is correct.
        notice: Plain-language explanation of a partial result, or None.
    """

    status: str
    draft: StoryDraft
    writer_model: str
    critique: StoryCritique | None = None
    critic_model: str | None = None
    signal: OverlapSignal | None = None
    notice: str | None = None


def normalize_story_prompt(raw: str) -> str:
    """Validate and trim a submitted story idea.

    Shared by the HTTP schema and the service so one rule governs both the wire
    boundary and any direct caller, matching `single_call.normalize_prompt`.

    Args:
        raw: The story idea as submitted.

    Returns:
        The idea with surrounding whitespace removed.

    Raises:
        InvalidStoryPromptError: If it is blank or exceeds
            MAX_STORY_PROMPT_CHARS.
    """
    prompt = raw.strip()
    if not prompt:
        raise InvalidStoryPromptError("Enter a story idea before running the chain.")
    if len(prompt) > MAX_STORY_PROMPT_CHARS:
        raise InvalidStoryPromptError(
            f"That story idea is {len(prompt)} characters -- the limit is "
            f"{MAX_STORY_PROMPT_CHARS}."
        )
    return prompt


async def run_chain(session: AsyncSession, *, story_prompt: str) -> ChainOutcome:
    """Run both calls: write a story, then critique that exact story.

    Google-style docstring per project convention.

    Args:
        session: An async SQLAlchemy session for usage/logging bookkeeping.
        story_prompt: The visitor's story idea.

    Returns:
        A complete outcome, or one with STATUS_CRITIQUE_FAILED carrying the
        draft that did succeed.

    Raises:
        InvalidStoryPromptError: If the story idea is blank or over-long.
        UsageLimitReachedError: If today's generation cap cannot cover both
            calls. Raised before either one runs.
        GenerationUnavailableError: If call 1 failed, leaving nothing to show.
    """
    prompt = normalize_story_prompt(story_prompt)

    # Both units, once, up front. Note the consequence, which is deliberate:
    # if call 1 then fails, two units are spent for zero output. Over-counting
    # a shared free tier is the safe direction to be wrong in -- the opposite
    # arrangement would let a chain start that the budget cannot finish.
    await _reserve(session, units=CHAIN_LENGTH)

    try:
        step1 = await run_step(
            role=ROLE_WRITER,
            prompt_version=WRITER_PROMPT_VERSION,
            user_prompt=prompt,
            output_type=StoryDraft,
        )
    except AgentLaneError as exc:
        await _log(session, role=ROLE_WRITER, succeeded=False, detail="chain abandoned")
        raise GenerationUnavailableError(
            "The story could not be generated, so the chain did not start."
        ) from exc

    await _log(
        session,
        role=ROLE_WRITER,
        succeeded=True,
        detail=f"{len(step1.output.story.split())} words via {step1.model}",
    )

    return await _critique(session, draft=step1.output, writer_model=step1.model)


async def run_critique_only(
    session: AsyncSession, *, draft: StoryDraft
) -> ChainOutcome:
    """Re-run only call 2 against a story that was already generated.

    The capability's mitigation for a failed second call: the draft is intact,
    so regenerating it would spend a unit to reproduce something the visitor is
    already looking at -- and would produce a *different* story, quietly
    invalidating the critique they were waiting for.

    Args:
        session: An async SQLAlchemy session for usage/logging bookkeeping.
        draft: The story to critique, as returned by an earlier chain run.

    Returns:
        A complete outcome, or one still carrying STATUS_CRITIQUE_FAILED.

    Raises:
        UsageLimitReachedError: If today's generation cap is spent. One unit is
            reserved here, not two -- only one call is being made.
    """
    await _reserve(session, units=1)
    # writer_model is unknown on this path: the draft arrived from the client
    # and this process may not be the one that generated it (a free dyno spins
    # down between clicks). Naming a model on that basis would be a guess.
    return await _critique(session, draft=draft, writer_model=None)


async def _critique(
    session: AsyncSession, *, draft: StoryDraft, writer_model: str | None
) -> ChainOutcome:
    """Run call 2 over a finished draft and assemble the outcome.

    Args:
        session: An async SQLAlchemy session for logging bookkeeping.
        draft: Call 1's output.
        writer_model: The slug that served call 1, or None on the retry path.

    Returns:
        The outcome, complete or with the critique missing.
    """
    # The whole pattern, in one statement: call 2's input is call 1's output.
    critic_input = CRITIC_INPUT_TEMPLATE.format(title=draft.title, story=draft.story)

    try:
        step2 = await run_step(
            role=ROLE_CRITIC,
            prompt_version=CRITIC_PROMPT_VERSION,
            user_prompt=critic_input,
            output_type=StoryCritique,
        )
    except AgentLaneError:
        await _log(session, role=ROLE_CRITIC, succeeded=False, detail="retryable")
        return ChainOutcome(
            status=STATUS_CRITIQUE_FAILED,
            draft=draft,
            writer_model=writer_model or "unknown",
            notice=_CRITIQUE_FAILED_NOTICE,
        )

    signal = overlap.measure(draft.story, step2.output.quoted_detail)

    await _log(
        session,
        role=ROLE_CRITIC,
        succeeded=True,
        detail=(
            f"{len(step2.output.critique.split())} words via {step2.model}, "
            f"references_story={signal.references_story}"
        ),
    )
    logger.info(
        "chained_calls_chain_completed",
        writer_model=writer_model,
        critic_model=step2.model,
        quoted_detail_found=signal.quoted_detail_found,
        match_ratio=signal.match_ratio,
        references_story=signal.references_story,
    )

    return ChainOutcome(
        status=STATUS_COMPLETE,
        draft=draft,
        writer_model=writer_model or "unknown",
        critique=step2.output,
        critic_model=step2.model,
        signal=signal,
    )


async def _reserve(session: AsyncSession, *, units: int) -> None:
    """Spend `units` generation units up front, or refuse the request.

    Args:
        session: An async SQLAlchemy session.
        units: How many calls this request will make.

    Raises:
        UsageLimitReachedError: If today's cap cannot cover them all. The
            shared error says the capability "has reached" its limit, which is
            true for a one-unit caller but not for this one: a chain is refused
            while there is still budget left, just not enough of it for both
            calls. The message is restated here rather than in `shared`, since
            only the caller knows how many units it asked for.
    """
    try:
        await shared.reserve_capability(
            session,
            shared.CAPABILITY_GENERATION,
            app_name=CHAINED_CALLS_APP_NAME,
            units=units,
        )
    except shared.ServiceUnavailableError as exc:
        if units > 1:
            raise UsageLimitReachedError(
                f"Today's shared generation budget cannot cover all {units} calls in "
                "this chain, so it was not started -- a half-finished chain would "
                "show a story with no critique. The budget resets at 00:00 UTC."
            ) from exc
        raise UsageLimitReachedError(str(exc)) from exc


async def _log(
    session: AsyncSession, *, role: str, succeeded: bool, detail: str
) -> None:
    """Record one cross-app log entry for one step of the chain.

    One entry per call rather than one per request, so the log shows the chain
    as two invocations -- which is what it is, and what the usage counter was
    charged for.

    The summary is assembled from role, outcome, model, and counts. It must
    never carry story text: this app's whole persistence story is that the
    authored content does not outlive the response.

    Args:
        session: An async SQLAlchemy session.
        role: ROLE_WRITER or ROLE_CRITIC.
        succeeded: Whether the call completed.
        detail: Metadata only -- lengths, model slugs, signal flags.
    """
    outcome = "ok" if succeeded else "FAILED"
    await shared.log_invocation(
        session,
        app_name=CHAINED_CALLS_APP_NAME,
        capability=shared.CAPABILITY_GENERATION,
        summary=f"Chained call ({role}) {outcome}: {detail}",
    )
