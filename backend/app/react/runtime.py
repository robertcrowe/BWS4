# Built with Spec4 AI - https://spec4.ai
"""The run's budget: what is reserved, what may be spent, and what is left.

## The arithmetic, and why every number here is a provider request

    8   search cycles          MAX_SEARCH_CYCLES
    1   final-answer call      FINAL_ANSWER_RESERVE
    1   hop annotation         ANNOTATION_RESERVE   (spent in Phase 6)
    --
    10  MAX_PROVIDER_REQUESTS  == RUN_HOLD_UNITS

**A logical call is not a provider request, and this project has been broken in
production by conflating them** -- v5 measured 2 of 6 orchestrated steps
re-prompting inside a single step, because PydanticAI binds typed output through
a synthetic output tool and asks again when a model botches the call. If a cycle
could silently cost two requests, eight cycles could cost sixteen against a hold
of ten, and the hold would be a number rather than a guarantee.

So this phase revisits Phase 2's `CYCLE_REQUEST_LIMIT = 2` and settles it the
way the collaboration app settled the same question: **one request per step**.
PydanticAI may not re-prompt on its own. A step whose output will not validate
fails, and `service.run_cycle_step` re-asks *explicitly* -- which costs a second
request that this budget can see, count and refuse.

The consequence is worth stating plainly: **a cycle that needs a re-ask costs
two of the ten**, so a run that hits one malformed step has one fewer cycle
available. That is the honest trade. The alternative -- padding the hold so
re-asks are free -- makes the reservation larger than the run's declared cost
and charges every visitor for the failures of a few.

## Why the reserve exists

`FINAL_ANSWER_RESERVE` and `ANNOTATION_RESERVE` are held back from the search
loop, the same device as the planning app's `SYNTHESIS_RESERVE`. Without it a
loop that searched right up to the ceiling would leave nothing to compose an
answer with -- the run would spend ten requests gathering observations and then
have no way to say anything about them, which is the most expensive possible
version of producing nothing.

## Why the loop is hand-rolled

Three reasons, all load-bearing and all the reason this module exists rather
than a PydanticAI tool loop:

1. **The cycle count must be a code invariant**, because the reservation is
   taken before the first cycle and has to size a known worst case.
2. **Every cycle boundary is an SSE emission point.** Framework iteration keeps
   its turns in message history; the whole exhibit is that thought, action and
   observation arrive separately, seconds apart.
3. **The duplicate guard runs between the model choosing a query and the search
   being issued** -- a seam that does not exist when the framework owns the
   tool call.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import structlog

logger = structlog.get_logger()

#: Provider requests one logical step may make.
#:
#: One, not two. See the module docstring: a silent re-prompt would spend budget
#: the loop did not authorise, and this app's whole claim is that its cycle count
#: is a code invariant.
STEP_REQUEST_LIMIT: Final[int] = 1

#: Search cycles a run may run. `Settings.react_cycle_budget` is the operator's
#: dial; this is the name the loop reads it under.
#:
#: **Not visitor-settable, and there is no 3..6 clamp.** The design mock draws a
#: cycle-budget select and the capability text describes one; both are superseded
#: by the stack spec's `react_run_call_budget` decision.
DEFAULT_MAX_SEARCH_CYCLES: Final[int] = 8

#: Held back so the loop can never search its way out of being able to answer.
FINAL_ANSWER_RESERVE: Final[int] = 1

#: Held back on behalf of Phase 6's post-run hop annotation. Reserved from the
#: first cycle and refunded with everything else if the run never gets there --
#: which is why reserving it now costs nothing but a claim on the remainder.
ANNOTATION_RESERVE: Final[int] = 1

#: Wall-clock ceiling for one run, after which it ends candidly rather than
#: leaving the stream open.
#:
#: **120s, not the specification's 90.** That figure travels with the superseded
#: 3..6 cycle budget: at a 6-search ceiling it allowed 15s a cycle, and holding
#: it at 90 while the ceiling rose to 8 would allow 11s. Measured elsewhere in
#: this repo, one Exa search alone is ~5s and a free-tier model turn 1-5s, so 90s
#: would make the *clock* the usual ending rather than the budget -- which would
#: misrepresent what the demonstration is showing. Same reasoning, and the same
#: direction, as the planning app's 30s -> 90s step timeout.
RUN_WALL_CLOCK_SECONDS: Final[float] = 120.0


def max_provider_requests(max_search_cycles: int = DEFAULT_MAX_SEARCH_CYCLES) -> int:
    """Return the run's worst case in provider requests.

    Derived rather than written down twice, so the hold and the ceiling cannot
    drift apart: a hold smaller than the ceiling promises budget the run may
    overspend, and a hold larger than it charges for requests that can never be
    made.

    Args:
        max_search_cycles: The configured search-cycle ceiling.

    Returns:
        Search cycles plus the final answer plus the annotation.
    """
    return max_search_cycles + FINAL_ANSWER_RESERVE + ANNOTATION_RESERVE


class RunBudgetExceededError(Exception):
    """Raised when a request would take the run past its reserved ceiling.

    The backstop rather than the plan: the loop's own accounting stops it well
    before this, and reaching here means something asked for a request the run
    had not budgeted. It raises rather than warns, because a coding error must
    not be able to turn a bounded demonstration into an unbounded one and
    merely mention it.
    """


@dataclass
class RunBudget:
    """The run's ledger: reserved, spent, and what may still be asked for.

    Attributes:
        ceiling: Provider requests the run reserved. Never raised in flight.
        spent: Requests actually made, counted as they are made rather than
            assumed from the number of logical steps.
        max_search_cycles: The search ceiling this run was configured with.
    """

    ceiling: int
    spent: int = 0
    max_search_cycles: int = DEFAULT_MAX_SEARCH_CYCLES

    def charge(self, requests: int = 1) -> None:
        """Record requests that were made.

        Called *after* the fact with what a step reported, not before with what
        it was expected to cost -- `StepResult.requests` is the truth, and the
        difference between the two is the bug this whole module exists to make
        impossible.

        Args:
            requests: How many provider requests the step actually made.

        Raises:
            RunBudgetExceededError: If the run has passed its ceiling.
        """
        self.spent += requests
        if self.spent > self.ceiling:
            raise RunBudgetExceededError(
                f"The run spent {self.spent} provider requests against a "
                f"ceiling of {self.ceiling}."
            )

    @property
    def remaining(self) -> int:
        """Return requests still available before the ceiling."""
        return max(0, self.ceiling - self.spent)

    def can_search_again(self, searches_used: int) -> bool:
        """Whether another search cycle may be started.

        Two independent limits, and the run stops at whichever comes first:

        * the **search ceiling**, which is the number the app is about; and
        * the **request budget**, which must still hold back enough for the
          final answer and the annotation once this cycle is paid for.

        A cycle that needed a re-ask spent two requests, so the second limit is
        what quietly costs that run a cycle -- deliberately, and visibly in the
        counter the visitor is watching.

        Args:
            searches_used: Searches issued so far.

        Returns:
            True when another cycle is affordable and permitted.
        """
        if searches_used >= self.max_search_cycles:
            return False
        needed = STEP_REQUEST_LIMIT + FINAL_ANSWER_RESERVE + ANNOTATION_RESERVE
        return self.remaining >= needed

    def can_answer(self) -> bool:
        """Whether the final-answer call is still affordable.

        Returns:
            True when at least the answer call's own request remains. The
            annotation's reserve is deliberately not required here: an answer
            the visitor can read matters more than a badge Phase 6 adds to it.
        """
        return self.remaining >= FINAL_ANSWER_RESERVE
