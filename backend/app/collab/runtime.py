# Built with Spec4 AI - https://spec4.ai
"""The collaboration run's budget, its agent seam, and its two-branch fan-out.

Three pieces, none of which knows anything about buyers, sellers or bids. The
sequencer and the agents are built on top.

## The budget arithmetic, and how it answers Phase 2's open question

Phase 2 reserved eight units and left a question in its docstring: PydanticAI
re-prompts inside one logical step, so eight unbounded steps could spend
sixteen provider requests against a hold of eight -- the v5 production bug
rediscovered. This phase settles it the way the phase text requires, and the
answer is **replacement, not addition**:

- `STEP_REQUEST_LIMIT = 1`. PydanticAI may not silently re-prompt. A step that
  would need a second request fails instead, and the sequencer decides what to
  do about it *explicitly*.
- `NEGOTIATION_CALLS = 6` -- the number the pattern claim rests on, and the
  only number the visitor is told about the negotiation.
- `MAX_PROVIDER_REQUESTS = 8` -- the whole reservation. Six negotiation calls
  leave **two spare requests**, which is the slack every retry, schema repair
  and differentiation nudge draws from.

So a repair replaces the call it repairs in the *stage* count while still
costing a real provider request from the run's slack. `negotiation_stage_calls`
and `total_provider_requests` are therefore two different counters, deliberately:
one is the claim about the pattern, the other is the claim about the spend, and
conflating them is how both stop being checkable.

**Phase 5 will need those two spare requests for the reveal and sensitivity
calls.** At that point the run has no slack left and the hold has to rise, or a
repair has to cost a stage. That is a real decision, not a rounding error, and
it belongs to the phase that spends the units.

## Why the fan-out is written by hand

The same reason the orchestrated app writes its own: a model-driven tool loop
cannot guarantee a fixed number of provider requests, and it would run the two
sellers *one after another* because the caller must receive one tool result
before asking for the next. The demonstration is that the two bid at the same
time, and that neither branch can see the other. `asyncio.gather` gives both.

This duplicates `orchestrated/runtime.py`'s shape. Promoting the generic half
to `services/` is the obvious consolidation and is deliberately not done here:
it would mean editing a shipped, tested slice from inside a phase that owns
neither. Noted as a known gap rather than done quietly.
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
#: **One, not two.** The orchestrated app allows two because a re-prompt there
#: buys a specialist column that would otherwise be lost. Here a silent
#: re-prompt would spend budget the sequencer did not authorise, and the phase
#: requires every repair to be a replacement it can see and record. A step that
#: needs a second request fails and the sequencer repairs it explicitly.
STEP_REQUEST_LIMIT = 1

#: Model calls the negotiation itself makes: two opening bids, one buyer
#: counter-offer call producing both counters, two best-and-final bids, one
#: award. The RFQ (stage 1) and the counter-offer routing (stage 4) are
#: deterministic and cost nothing.
NEGOTIATION_CALLS = 6

#: The two post-award explanation calls. Reserved from the first stage but not
#: spent until v6 Phase 5.
EXPLANATION_CALLS = 2

#: Requests held back for the repairs the sequencer makes explicitly: the award
#: regeneration when a declared winner contradicts its own per-priority scoring,
#: the differentiation nudge when two bids arrive indistinguishable, and a
#: schema repair.
#:
#: **Without this the run had no padding at all**, because
#: `STEP_REQUEST_LIMIT = 1` means every repair is an extra *request*, not an
#: extra attempt inside one. Measured on the Phase 6 smoke run: an award
#: regeneration fired, consumed the sensitivity call's budget, and the ninth
#: request was refused -- so the sensitivity panel fell back to its template and
#: was badged. Both panels still rendered, which is the design working, but the
#: run paid for one correct repair with one lost explanation. Four covers the
#: three repairs that exist plus one.
REPAIR_HEADROOM = 4

#: Provider requests one run may make before it is aborted. The whole
#: reservation -- see the module docstring for what the gap between this and
#: `NEGOTIATION_CALLS` is for.
#:
#: Note what is *not* padded: `STEP_REQUEST_LIMIT` stays at one. Raising it
#: would let PydanticAI re-prompt silently, and this app's claim is that every
#: repair is a replacement it can see and record -- padding that would buy
#: reliability by making the repairs invisible, which is the wrong trade in the
#: one example built to demonstrate visible peer exchanges.
MAX_PROVIDER_REQUESTS = NEGOTIATION_CALLS + EXPLANATION_CALLS + REPAIR_HEADROOM

#: Wall-clock ceiling for one seller's branch. The two run concurrently, so
#: this bounds the run rather than adding to it. Sixty rather than the
#: capability's suggested twelve: v4 measured healthy steps at 4.1--40.7s
#: against these free models, and a too-short timeout cost whole runs.
BRANCH_TIMEOUT_SECONDS = 60.0


class RunBudgetExceededError(Exception):
    """Raised when a run tries to make one provider request more than it may.

    An exception rather than a warning: the ceiling exists so a coding error in
    a later phase cannot quietly turn a bounded demo into an unbounded one
    against a shared free tier.
    """

    def __init__(self, ceiling: int) -> None:
        self.ceiling = ceiling
        super().__init__(
            f"This run reached its ceiling of {ceiling} provider requests, so "
            "the next one was refused."
        )


@dataclass
class RunBudget:
    """One run's two counters: what it spent, and what the pattern claims.

    Mutable and not thread-safe by design: one budget belongs to one run. The
    two seller branches run concurrently but on the same event loop, so their
    increments interleave without racing.

    Attributes:
        ceiling: Provider requests permitted before `spend()` refuses.
        used: Provider requests charged so far, including repairs and retries.
        negotiation_stage_calls: How many of the six negotiation stages have
            been *served*. A repair does not increment this -- it replaces the
            call it repairs -- which is what keeps the six-call claim true
            while `used` still tells the truth about the spend.
    """

    ceiling: int = MAX_PROVIDER_REQUESTS
    used: int = 0
    negotiation_stage_calls: int = 0

    def spend(self) -> None:
        """Account for one provider request about to be made.

        Raises:
            RunBudgetExceededError: If the request would exceed the ceiling.
                Raised *before* the call, so nothing is spent and the counter
                does not record a request that never happened.
        """
        if self.used + 1 > self.ceiling:
            raise RunBudgetExceededError(self.ceiling)
        self.used += 1

    def count_stage_call(self) -> None:
        """Record that one of the six negotiation calls was served.

        Called once per stage call that produced a usable result, never on a
        repair or a retry of the same call. `used` counts requests; this counts
        the pattern.
        """
        self.negotiation_stage_calls += 1

    def remaining(self) -> int:
        """Return how many further provider requests this run may make."""
        return max(0, self.ceiling - self.used)


BranchStatus = Literal["completed", "failed", "timed_out"]


@dataclass
class BranchOutcome:
    """What one side of the fan-out produced.

    Attributes:
        label: Which branch this was -- the seller id.
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
    """Both branches of one concurrent stage.

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

    A thin seam rather than a second lane: the model list, the provider
    credentials, the fallback ordering and the cooldown bench all come from
    `services/agent_runtime.py`, which reads `services/model_registry.py`'s
    chains. **No model slug appears anywhere in this package** -- a second list
    here would rot without anything noticing, and a direct provider SDK call
    would escape the shared usage gate entirely.

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
    around the call, so a step that somehow issued two requests is counted
    twice. Counting the *step* would let the ceiling be a number that did not
    mean what it says.

    **There is no `tools` parameter**, and that is arithmetic as much as
    privacy: a tool-using step takes an unpredictable number of provider
    requests, and this run allows exactly one per step. There is no list for a
    later phase to quietly add to.

    Args:
        label: What this step is, for logs and for the error raised.
        instructions: The agent's system instructions.
        user_prompt: The call's user message.
        output_type: The Pydantic model the response is bound to.
        budget: The run's counters.
        model_settings: Per-request settings such as temperature, for a caller
            regenerating a response at a lower one.

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
        request_limit=STEP_REQUEST_LIMIT,
    )


async def fan_out(
    first: tuple[str, Awaitable[object]],
    second: tuple[str, Awaitable[object]],
    *,
    timeout: float = BRANCH_TIMEOUT_SECONDS,
) -> FanOut:
    """Run exactly two awaitables at the same time and collect both outcomes.

    **`return_exceptions=True` is the whole point.** Without it one seller
    raising cancels the other mid-flight, and the run loses a bid that was
    about to succeed along with the provider request already spent on it. With
    it, a failure is a value like any other and the surviving track stays
    available -- which is what lets the negotiation continue in degraded mode
    with the gap stated rather than silently lost.

    A timeout is its own status rather than folded into failure: "still
    thinking" and "broke" suggest different things to a visitor, and the
    timeout is per branch so a slow seller cannot consume the other's time.

    Args:
        first: A `(label, awaitable)` pair.
        second: The other pair. Runs at the same time as the first.
        timeout: Per-branch wall-clock ceiling.

    Returns:
        Both outcomes, in the order given.
    """

    async def _bounded(label: str, work: Awaitable[object]) -> object:
        async with asyncio.timeout(timeout):
            return await work

    labels = [first[0], second[0]]
    results = await asyncio.gather(
        _bounded(*first),
        _bounded(*second),
        return_exceptions=True,
    )

    outcomes: list[BranchOutcome] = []
    for label, result in zip(labels, results, strict=True):
        if isinstance(result, TimeoutError):
            logger.warning("collab_branch_timed_out", branch=label)
            outcomes.append(
                BranchOutcome(label=label, status="timed_out", error=result)
            )
        elif isinstance(result, BaseException):
            logger.warning(
                "collab_branch_failed", branch=label, error=type(result).__name__
            )
            outcomes.append(BranchOutcome(label=label, status="failed", error=result))
        else:
            outcomes.append(
                BranchOutcome(label=label, status="completed", value=result)
            )

    return FanOut(branches=outcomes)
