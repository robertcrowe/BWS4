# Built with Spec4 AI - https://spec4.ai
"""The subagent orchestration runtime: build agents, count calls, fan out, fan in.

Three pieces, none of which knows anything about specialists, briefs or
questions. Later phases build the coordinator and the two specialists on top;
this file is the substrate they share.

## Why the fan-out is written by hand rather than delegated to the framework

PydanticAI supports agent delegation -- specialists exposed to a coordinator as
tools -- and that is the wrong shape here for two reasons the pattern depends
on. A model-driven tool loop cannot guarantee a fixed number of provider
requests, and it would run the specialists *one after another*, because the
coordinator has to receive one tool result before it can ask for the next. The
demonstration is that two independent workers run **at the same time**, so the
dispatch is an `asyncio.gather` this module owns. The specialists also have no
tool access at all, which removes the last reason to model them as tools.

## Models come from the shared registry, never from here

Agents are built through `services/agent_runtime.py`, the PydanticAI lane the
chained-calls and planning apps already use: one `FallbackModel` spanning
providers, resolved from `services/model_registry.py`'s chains and subject to
the same cooldown bench. **No model slug appears anywhere in this package** --
choosing which family serves a capability is the registry's job, and a second
list here would rot without anything noticing.

The phase describes constructing the provider and fallback wrapper directly.
That machinery already exists in the shared lane, and duplicating it is exactly
what this project's notes forbid; using it satisfies the same requirement --
both slugs read from the shared config module -- with one implementation.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass, field
from typing import Literal

import structlog
from pydantic import BaseModel
from pydantic_ai.settings import ModelSettings

from backend.app.services import agent_runtime

logger = structlog.get_logger()

#: Provider requests one logical step may make.
#:
#: **Two, because one logical call is not one provider request.** PydanticAI
#: binds typed output through a synthetic output tool and *re-prompts* when a
#: model botches the call -- measured at 2 of 6 specialist steps against the
#: chain's Groq-served head, with `result.usage.requests == 2` confirming the
#: retry happened inside the step rather than as a walk down the fallback chain.
#: (The slug is deliberately not named here: no model slug belongs in this
#: package, and a test enforces it.)
#:
#: This is a per-step ceiling enforced by PydanticAI itself, which is what stops
#: one greedy step from eating another's share of the run. A step that needs a
#: third request loses its own column and nothing else.
STEP_REQUEST_LIMIT = 2

#: Logical model calls one run makes: the delegation, the two specialists, and
#: the coordinator's closing synthesis turn. The moderation gate is **not**
#: counted -- it reaches a different provider, is free of charge, and draws on
#: no model allowance.
LOGICAL_CALLS_PER_RUN = 4

#: Provider requests a single run may make before it is aborted.
#:
#: Eight: four logical calls, each allowed one framework re-prompt. **This was
#: four, and four was measurably wrong.** The specification's hard counter
#: assumes one provider request per logical call; in practice a third of typed
#: steps take two, so a run budgeted at four had zero tolerance and lost a
#: specialist column on roughly half of all dispatches. Raising the ceiling is
#: what makes the fan-out reliable; the per-step limit above is what keeps it
#: bounded rather than merely larger.
#:
#: The visitor-facing count is untouched at three -- a re-prompt is the
#: framework fixing its own malformed request, not a call the run chose to make.
MAX_PROVIDER_REQUESTS = LOGICAL_CALLS_PER_RUN * STEP_REQUEST_LIMIT

#: What the visitor is told a run costs.
#:
#: Three, and the difference from the ceiling above is not a rounding error. The
#: merge is the coordinator's closing turn on a conversation it already holds,
#: so from the visitor's side the run is "one coordinator, two specialists".
#: Reporting four would be counting an implementation detail at them; enforcing
#: three would abort a run that is behaving exactly as designed.
VISITOR_FACING_CALL_COUNT = 3

#: Wall-clock ceiling for one specialist branch. Generous, because the two run
#: concurrently: the run waits for the slower of the pair, so this bounds the
#: run rather than adding to it.
BRANCH_TIMEOUT_SECONDS = 60.0


class RunBudgetExceededError(Exception):
    """Raised when a run tries to make one provider request more than it may.

    An exception rather than a logged warning, deliberately. The ceiling exists
    so a coding error in a later phase cannot quietly turn a three-call demo
    into an unbounded one against a shared free tier; a warning would let that
    happen and merely mention it afterwards.
    """

    def __init__(self, ceiling: int) -> None:
        self.ceiling = ceiling
        super().__init__(
            f"This run reached its ceiling of {ceiling} provider requests, so the "
            "next one was refused."
        )


@dataclass
class RunBudget:
    """A single run's provider-request counter.

    Mutable and not thread-safe by design: one budget belongs to one run. The
    two specialist branches run concurrently but on the same event loop, so
    their increments interleave without racing.

    Attributes:
        ceiling: Requests permitted before `spend()` refuses.
        used: Requests charged so far.
    """

    ceiling: int = MAX_PROVIDER_REQUESTS
    used: int = 0

    def spend(self) -> None:
        """Account for one provider request about to be made.

        Raises:
            RunBudgetExceededError: If the request would exceed the ceiling. Raised
                *before* the call, so nothing is spent and the counter does not
                record a request that never happened.
        """
        if self.used + 1 > self.ceiling:
            raise RunBudgetExceededError(self.ceiling)
        self.used += 1

    def remaining(self) -> int:
        """Return how many further provider requests this run may make."""
        return max(0, self.ceiling - self.used)

    @property
    def visitor_facing_count(self) -> int:
        """Return the call count to show the visitor.

        Fixed rather than derived from `used`: it is a statement about how the
        run is *designed*, shown before anything has run, not a tally of what
        has happened so far.
        """
        return VISITOR_FACING_CALL_COUNT


BranchStatus = Literal["completed", "failed", "timed_out"]


@dataclass
class BranchOutcome:
    """What one side of the fan-out produced.

    Attributes:
        label: Which branch this was, for logs and for the column heading.
        status: `completed`, `failed`, or `timed_out`.
        value: The branch's result, or None unless it completed.
        error: The exception, or None unless it failed or timed out.
    """

    label: str
    status: BranchStatus
    value: object | None = None
    error: BaseException | None = None

    @property
    def ok(self) -> bool:
        """True when this branch produced a usable result."""
        return self.status == "completed"


@dataclass
class FanOut:
    """Both branches of one dispatch.

    Attributes:
        branches: The two outcomes, in the order the tasks were given.
    """

    branches: list[BranchOutcome] = field(default_factory=list)

    @property
    def survivors(self) -> list[BranchOutcome]:
        """The branches that produced a result."""
        return [branch for branch in self.branches if branch.ok]

    @property
    def all_failed(self) -> bool:
        """True when neither branch produced anything."""
        return not self.survivors


def build_agent[T: BaseModel](
    *,
    instructions: str,
    output_type: type[T],
) -> object:
    """Build one PydanticAI agent over the shared cross-provider fallback model.

    A thin seam rather than a second lane: the model, the provider credentials,
    the fallback ordering and the cooldown bench all come from
    `services/agent_runtime.py`. What this adds is the argument shape the
    orchestrated app's agents share.

    Args:
        instructions: The agent's system instructions.
        output_type: The Pydantic model its response is bound to.

    Returns:
        A configured agent, ready to run.
    """
    from pydantic_ai import Agent

    return Agent(
        agent_runtime.build_fallback_model(),
        output_type=output_type,
        instructions=instructions,
    )


async def run_agent_step[T: BaseModel](
    *,
    label: str,
    instructions: str,
    user_prompt: str,
    output_type: type[T],
    budget: RunBudget,
    model_settings: ModelSettings | None = None,
) -> agent_runtime.StepResult[T]:
    """Run one typed agent turn, charging the run's budget before the call.

    The budget is charged through the lane's per-request hook rather than once
    around the call, so a step that somehow issued two provider requests is
    counted twice. Counting the *step* instead would let the ceiling be a
    number that did not mean what it says.

    Args:
        label: What this step is, for logs and for the error raised.
        instructions: The agent's system instructions.
        user_prompt: The call's user message.
        output_type: The Pydantic model the response is bound to.
        budget: The run's counter.
        model_settings: Per-request settings such as temperature, for a caller
            that regenerates a response at a lower temperature.

    Returns:
        The validated output and the slug that served it.

    Raises:
        RunBudgetExceededError: If the run has no requests left.
        AgentLaneError: If every model in the chain failed.
    """

    async def charge() -> None:
        budget.spend()

    return await agent_runtime.run_typed_step(
        label=label,
        instructions=instructions,
        user_prompt=user_prompt,
        output_type=output_type,
        on_request=charge,
        model_settings=model_settings,
        # Bounded per step, not only against the run's shared pool. Without
        # this a step that re-prompts twice would spend its partner's share,
        # which is exactly how a live run lost both specialist columns.
        request_limit=STEP_REQUEST_LIMIT,
    )


async def fan_out(
    first: tuple[str, Awaitable[object]],
    second: tuple[str, Awaitable[object]],
    *,
    timeout: float = BRANCH_TIMEOUT_SECONDS,
) -> FanOut:
    """Run exactly two awaitables at the same time and collect both outcomes.

    **`return_exceptions=True` is the whole point.** Without it, one specialist
    raising cancels the other mid-flight, and the visitor loses a column that
    was about to succeed -- along with the provider request already spent on it.
    With it, a failure is a value like any other and the surviving column stays
    on screen, which is what lets the merge proceed with a note about the
    missing contribution.

    A timeout is reported as its own status rather than folded into failure:
    "this specialist is still thinking" and "this specialist broke" are
    different things to show someone, and only one of them suggests trying
    again.

    Args:
        first: A label and the first awaitable.
        second: A label and the second awaitable.
        timeout: Per-branch wall-clock ceiling. Applied per branch, not to the
            pair, so a slow branch cannot consume the other's time.

    Returns:
        Both outcomes, in the order given.
    """
    labels = (first[0], second[0])

    async def bounded(awaitable: Awaitable[object]) -> object:
        async with asyncio.timeout(timeout):
            return await awaitable

    results = await asyncio.gather(
        bounded(first[1]),
        bounded(second[1]),
        return_exceptions=True,
    )

    outcomes: list[BranchOutcome] = []
    for label, result in zip(labels, results, strict=True):
        if isinstance(result, TimeoutError):
            outcomes.append(
                BranchOutcome(label=label, status="timed_out", error=result)
            )
        elif isinstance(result, BaseException):
            outcomes.append(BranchOutcome(label=label, status="failed", error=result))
        else:
            outcomes.append(
                BranchOutcome(label=label, status="completed", value=result)
            )

    logger.info(
        "orchestrated_fan_out_completed",
        statuses={outcome.label: outcome.status for outcome in outcomes},
        survivors=len([outcome for outcome in outcomes if outcome.ok]),
    )
    return FanOut(branches=outcomes)
