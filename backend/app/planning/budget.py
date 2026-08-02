# Built with Spec4 AI - https://spec4.ai
"""The hard per-run model-call ceiling.

The capability's runaway-loop failure mode requires that the ceiling be
"enforced in the run orchestrator (framework-level, not prompt-level)". This
module is that enforcement, and the distinction is the whole point: a prompt
asking a model to make at most seven calls is a request, and a counter that
refuses the eighth is a guarantee. Only one of the two survives a model that
misbehaves, and a planning agent is exactly the tier where that matters, because
an agent that writes its own next step can write itself a loop.

`CallBudget.charge()` is wired to `agent_runtime.GatedModel` via the orchestrator,
so it runs immediately before each model request -- including the several a
single tool-using step makes internally. Counting agent *runs* instead would
undercount by roughly a factor of two and the ceiling would not mean what it
says.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Provider requests one run may make. Reaching it is not an error; the request
#: after it is the one that is refused.
#:
#: **This is a count of provider requests, not of logical steps, and the two
#: were conflated at 7.** That figure came from the capability's arithmetic --
#: 1 planner + at most 1 replan + at most 5 executor calls -- which prices a
#: research step at roughly one call. A research step is a *tool-using* step: it
#: spends one request emitting each search, one reading the results, and may
#: spend one more on PydanticAI's schema retry. Two research steps at the
#: allowance `agents.py` actually grants them, plus a planner and a synthesis,
#: could never have fitted in 7 -- so `allowance()` silently shrank the second
#: step's limit until it could not finish either. Reported live: both research
#: steps died on `StepRequestLimitExceeded` and the visitor got an itinerary
#: built on nothing.
#:
#: Nine was the smallest *self-consistent* ceiling and it was still too tight to
#: absorb one bad turn. Reported live: a research step failed on
#: `UnexpectedModelBehavior` after 3 requests, its retry spent 3 more, and the
#: second step was then skipped for budget -- with synthesis one request away
#: from `CallCeilingExceeded` ending the run outright. Eighteen is that same
#: arithmetic with the retry actually paid for and headroom on top:
#:
#:     1 planner + (5 x 2 attempts) + (5 x 2 attempts) + 2 synthesis = 23 absolute
#:     1 planner + (5 x 2 attempts) +  5              + 2 synthesis = 18 padded
#:     1 planner +  3               +  3              + 1 synthesis =  6 typical
#:
#: So one research step may fail and retry at full allowance while the other
#: still runs and synthesis still composes. Both steps failing *and* both
#: retrying at full allowance is deliberately not covered -- that is 23, and at
#: some point a run that has gone that wrong should stop rather than keep buying
#: attempts. `allowance(attempts=...)` is what keeps the reserve honest in
#: between.
#:
#: **This is a ceiling, not a reservation**, which is why padding it is cheap:
#: the gate charges `generation` per request as it goes, so a typical run still
#: costs six whatever this says. Raising it does not raise normal spend; it
#: raises what a *degrading* run is allowed to spend recovering. That is the
#: opposite of the orchestrated and collaboration apps, which reserve their
#: whole ceiling up front as a hold and where padding costs runs per hour
#: directly.
MAX_MODEL_CALLS = 18


class CallCeilingExceeded(Exception):
    """Raised when a run tries to make one more model call than it may.

    Carries the ceiling so the caller can explain the stop without restating
    the number, which would then have two places to be wrong.
    """

    def __init__(self, ceiling: int) -> None:
        self.ceiling = ceiling
        super().__init__(
            f"This run reached its ceiling of {ceiling} model calls, so the next call "
            "was refused. Whatever finished before that point is preserved."
        )


@dataclass
class CallBudget:
    """A run's model-call counter.

    Mutable and deliberately not thread-safe: one budget belongs to one run,
    and a run is a single sequential coroutine. Sharing one across runs would
    be a bug that this type should not quietly accommodate.

    Attributes:
        ceiling: The maximum number of model calls permitted.
        used: Calls charged so far.
    """

    ceiling: int = MAX_MODEL_CALLS
    used: int = 0

    def remaining(self) -> int:
        """Return how many further model calls this run may make."""
        return max(0, self.ceiling - self.used)

    def charge(self) -> None:
        """Account for one model call about to be made.

        Raises:
            CallCeilingExceeded: If the call would take the run past its
                ceiling. Raised *before* the call, so nothing is spent.
        """
        if self.used + 1 > self.ceiling:
            raise CallCeilingExceeded(self.ceiling)
        self.used += 1

    def allowance(self, step_limit: int, *, reserve: int = 0, attempts: int = 1) -> int:
        """Bound a step's own request limit by what the run has left.

        Lets the framework stop a step cleanly at the run's edge instead of the
        gate having to refuse mid-step, while `charge()` remains the thing that
        actually guarantees the ceiling.

        Args:
            step_limit: The step's own maximum request count.
            reserve: Calls to hold back for later steps. The orchestrator
                reserves the synthesis call, so research cannot spend the run
                down to nothing and leave the visitor with notes and no
                itinerary -- which is exactly what a live run produced before
                this existed.
            attempts: How many times the caller may run this step. **The
                returned figure bounds one attempt, so a retried step spends up
                to `attempts` times it** -- dividing by this is what keeps the
                reserve a reserve. Reported live: a research step failed on
                `UnexpectedModelBehavior` after 3 requests and its retry spent 3
                more, which was never budgeted for; the second step was skipped
                for budget and one further request would have taken synthesis
                over the ceiling, ending the run with no itinerary at all.

        Returns:
            How many requests one attempt may make, possibly zero. Zero is a
            real answer and the caller must handle it: starting a step with a
            one-request budget guarantees a failure that still costs a call,
            which is worse than not starting it.
        """
        return min(step_limit, max(0, (self.remaining() - reserve) // max(1, attempts)))
