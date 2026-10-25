# Built with Spec4 AI - https://spec4.ai
"""The comparison re-run: eligibility, and the tickets that make it checkable.

A re-run sends a misrouted preset once through its expected route so the
visitor can compare the two answers side by side. The router does not run
again, and a re-run never feeds either history -- it is a forced route, not a
routing outcome.

## Eligibility

Offered only for a **preset** run whose **dispatched** route differs from the
preset's expected route -- whether the router chose wrongly, declined and the
tie-break landed wrong, fell back via the evaluator, or returned a malformed
decision that went to single call. Never for free text, never when a
tie-break happened to land on the expected route, and at most once per run.

## Why tickets

The re-run endpoint must recompute eligibility from trusted data rather than
believe the client. The expected route comes from the preset catalogue; the
dispatched route comes from a ticket this process recorded when the original
run ended. Tickets live in process memory -- per-process state, which the
API's single-worker deployment already depends on -- and expire with the UTC
hour's allowance window. A restart forgets them, and a re-run is then refused
as unknown rather than guessed at. "At most once" is enforced twice: the
ticket is spent on use, and the re-run's allowance hold is keyed by the
original run id, so the hold table's primary key refuses a second one even
across a restart.
"""

from __future__ import annotations

import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from typing import Final

from backend.app.router.constants import RouteId
from backend.app.router.presets import RouterPreset

#: How long a run stays re-runnable, in seconds.
TICKET_TTL_SECONDS: Final[float] = 3600.0
#: Most tickets held at once; the oldest are dropped first.
MAX_TICKETS: Final[int] = 4096


def is_eligible(*, preset: RouterPreset | None, dispatched_route: RouteId) -> bool:
    """Whether a finished run may be re-run through its expected route.

    Args:
        preset: The run's preset, or None for free text.
        dispatched_route: Where the run's request was finally dispatched.

    Returns:
        True for a preset run dispatched somewhere other than its expected
        route; False otherwise.
    """
    return preset is not None and dispatched_route != preset.expected_route


def rerun_hold_key(original_run_id: uuid.UUID) -> str:
    """The allowance-hold key for a run's one re-run.

    Args:
        original_run_id: The run being re-run.

    Returns:
        A key unique to that run's re-run.
    """
    return f"{original_run_id}:rerun"


@dataclass(frozen=True)
class Ticket:
    """What the server recorded about an eligible run when it ended."""

    preset_id: str
    dispatched_route: RouteId
    issued_at: float


class TicketBook:
    """Eligible runs awaiting an optional re-run. In-process, bounded, expiring."""

    def __init__(self) -> None:
        self._tickets: OrderedDict[uuid.UUID, Ticket] = OrderedDict()

    def issue(self, run_id: uuid.UUID, preset_id: str, dispatched: RouteId) -> None:
        """Record an eligible run.

        Args:
            run_id: The run.
            preset_id: Its preset.
            dispatched: Where it was dispatched.
        """
        self._prune()
        self._tickets[run_id] = Ticket(preset_id, dispatched, time.monotonic())
        while len(self._tickets) > MAX_TICKETS:
            self._tickets.popitem(last=False)

    def peek(self, run_id: uuid.UUID) -> Ticket | None:
        """Look up a run's ticket without spending it.

        Args:
            run_id: The original run.

        Returns:
            The ticket, or None when unknown, expired or spent.
        """
        self._prune()
        return self._tickets.get(run_id)

    def spend(self, run_id: uuid.UUID) -> None:
        """Spend a ticket so the run cannot be re-run again.

        Args:
            run_id: The original run.
        """
        self._tickets.pop(run_id, None)

    def clear(self) -> None:
        """Forget every ticket. For tests."""
        self._tickets.clear()

    def _prune(self) -> None:
        cutoff = time.monotonic() - TICKET_TTL_SECONDS
        while self._tickets:
            oldest = next(iter(self._tickets.values()))
            if oldest.issued_at >= cutoff:
                break
            self._tickets.popitem(last=False)


#: The process's one ticket book.
TICKETS: Final[TicketBook] = TicketBook()
