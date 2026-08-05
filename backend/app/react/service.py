# Built with Spec4 AI - https://spec4.ai
"""The slice's service layer: the bounded loop, its budget, and its endings.

## The loop is hand-rolled, and that is the exhibit

`stream_run` is an ordinary `while`. It is not PydanticAI's tool-calling
iteration, and the three reasons are all load-bearing -- see
`react/runtime.py` for the arithmetic behind the first:

1. The cycle count is a **code invariant**, because the run reserves its whole
   worst case before the first cycle and has to size a known number.
2. Every cycle boundary is an **SSE emission point**. Framework iteration keeps
   its turns in message history; the demonstration is that thought, action and
   observation arrive separately, seconds apart.
3. The **duplicate guard runs between** the model choosing a query and the
   search being issued -- a seam that does not exist when the framework owns
   the tool call.

## One place decides how a run ended

`_terminal_card` is a pure function returning exactly one card, called from
exactly one place. The alternative -- emitting a card wherever a termination is
noticed -- is how a run comes to produce both a final answer and a
budget-exhausted card, or neither. `TERMINAL_EVENTS` and the tests pin that
exactly one is emitted.

## One place gives the budget back

`_settle` runs in a `finally` that wraps the entire run, including every
abnormal exit: an early answer, a client disconnect, a malformed step, a dead
provider, the wall clock. A missed refund is invisible -- the run looks fine and
the showcase quietly loses capacity until visitors start hitting caps -- so
there is exactly one release path and no way around it.

**Redeeming and refunding are different things and both happen.**
`allowance_holds` releases the *promise*; `shared.release_capability` returns
the *spend* the gate was charged up front. A run that answers in three cycles
gives back seven of its ten units, and that refund is what makes a deliberately
generous eight-search budget affordable at all.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core import observability
from backend.app.core.config import get_settings
from backend.app.db.models import ReactRun, UsageLimit
from backend.app.db.session import async_session_factory
from backend.app.react import annotation, duplicate_guard, runtime, schemas
from backend.app.react.presets import (
    CUSTOM_ORIGIN,
    PRESET_SET_VERSION,
    PRESETS,
    get_preset,
)
from backend.app.services import (
    agent_runtime,
    allowance_holds,
    embedding,
    shared,
    web_search,
)
from backend.app.services.prompt_context import with_current_date
from backend.app.services.prompt_loader import load_prompt
from backend.app.services.untrusted import untrusted_block

logger = structlog.get_logger()

PROMPTS_DIR = Path(__file__).parent / "prompts"

#: The per-cycle prompt version in force. Bumped by adding `cycle_v2.md`
#: alongside, never by editing a shipped version in place -- the same convention
#: as `rag/prompts/answer_vN.md`, and for the same reason: a past run's trace is
#: only reproducible if the prompt that produced it still exists.
CYCLE_PROMPT_VERSION = "cycle_v1"

#: Model requests one cycle's step may take.
#:
#: **One, revised down from two when Phase 3 built the budget the reservation
#: depends on.** Phase 2 allowed a second so PydanticAI could retry its own
#: synthetic output tool. That is exactly the silent re-prompt v5 measured in
#: production, and it would make a cycle cost an unpredictable number of
#: provider requests -- which is fatal here, because the run reserves its whole
#: worst case before the first cycle and the ceiling has to be a number the code
#: guarantees rather than one it hopes for.
#:
#: So the framework may not re-ask, and `run_cycle_step`'s service-level re-ask
#: does it **explicitly** instead: a second request the run's ledger sees,
#: counts, and can refuse. The visible consequence is that a cycle needing a
#: re-ask costs two of the run's ten requests, so that run has one fewer cycle.
#: See `react/runtime.py` for the full arithmetic.
CYCLE_REQUEST_LIMIT = runtime.STEP_REQUEST_LIMIT

#: How many times one cycle's step may be asked for.
#:
#: The specification's validation-failure policy exactly: one re-ask with the
#: validation error appended, and a second failure terminates the run. Not a
#: retry loop with a tunable count -- a model that returns a malformed step
#: twice against an explicit description of what was wrong is not going to get
#: it right on the third ask, and each attempt is a real provider request out of
#: a budget the run reserved up front.
CYCLE_STEP_ATTEMPTS = 2

#: The per-visit run limit this app publishes. The gallery's tightest, because
#: a loop can issue a search on every cycle -- see the vision's constraint. It
#: is a *client-side* counter with the server's hourly `usage_limits` gate
#: behind it, exactly as the planning and orchestrated apps do it, so this
#: number is what the run stream reports rather than what it enforces.
RUNS_PER_SESSION = 2


class UnknownPresetError(ValueError):
    """Raised when a request names a preset id the catalogue does not carry."""


@dataclass(frozen=True)
class StreamEvent:
    """One event on its way to the wire.

    A name and an already-validated payload. The router encodes it; nothing
    here knows about SSE framing.

    Attributes:
        name: The SSE event name the client listens for.
        payload: The envelope, dumped from its Pydantic model.
    """

    name: str
    payload: dict[str, Any] = field(default_factory=dict)


def public_presets() -> schemas.PresetsResponse:
    """Project the preset catalogue into what the selector may see.

    The per-hop maintainer notes stay server-side, and there is no answer to
    withhold because the catalogue holds none -- see `presets.py`.

    Returns:
        The five curated questions, the catalogue version, and the run's
        server-fixed search-cycle budget.
    """
    settings = get_settings()
    return schemas.PresetsResponse(
        presets=[
            schemas.PresetView(
                id=preset.id,
                label=preset.label,
                question=preset.question,
                hop_count=preset.hop_count,
                guaranteed_fully_observed=preset.guaranteed_fully_observed,
            )
            for preset in PRESETS
        ],
        set_version=PRESET_SET_VERSION,
        cycle_budget=settings.react_cycle_budget,
    )


def resolve_question(request: schemas.RunRequest) -> tuple[str, str]:
    """Work out what question this run answers, and where it came from.

    A preset id is resolved to the catalogue's **canonical** wording rather
    than to anything the client sent, which is what lets the shared moderation
    gate recognise curated text by byte-match from Phase 3 -- a preset id is a
    claim, and text accepted on the strength of one could carry anything.

    Args:
        request: The validated request body.

    Returns:
        A `(question, origin)` pair, where origin is a preset id or `custom`.

    Raises:
        UnknownPresetError: If the request names a preset that does not exist.
    """
    if request.preset_question_id is not None:
        preset = get_preset(request.preset_question_id)
        if preset is None:
            raise UnknownPresetError(request.preset_question_id)
        return preset.question, preset.id

    # The model validator has already established exactly one source was
    # supplied, so this branch has a question.
    assert request.visitor_question is not None
    return request.visitor_question.strip(), CUSTOM_ORIGIN


# ---------------------------------------------------------------------------
# The bounded loop
# ---------------------------------------------------------------------------

#: What this app is called in `usage_limits`, `service_log_entries` and the
#: allowance ledger.
REACT_APP_NAME = "react_loop_example_app"

#: The final-answer prompt in force. Bumped by adding `final_answer_v2.md`
#: alongside, never by editing a shipped version in place.
FINAL_ANSWER_PROMPT_VERSION = "final_answer_v1"

#: Consecutive unreachable searches the run tolerates before ending candidly.
#:
#: One is a blip the next cycle can work around, and the loop hands the model an
#: explicit "the search could not be run" observation so it can try something
#: else. Two in a row is the provider being down, and continuing would spend the
#: rest of the budget discovering that repeatedly.
MAX_CONSECUTIVE_SEARCH_FAILURES = 2

#: Times the duplicate guard may refuse a candidate within one cycle before the
#: cycle is counted as spent. The specification's mitigation exactly: the model
#: is told which observation already covers the ground and asked once more.
MAX_GUARD_REPROMPTS_PER_CYCLE = 1


@dataclass
class _RunState:
    """Everything one run accumulates. Nothing here outlives the run."""

    observations: list[schemas.Observation] = field(default_factory=list)
    trace: list[dict[str, Any]] = field(default_factory=list)
    timings: dict[str, Any] = field(default_factory=dict)
    issued: duplicate_guard.IssuedQueries = field(
        default_factory=duplicate_guard.IssuedQueries
    )
    searches_used: int = 0
    duplicates_blocked: int = 0
    empty_observations: int = 0
    consecutive_search_failures: int = 0
    last_thought: str = ""
    answer_decision: schemas.AnswerAction | None = None

    def partial_findings(self) -> list[int]:
        """Observation indices that actually returned something."""
        return [o.index for o in self.observations if not o.is_empty]


def _unresolved_text(
    reason: schemas.ExhaustionReason, state: _RunState, budget_cycles: int
) -> list[str]:
    """Say what the run did not manage to establish, and why it stopped.

    **Deterministic, not a model call.** A run that ended because it ran out of
    budget or because the provider is unreachable is the worst possible moment
    to need one more provider request, and a card that could itself fail to
    render would turn a candid ending into no ending at all. What the model has
    to say about what it still needed is already in the trace -- its last
    thought -- so that is quoted rather than re-elicited.

    Args:
        reason: Which wall the run hit.
        state: What the run accumulated.
        budget_cycles: The search ceiling it was counted against.

    Returns:
        Plain sentences for the card, most specific first.
    """
    headline = {
        "search_ceiling": (
            f"The run reached its ceiling of {budget_cycles} searches without "
            "the model deciding it could answer."
        ),
        "malformed_step": (
            "The model returned a step that could not be read, twice in a row, "
            "so the run stopped rather than guessing what it meant."
        ),
        "search_unavailable": (
            "The search service could not be reached, so the run could not "
            "gather the observations it still needed."
        ),
        "model_unavailable": (
            "No model in the shared chain could be reached, so the run could "
            "not take its next step."
        ),
        "wall_clock": (
            "The run passed its time limit of "
            f"{int(runtime.RUN_WALL_CLOCK_SECONDS)} seconds and was stopped."
        ),
        "call_budget": (
            "The run spent its reserved call budget before reaching an answer. "
            "A step that had to be re-asked costs the run a cycle."
        ),
    }[reason]

    lines = [headline]
    if state.last_thought:
        lines.append(f"The model's last thought was: {state.last_thought}")
    if state.empty_observations:
        lines.append(
            f"{state.empty_observations} of {state.searches_used} searches "
            "returned no results."
        )
    if not state.partial_findings():
        lines.append("No search returned anything the answer could rest on.")
    return lines


def _terminal_card(
    *,
    run_id: uuid.UUID,
    answer: schemas.ComposedAnswer | None,
    reason: schemas.ExhaustionReason | None,
    state: _RunState,
    budget_cycles: int,
) -> schemas.FinalAnswer | schemas.BudgetExhausted:
    """Decide how the run ended. Exactly one card, from exactly one place.

    Args:
        run_id: The run's id.
        answer: The composed answer, when the run produced one.
        reason: Why the run stopped, when it did not.
        state: What the run accumulated.
        budget_cycles: The search ceiling.

    Returns:
        One card. `BudgetExhausted` has no answer field to fill in, which is the
        structural half of never dressing an unfinished run up as an answer.

    Raises:
        ValueError: If neither an answer nor a reason was supplied. A run that
            ended for no recorded reason is a bug, and returning some default
            card would hide it.
    """
    if answer is not None:
        return schemas.FinalAnswer(
            run_id=str(run_id),
            answer=answer.answer,
            observation_cycles=list(answer.grounded_on),
            audit=schemas.audit_grounding(answer.grounded_on, state.observations),
            searches_used=state.searches_used,
            cycle_budget=budget_cycles,
        )
    if reason is None:
        raise ValueError("A run must end with either an answer or a reason.")
    return schemas.BudgetExhausted(
        run_id=str(run_id),
        reason=reason,
        unresolved=_unresolved_text(reason, state, budget_cycles),
        partial_findings=state.partial_findings(),
        searches_used=state.searches_used,
        cycle_budget=budget_cycles,
    )


async def read_allowance(session: AsyncSession) -> tuple[int, int, datetime]:
    """Read what is left of the generation gate this hour.

    Applies the **same strictly-older window comparison** `reserve_capability`
    applies. A reader that skipped it would report last hour's leftover as this
    hour's figure, which is the documented way to get this wrong.

    Args:
        session: An async SQLAlchemy session.

    Returns:
        Remaining units, the cap, and when the window rolls over.
    """
    window = shared.utc_window()
    result = await session.execute(
        select(UsageLimit).where(UsageLimit.capability == shared.CAPABILITY_GENERATION)
    )
    row = result.scalar_one_or_none()
    if row is None:
        cap = get_settings().generation_hourly_limit
        return cap, cap, window + timedelta(hours=1)
    used = 0 if row.window_start is None or row.window_start < window else row.used
    return max(0, row.cap - used), row.cap, window + timedelta(hours=1)


async def _settle(run_id: uuid.UUID, budget: runtime.RunBudget) -> None:
    """Give back everything the run reserved and did not spend.

    The single release path, called from a `finally` that wraps the whole run.
    **Never raises**: it runs on the way out of paths that are already failing,
    and an exception here would turn one problem into two while still leaving
    the budget held.

    **It opens its own session, and that is not tidiness.** The common reason
    this runs is a visitor closing the tab, at which point the streaming
    response's session is being torn down around it -- committing through a
    session the caller is in the middle of closing is a race, and the write that
    loses it is the refund.

    Args:
        run_id: The run's id, which is also the hold's key.
        budget: The run's ledger.
    """
    unspent = max(0, budget.ceiling - budget.spent)
    try:
        async with async_session_factory() as session:
            if unspent:
                await shared.release_capability(
                    session,
                    shared.CAPABILITY_GENERATION,
                    app_name=REACT_APP_NAME,
                    units=unspent,
                )
            if budget.spent:
                await allowance_holds.redeem(session, str(run_id))
            else:
                await allowance_holds.refund(session, str(run_id))
    except Exception:  # noqa: BLE001 - teardown must not raise over a failing run
        logger.exception("react_settle_failed", run_id=str(run_id))
    else:
        logger.info(
            "react_run_settled",
            run_id=str(run_id),
            reserved=budget.ceiling,
            spent=budget.spent,
            refunded=unspent,
        )


async def _release(run_id: uuid.UUID, budget: runtime.RunBudget) -> None:
    """Run the settle so that a cancelled run still gives its budget back.

    **The trap this exists for, caught by a live run rather than by a test.**
    When a visitor disconnects, the task running this generator is cancelled --
    and inside an already-cancelled task *every* `await` raises `CancelledError`
    immediately. A `finally` that simply awaits its cleanup therefore does not
    perform it. Measured: the hold stayed `reserved` and all ten units stayed
    charged to the hourly gate, on the one exit path where a visitor definitely
    spent nothing.

    `asyncio.shield` fixes it because the shielded coroutine runs as its own
    task: the *await* here is cancelled, the release is not.

    Args:
        run_id: The run's id.
        budget: The run's ledger.
    """
    await asyncio.shield(_settle(run_id, budget))


async def _compose_answer(
    *,
    question: str,
    state: _RunState,
    budget: runtime.RunBudget,
) -> schemas.ComposedAnswer | None:
    """Make the run's final call: the answer, with the observations it used.

    Its own model call with its own versioned prompt, and the last request the
    budget reserves for. The cycle's `answer` action was the *decision* to stop
    searching; this is the answer composed with every observation in view.

    Args:
        question: The question being answered.
        state: What the run gathered.
        budget: The run's ledger, charged with what this call costs.

    Returns:
        The composed answer, or None when the lane could not produce one.
    """
    instructions = load_prompt(PROMPTS_DIR, FINAL_ANSWER_PROMPT_VERSION)
    prompt = build_cycle_prompt(question, state.observations)
    try:
        with observability.span("react.answer", "react final answer"):
            result = await agent_runtime.run_typed_step(
                label="react-final-answer",
                instructions=instructions,
                user_prompt=prompt,
                output_type=schemas.ComposedAnswer,
                request_limit=runtime.STEP_REQUEST_LIMIT,
            )
    except agent_runtime.AgentLaneError:
        budget.charge(runtime.FINAL_ANSWER_RESERVE)
        logger.warning("react_final_answer_failed")
        return None

    budget.charge(result.requests)
    return result.output


async def stream_run(
    session: AsyncSession,
    *,
    run_id: uuid.UUID,
    request: schemas.RunRequest,
    suitability: schemas.QuestionSuitability | None = None,
) -> AsyncGenerator[StreamEvent, None]:
    """Run the loop and put every cycle boundary on the wire as it happens.

    Args:
        session: A session the caller's generator owns, not one bound to the
            request scope -- this response outlives its handler.
        run_id: The id this run is stored and retrievable under, and the key
            its allowance hold is reserved with.
        request: The validated request body.
        suitability: The advisory verdict for a free-form question, recorded on
            the run record. Advisory only -- it never gates the run, and a
            `None` here is the ordinary case for a preset.

    Yields:
        `run_started`, then per cycle a `cycle_counter`, `cycle_thought`,
        `cycle_action` and `cycle_observation`, terminating in exactly one of
        `final_answer`, `budget_exhausted` or `error`.
    """
    settings = get_settings()
    budget_cycles = settings.react_cycle_budget
    ceiling = runtime.max_provider_requests(budget_cycles)

    try:
        question, origin = resolve_question(request)
    except UnknownPresetError as exc:
        yield StreamEvent(
            schemas.EVENT_ERROR,
            schemas.RunError(
                code="unknown_preset",
                message=(
                    "That question is no longer in the curated set. Choose "
                    "another, or type your own."
                ),
            ).model_dump(),
        )
        logger.info("react_run_refused", run_id=str(run_id), reason=str(exc))
        return

    # The showcase-wide gate, before anything is promised. A refused run has
    # reserved nothing and so has nothing to give back.
    try:
        await shared.reserve_capability(
            session,
            shared.CAPABILITY_GENERATION,
            app_name=REACT_APP_NAME,
            units=ceiling,
        )
    except shared.ServiceUnavailableError:
        remaining, cap, resets_at = await read_allowance(session)
        yield StreamEvent(
            schemas.EVENT_ERROR,
            schemas.RunError(
                code="usage_limit_reached",
                message=(
                    "The showcase's shared hourly allowance for model calls is "
                    f"used up ({remaining} of {cap} left, resets at "
                    f"{resets_at:%H:%M} UTC). This is the gallery-wide limit, "
                    "not this example's own — nothing you can reword will help."
                ),
            ).model_dump(),
        )
        logger.info("react_run_refused", run_id=str(run_id), reason="usage_limit")
        return

    # The claim on what is left. Taken before the first cycle so a run is never
    # begun that the allowance cannot finish.
    try:
        await allowance_holds.reserve(
            session,
            hold_key=str(run_id),
            capability=shared.CAPABILITY_GENERATION,
            app_name=REACT_APP_NAME,
            units=ceiling,
        )
    except allowance_holds.HoldStateError:
        await shared.release_capability(
            session,
            shared.CAPABILITY_GENERATION,
            app_name=REACT_APP_NAME,
            units=ceiling,
        )
        yield StreamEvent(
            schemas.EVENT_ERROR,
            schemas.RunError(
                code="run_already_started",
                message="That run has already been started.",
            ).model_dump(),
        )
        return

    budget = runtime.RunBudget(ceiling=ceiling, max_search_cycles=budget_cycles)
    state = _RunState()
    started = time.monotonic()
    answer: schemas.ComposedAnswer | None = None
    reason: schemas.ExhaustionReason | None = None
    cycle = 0

    try:
        yield StreamEvent(
            schemas.EVENT_RUN_STARTED,
            schemas.RunStarted(
                run_id=str(run_id),
                question=question,
                question_source="preset" if origin != CUSTOM_ORIGIN else "custom",
                preset_id=None if origin == CUSTOM_ORIGIN else origin,
                cycle_budget=budget_cycles,
                runs_remaining=RUNS_PER_SESSION,
            ).model_dump(),
        )

        while True:
            if time.monotonic() - started > runtime.RUN_WALL_CLOCK_SECONDS:
                reason = "wall_clock"
                break
            if not budget.can_search_again(state.searches_used):
                reason = (
                    "search_ceiling"
                    if state.searches_used >= budget_cycles
                    else "call_budget"
                )
                break

            cycle += 1
            cycle_started = time.monotonic()

            # Emitted at the START of the cycle, so the consumed budget is
            # visible before the run ends rather than only in hindsight.
            yield StreamEvent(
                schemas.EVENT_CYCLE_COUNTER,
                schemas.CycleCounter(
                    searches_used=state.searches_used, cycle_budget=budget_cycles
                ).model_dump(),
            )

            guard_note: str | None = None
            reprompts = 0
            observation: schemas.Observation | None = None
            action: schemas.SearchAction | schemas.AnswerAction | None = None

            with observability.span("react.cycle", f"react cycle {cycle}", cycle=cycle):
                while True:
                    outcome = await run_cycle_step(
                        question=question,
                        observations=state.observations,
                        cycle=cycle,
                        guard_note=guard_note,
                    )
                    if isinstance(outcome, MalformedStep):
                        budget.charge(outcome.requests)
                        reason = "malformed_step"
                        break

                    budget.charge(outcome.requests)
                    state.last_thought = outcome.step.thought
                    action = outcome.step.action

                    if isinstance(action, schemas.AnswerAction):
                        state.answer_decision = action
                        break

                    decision = check_candidate_query(action.query, state.issued)
                    if decision.allowed:
                        break

                    state.duplicates_blocked += 1
                    if reprompts >= MAX_GUARD_REPROMPTS_PER_CYCLE:
                        # The cycle is spent: the model was told once which
                        # observation already covered this ground and asked
                        # again anyway. Issuing the query would spend a search
                        # on results the run already has.
                        action = None
                        break
                    reprompts += 1
                    guard_note = decision.note

                if reason is not None:
                    break
                if action is None:
                    # A cycle burnt entirely on refused duplicates. It cost its
                    # model requests and no search, which is exactly what the
                    # guard is for.
                    continue
                if isinstance(action, schemas.AnswerAction):
                    break

                yield StreamEvent(
                    schemas.EVENT_CYCLE_THOUGHT,
                    schemas.CycleThought(
                        cycle=cycle, thought=state.last_thought
                    ).model_dump(),
                )
                yield StreamEvent(
                    schemas.EVENT_CYCLE_ACTION,
                    schemas.CycleAction(
                        cycle=cycle,
                        kind="search",
                        query=action.query,
                        rationale="",
                    ).model_dump(),
                )

                # Every search is charged to the shared search gate, one unit
                # per query actually issued -- the duplicate guard runs first
                # precisely so a refused query costs nothing here.
                try:
                    await shared.reserve_capability(
                        session,
                        shared.CAPABILITY_SEARCH,
                        app_name=REACT_APP_NAME,
                        units=1,
                    )
                except shared.ServiceUnavailableError:
                    reason = "search_unavailable"
                    break

                observation = await build_observation(
                    action.query, len(state.observations) + 1
                )

            if reason is not None:
                break

            assert observation is not None
            state.observations.append(observation)
            state.searches_used += 1
            remember_issued_query(action.query, state.issued)

            if observation.status == "unavailable":
                state.consecutive_search_failures += 1
            else:
                state.consecutive_search_failures = 0
            if observation.is_empty and observation.status == "empty":
                state.empty_observations += 1

            yield StreamEvent(schemas.EVENT_CYCLE_OBSERVATION, observation.model_dump())

            state.trace.append(
                {
                    "cycle": cycle,
                    "thought": state.last_thought,
                    "action": {"kind": "search", "query": action.query},
                    "observation": observation.model_dump(),
                }
            )
            state.timings[f"cycle_{cycle}"] = round(time.monotonic() - cycle_started, 3)

            if state.consecutive_search_failures >= MAX_CONSECUTIVE_SEARCH_FAILURES:
                reason = "search_unavailable"
                break

        # The thought that decided to answer belongs in the trace too, so the
        # visitor sees the model's reasoning for stopping.
        if state.answer_decision is not None:
            yield StreamEvent(
                schemas.EVENT_CYCLE_THOUGHT,
                schemas.CycleThought(
                    cycle=cycle, thought=state.last_thought
                ).model_dump(),
            )
            yield StreamEvent(
                schemas.EVENT_CYCLE_ACTION,
                schemas.CycleAction(
                    cycle=cycle, kind="answer", query=None, rationale=""
                ).model_dump(),
            )
            state.trace.append(
                {
                    "cycle": cycle,
                    "thought": state.last_thought,
                    "action": {"kind": "answer", "query": None},
                    "observation": None,
                }
            )
            if budget.can_answer():
                answer = await _compose_answer(
                    question=question, state=state, budget=budget
                )
                if answer is None:
                    reason = "model_unavailable"
            else:
                reason = "call_budget"

        card = _terminal_card(
            run_id=run_id,
            answer=answer,
            reason=reason,
            state=state,
            budget_cycles=budget_cycles,
        )
        ending = (
            schemas.ENDING_FINAL_ANSWER
            if isinstance(card, schemas.FinalAnswer)
            else schemas.ENDING_BUDGET_EXHAUSTED
        )
        yield StreamEvent(
            schemas.EVENT_FINAL_ANSWER
            if ending == schemas.ENDING_FINAL_ANSWER
            else schemas.EVENT_BUDGET_EXHAUSTED,
            card.model_dump(),
        )

        await persist_run(
            session,
            run_id=run_id,
            question_origin=origin,
            cycle_budget=budget_cycles,
            searches_used=state.searches_used,
            ending=ending,
            cycle_trace=state.trace,
            terminal_card=card.model_dump(),
            duplicate_queries_blocked=state.duplicates_blocked,
            empty_observations=state.empty_observations,
            cycle_timings=state.timings,
            suitability=suitability,
        )
        # **After** the terminal card is already on the wire and the run is
        # already stored. Annotation is decorative: the visitor has their
        # result before this runs, and a failure here changes nothing they can
        # see. It is also the tenth call of the reservation Phase 3 took, so it
        # is charged to that budget rather than reserving anything new.
        annotation_outcome = annotation.OUTCOME_SKIPPED
        if budget.can_answer():
            labels = await annotation.annotate(
                run_id=str(run_id),
                question=question,
                cycles=state.trace,
                ending=ending,
                affordable=budget.remaining >= 1,
            )
            budget.charge(1)
            annotation_outcome = annotation.outcome_of(labels)
            if labels is not None:
                yield StreamEvent(schemas.EVENT_HOP_ANNOTATIONS, labels.model_dump())
            await attach_annotations(
                session,
                run_id=run_id,
                result=labels,
            )

        # **One consolidated record per run**, the shape v5's
        # `orchestrated_run_summary` settled on. Answering "what did that run
        # do?" from three per-phase events meant joining them by run id; the
        # ending distribution, the budget consumption and the annotation
        # outcome are one row here instead.
        #
        # `requests_redeemed` is the disclosed-versus-actual check: the page
        # tells a visitor a run reserves ten calls, and this is what it really
        # spent. A divergence is then visible in production rather than only in
        # a test.
        #
        # Nothing here is visitor text. `question_origin` is a preset id or the
        # literal "custom", and the suitability fields are the derived verdict,
        # never the question it was about.
        logger.info(
            "react_run_summary",
            run_id=str(run_id),
            question_origin=origin,
            ending=ending,
            cycles=cycle,
            searches_used=state.searches_used,
            cycle_budget=budget_cycles,
            duplicates_blocked=state.duplicates_blocked,
            empty_observations=state.empty_observations,
            requests_spent=budget.spent,
            requests_redeemed=budget.spent,
            requests_reserved=budget.ceiling,
            annotation_outcome=annotation_outcome,
            suitability_verdict=(None if suitability is None else suitability.verdict),
            suitability_exercises_loop=(
                None if suitability is None else suitability.exercises_loop
            ),
        )
    except asyncio.CancelledError:
        # The visitor walked away. Nothing further is spent, and the `finally`
        # below still gives the reservation back -- which matters most here,
        # because this is the gallery's most expensive example per run.
        logger.info(
            "react_run_abandoned",
            run_id=str(run_id),
            searches_used=state.searches_used,
            requests_spent=budget.spent,
        )
        raise
    finally:
        await _release(run_id, budget)


async def persist_run(
    session: AsyncSession,
    *,
    run_id: uuid.UUID,
    question_origin: str,
    cycle_budget: int,
    searches_used: int,
    ending: str,
    cycle_trace: list[dict[str, Any]],
    terminal_card: dict[str, Any],
    duplicate_queries_blocked: int = 0,
    empty_observations: int = 0,
    cycle_timings: dict[str, Any] | None = None,
    suitability: schemas.QuestionSuitability | None = None,
) -> None:
    """Write one completed run's record.

    Written once, at run end, rather than per cycle. A half-written trace read
    back later would show an interrupted run with no way to tell it had been
    interrupted -- the same reasoning as the collaboration app's run cache.

    `question_origin` is a preset id or `custom`; **the question itself is never
    stored**, which is the project's standing rule for telemetry over
    visitor-written text.

    Args:
        session: The session the generator owns.
        run_id: The run's id, and the key its trace is retrievable under.
        question_origin: A preset id, or `custom`.
        cycle_budget: The ceiling this run was allowed.
        searches_used: How much of it was spent.
        ending: `final_answer` or `budget_exhausted`.
        cycle_trace: The ordered cycles.
        terminal_card: The card the run ended on.
        duplicate_queries_blocked: Candidates the near-duplicate guard refused.
        empty_observations: Searches that returned nothing.
        cycle_timings: Per-cycle latencies.
        suitability: The free-form question's advisory verdict, when one was
            made. **Only the four derived fields are stored** -- never the
            question, and never the sentence shown to the visitor, which is
            model-written prose about text this table deliberately does not
            keep.
    """
    session.add(
        ReactRun(
            id=run_id,
            question_origin=question_origin,
            cycle_budget=cycle_budget,
            searches_used=searches_used,
            ending=ending,
            duplicate_queries_blocked=duplicate_queries_blocked,
            empty_observations=empty_observations,
            cycle_trace=cycle_trace,
            terminal_card=terminal_card,
            cycle_timings=cycle_timings,
            suitability_chained_facts=(
                None if suitability is None else suitability.exercises_loop
            ),
            suitability_needs_live_info=(
                None if suitability is None else suitability.requires_live_info
            ),
            suitability_estimated_hops=(
                None if suitability is None else suitability.estimated_hops
            ),
            suitability_confidence=(
                None if suitability is None else suitability.confidence
            ),
        )
    )
    await session.commit()


async def attach_annotations(
    session: AsyncSession,
    *,
    run_id: uuid.UUID,
    result: schemas.AnnotationResult | None,
) -> None:
    """Record the annotations on the already-persisted run.

    A **second** write, after `persist_run`, deliberately. Annotation runs for
    seconds after the terminal card is streamed, and folding it into the first
    write would mean a visitor who closes the tab mid-annotation loses the run
    record entirely -- trading a decorative panel for the trace itself.

    Never raises: annotation is decorative, and a failure to record it must not
    become the reason a completed run reports an error.

    Args:
        session: The generator's own session.
        run_id: The run to update.
        result: The cross-checked annotations, or None when there are none.
    """
    try:
        row = (
            await session.execute(select(ReactRun).where(ReactRun.id == run_id))
        ).scalar_one_or_none()
        if row is None:
            return
        row.annotation_outcome = annotation.outcome_of(result)
        if result is not None:
            row.hop_annotations = result.model_dump()
        await session.commit()
    except Exception:  # noqa: BLE001 - decorative; must not fail a finished run
        logger.exception("react_annotation_persist_failed", run_id=str(run_id))


async def load_run(
    session: AsyncSession, run_id: uuid.UUID
) -> schemas.TraceResponse | None:
    """Read one stored run back whole.

    Args:
        session: A request-scoped session -- this route does not stream.
        run_id: The run to load.

    Returns:
        The whole trace, or None when no run carries that id.
    """
    result = await session.execute(select(ReactRun).where(ReactRun.id == run_id))
    row = result.scalar_one_or_none()
    if row is None:
        return None

    suitability = None
    if row.suitability_confidence is not None:
        suitability = schemas.SuitabilityVerdict(
            chained_facts=bool(row.suitability_chained_facts),
            needs_live_info=bool(row.suitability_needs_live_info),
            estimated_hops=row.suitability_estimated_hops or 0,
            confidence=row.suitability_confidence,
        )

    created_at = row.created_at or datetime.now(UTC)
    return schemas.TraceResponse(
        run_id=str(row.id),
        created_at=created_at.isoformat(),
        question_origin=row.question_origin,
        searches_used=row.searches_used,
        cycle_budget=row.cycle_budget,
        ending=row.ending,
        duplicate_queries_blocked=row.duplicate_queries_blocked,
        empty_observations=row.empty_observations,
        annotation_outcome=row.annotation_outcome,
        suitability=suitability,
        cycle_trace=list(row.cycle_trace or []),
        terminal_card=row.terminal_card,
        hop_annotations=row.hop_annotations,
        cycle_timings=row.cycle_timings,
    )


# ---------------------------------------------------------------------------
# The per-cycle model call
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CycleStep:
    """One cycle's validated decision, plus what producing it cost.

    Attributes:
        step: The thought and the action, already widened to `ReactStep`.
        model: The slug that actually served it, read off the response.
        requests: Provider requests spent across every attempt. What the run's
            budget must be charged, not what a cycle "usually" costs.
        attempts: How many times the step was asked for. 2 means the re-ask
            fired and succeeded.
    """

    step: schemas.ReactStep
    model: str
    requests: int
    attempts: int


@dataclass(frozen=True)
class MalformedStep:
    """The cycle produced nothing usable, twice.

    Returned rather than raised, because the caller's response is not "handle an
    error" -- it is to end the run as budget-exhausted **with the malformed step
    disclosed in the trace**, which is a rendering decision Phase 3 owns. An
    exception would push that decision into a handler and invite it to be
    reported as a crash instead of as an honest ending.

    Attributes:
        detail: What went wrong, operator- and visitor-facing. Carries the
            framework's validation message, never a model's own prose.
        requests: Provider requests spent reaching this conclusion.
        attempts: Always `CYCLE_STEP_ATTEMPTS`. Named rather than implied so a
            reader of a trace can see the re-ask happened.
    """

    detail: str
    requests: int
    attempts: int


#: What a cycle's model call returns: a decision, or the disclosed failure.
CycleOutcome = CycleStep | MalformedStep


def render_observations(observations: list[schemas.Observation]) -> str:
    """Render the run's observations for the next cycle's prompt.

    Every snippet goes inside `services/untrusted.py`'s delimiters, which the
    prompt tells the model never to take instructions from. That framing is only
    worth something because `untrusted_block` strips forged markers out of the
    content first -- a snippet carrying the closing delimiter would otherwise end
    the untrusted region early and everything after it would read as prompt.

    An empty or unavailable observation is rendered **explicitly**, never
    omitted. A missing cycle would let the model treat the miss as though it had
    not happened; the whole point is that it has to react to it.

    Args:
        observations: Every observation the run has gathered, in order.

    Returns:
        The transcript section, or a line stating there are none yet.
    """
    if not observations:
        return "No observations yet. This is the first cycle."

    blocks: list[str] = []
    for observation in observations:
        header = (
            f"Observation {observation.index} — query issued: {observation.query!r}"
        )
        if observation.status == "unavailable":
            body = (
                "The search could not be run. This is a tool failure, not "
                "evidence about the world."
            )
        elif observation.is_empty:
            body = "The search returned no results."
        else:
            lines = []
            for result in observation.results:
                date = result.published_date or "undated"
                cut = " [snippet truncated]" if result.truncated else ""
                lines.append(
                    f"[{result.idx}] {result.title} ({date}) — {result.url}\n"
                    f"{result.snippet}{cut}"
                )
            body = "\n\n".join(lines)
        block = untrusted_block(f"observation {observation.index}", body)
        blocks.append(f"{header}\n{block}")

    return "\n\n".join(blocks)


def build_cycle_prompt(
    question: str,
    observations: list[schemas.Observation],
    *,
    guard_note: str | None = None,
    validation_error: str | None = None,
) -> str:
    """Compose the user message for one cycle's step.

    The question is wrapped in the untrusted delimiters as well as the
    observations. It is visitor-written text on a public endpoint, and the fact
    that it is the *subject* of the run does not make it instructions to the
    model -- the same position the orchestrated app takes on its own question.

    Args:
        question: The question being answered.
        observations: What the run has gathered so far.
        guard_note: The duplicate guard's re-prompt, when the previous candidate
            was refused. Emitted **outside** the untrusted block, deliberately:
            wrapping the one sentence that must be obeyed in the delimiters the
            prompt is told to distrust would be self-defeating.
        validation_error: The framework's complaint about the previous attempt,
            when this is the re-ask.

    Returns:
        The user prompt.
    """
    parts = [
        untrusted_block("visitor question", question),
        "",
        render_observations(observations),
    ]
    if guard_note:
        parts += ["", f"NOTE FROM THE SYSTEM (not from an observation): {guard_note}"]
    if validation_error:
        parts += [
            "",
            "Your previous response could not be used. The system reported: "
            f"{validation_error}. Return one short thought and exactly one "
            "well-formed action.",
        ]
    return "\n".join(parts)


async def run_cycle_step(
    *,
    question: str,
    observations: list[schemas.Observation],
    cycle: int,
    guard_note: str | None = None,
    on_request: Any = None,
) -> CycleOutcome:
    """Ask the model for one cycle's thought and action.

    Runs on the shared PydanticAI lane, so it inherits the registry's chain-walk
    failover, the withdrawn-slug bench, the per-request gate and this project's
    fallback observation. **No model slug is named here or anywhere in this
    package** -- `model_registry` is the single source of truth and its chains
    are documented to rot.

    The step offers **no tools**. The search is issued by application code after
    the model has chosen its query, which is what lets the budget stay a code
    invariant, lets the duplicate guard sit between the choice and the call, and
    makes every cycle boundary a place the stream can emit from.

    Implements the specification's validation-failure policy: one re-ask with
    the validation error appended, then a `MalformedStep` the caller turns into
    a candid ending.

    Args:
        question: The question being answered.
        observations: What the run has gathered so far. Its length also selects
            the output type -- search-only until there is something to answer
            from.
        cycle: 1-based cycle number, for logs and spans. Not sent to the model.
        guard_note: The duplicate guard's re-prompt, when the previous candidate
            was refused.
        on_request: Awaited before each provider request, for the run's budget.
            Passed straight through to the lane.

    Returns:
        The validated step, or `MalformedStep` after the re-ask also failed.
    """
    output_type = schemas.step_output_type(len(observations))
    instructions = with_current_date(load_prompt(PROMPTS_DIR, CYCLE_PROMPT_VERSION))

    requests = 0
    validation_error: str | None = None

    for attempt in range(1, CYCLE_STEP_ATTEMPTS + 1):
        prompt = build_cycle_prompt(
            question,
            observations,
            guard_note=guard_note,
            validation_error=validation_error,
        )
        try:
            with observability.span(
                "react.cycle.model",
                f"react cycle {cycle} step",
                cycle=cycle,
                attempt=attempt,
            ):
                result = await agent_runtime.run_typed_step(
                    label=f"react-cycle-{cycle}",
                    instructions=instructions,
                    user_prompt=prompt,
                    output_type=output_type,
                    request_limit=CYCLE_REQUEST_LIMIT,
                    on_request=on_request,
                )
        except agent_runtime.StepRequestLimitExceeded as exc:
            # Deterministic by construction -- the step has no tools, so a model
            # that spent its request limit did so re-prompting itself into the
            # same malformed shape. Re-asking runs the same model against the
            # same prompt to reach the same limit, which the planning app paid
            # for once already.
            requests += CYCLE_REQUEST_LIMIT
            logger.warning("react_cycle_request_limit", cycle=cycle, attempt=attempt)
            return MalformedStep(detail=str(exc), requests=requests, attempts=attempt)
        except agent_runtime.AgentLaneError as exc:
            # The lane collapses "every model in the chain failed" and "the
            # output would not validate" into one exception type, so this
            # re-asks for both. That costs one extra attempt in the
            # chain-exhausted case, which is the cheaper direction to be wrong
            # in: re-asking a healthy chain about a malformed step is the case
            # the policy exists for, and refusing to re-ask would lose it.
            requests += 1
            validation_error = str(exc)
            logger.warning(
                "react_cycle_step_rejected",
                cycle=cycle,
                attempt=attempt,
                error_type=type(exc).__name__,
            )
            if attempt == CYCLE_STEP_ATTEMPTS:
                return MalformedStep(
                    detail=validation_error, requests=requests, attempts=attempt
                )
            continue

        requests += result.requests
        output = result.output
        step = (
            output.to_step() if isinstance(output, schemas.ReactSearchStep) else output
        )
        logger.info(
            "react_cycle_step",
            cycle=cycle,
            action=step.action.kind,
            model=result.model,
            requests=requests,
            attempts=attempt,
        )
        return CycleStep(
            step=step, model=result.model, requests=requests, attempts=attempt
        )

    # Unreachable: the loop either returns or exhausts its attempts above.
    raise AssertionError("run_cycle_step fell through its attempt loop")


# ---------------------------------------------------------------------------
# The observation builder
# ---------------------------------------------------------------------------


def _truncate(snippet: str) -> tuple[str, bool]:
    """Cut a snippet to the context bound, reporting whether it was cut.

    Args:
        snippet: The provider's text, verbatim.

    Returns:
        The snippet and whether truncation occurred. The flag is why this
        returns a pair -- the prompt says so explicitly, so the model does not
        read a missing detail as evidence the detail does not exist.
    """
    if len(snippet) <= schemas.SNIPPET_MAX_CHARS:
        return snippet, False
    return snippet[: schemas.SNIPPET_MAX_CHARS], True


async def build_observation(query: str, index: int) -> schemas.Observation:
    """Issue one query and record what came back, verbatim.

    A **direct in-process call** to the shared Exa wrapper, deliberately not a
    PydanticAI tool and deliberately not behind MCP. The direct shape is what
    lets application code hold the search budget, interpose the duplicate guard
    between the model's choice and the call, and render the exact query issued
    beside its snippets. There is exactly one Exa client in this project and
    this is not a second one.

    **The model authors none of this.** Every field is copied from the provider
    payload, which is what makes a fabricated fact visibly absent from the
    observation rather than blended into it.

    Args:
        query: The exact query the model chose, passed through unmodified.
        index: 1-based observation number, the value an answer may cite.

    Returns:
        The observation. Never raises for a search failure -- an unreachable
        provider is a recorded fact the loop must react to, not an exception the
        run dies on.
    """
    try:
        with observability.span(
            "react.cycle.search", f"react observation {index}", observation=index
        ):
            raw = await web_search.search(query)
    except (web_search.ExaClientError, web_search.ExaRateLimitError) as exc:
        logger.warning(
            "react_observation_unavailable",
            observation=index,
            error_type=type(exc).__name__,
        )
        return schemas.Observation(
            index=index,
            query=query,
            results=[],
            is_empty=True,
            status="unavailable",
            detail="The search service could not be reached for this cycle.",
        )

    results: list[schemas.ObservationResult] = []
    any_truncated = False
    for position, item in enumerate(raw, start=1):
        published = web_search.SearchToolResult.from_exa(item)
        snippet, truncated = _truncate(published.snippet)
        any_truncated = any_truncated or truncated
        results.append(
            schemas.ObservationResult(
                idx=position,
                title=published.title,
                url=published.url,
                snippet=snippet,
                published_date=published.published_date,
                truncated=truncated,
            )
        )

    logger.info(
        "react_observation",
        observation=index,
        results=len(results),
        truncated=any_truncated,
    )
    return schemas.Observation(
        index=index,
        query=query,
        results=results,
        # Explicit, never a dropped cycle: the model has to be made to react to
        # a miss, and a hidden miss is the failure mode this guards.
        is_empty=not results,
        status="ok" if results else "empty",
        truncated=any_truncated,
    )


# ---------------------------------------------------------------------------
# The duplicate guard's one impure edge
# ---------------------------------------------------------------------------


def check_candidate_query(
    candidate: str, issued: duplicate_guard.IssuedQueries
) -> duplicate_guard.DuplicateDecision:
    """Embed a candidate query and put it through the pure guard.

    The only place this slice embeds anything, and the seam that keeps
    `duplicate_guard.py` free of every input it cannot be handed. The shared
    in-process MiniLM model spends local CPU and nobody's third-party quota,
    which is exactly why every candidate is checked rather than only the
    suspicious ones -- and it is why this is **not** gated against the usage
    allowance.

    Args:
        candidate: The query the model chose.
        issued: What this run has already sent.

    Returns:
        The guard's verdict. A refused query must not reach Exa.
    """
    settings = get_settings()
    decision = duplicate_guard.evaluate_query(
        candidate,
        embedding.embed_text(candidate),
        issued,
        settings.react_duplicate_similarity_threshold,
    )
    if not decision.allowed:
        logger.info(
            "react_duplicate_query_blocked",
            reason=decision.reason,
            matched=decision.matched_index,
            similarity=(
                None if decision.similarity is None else round(decision.similarity, 3)
            ),
        )
    return decision


def remember_issued_query(query: str, issued: duplicate_guard.IssuedQueries) -> None:
    """Record a query that actually reached Exa.

    Called only after the search is issued. A *refused* query is deliberately
    never remembered: it was never sent, nothing should be measured against it,
    and remembering it would let one rejection poison the next cycle's
    comparison.

    Args:
        query: The query that was issued, verbatim.
        issued: The run's in-process record.
    """
    issued.remember(query, embedding.embed_text(query))
