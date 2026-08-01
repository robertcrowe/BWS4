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

#: Model calls one run may make, from the capability's own arithmetic:
#: 1 planner + at most 1 replan + at most 5 executor calls. Reaching it is not
#: an error -- a run that uses one replan, or one research step that reformulates
#: its query, lands exactly here. The eighth call is the one that is refused.
MAX_MODEL_CALLS = 7


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

    def allowance(self, step_limit: int, *, reserve: int = 0) -> int:
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

        Returns:
            How many requests the step may make, possibly zero. Zero is a real
            answer and the caller must handle it: starting a step with a
            one-request budget guarantees a failure that still costs a call,
            which is worse than not starting it.
        """
        return min(step_limit, max(0, self.remaining() - reserve))
