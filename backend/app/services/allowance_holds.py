# Built with Spec4 AI - https://spec4.ai
"""Reserve, redeem and refund against the shared hourly usage gate.

`usage_limits` records what has been **spent**. This records what has been
**promised**, and the difference is the whole reason the table exists: two
visitors can each be told there is room for three calls when between them there
is room for four.

The orchestrated-subagents run holds its entire budget *before* the coordinator
writes a delegation decision, so a plan is never displayed that the allowance
can no longer execute -- the capability's named failure between showing the
decision and the visitor confirming dispatch.

## These are internal calls and must never become model-visible tools

Every function here is called by application code only. Exposing any of them as
a tool would let generated output manipulate the very budget that bounds it,
which is the same reasoning that keeps the quota check out of the planning
agent's tool surface.

## Reserving is not spending

A hold does not increment `usage_limits.used`; `reserve_capability` does that
when the call is actually made. A hold is a claim on the *remainder*, which is
why it has to be released. Redeem and refund are both releases -- one because
the calls happened, one because they never will -- and a hold that was only
ever redeemed would make a run that failed before spending anything cost the
showcase the same as one that succeeded.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import AllowanceHold
from backend.app.services.shared import utc_window

logger = structlog.get_logger()

STATE_RESERVED: Final[str] = "reserved"
STATE_REDEEMED: Final[str] = "redeemed"
STATE_REFUNDED: Final[str] = "refunded"

#: How long a reserved hold may sit before it is treated as abandoned.
#:
#: Long enough that a visitor can read a delegation decision and think about it,
#: short enough that a browser closed mid-run does not hold budget for the rest
#: of the window. The hold's own window bounds it too -- nothing survives the
#: hour it was taken in -- so this only matters within a single window.
HOLD_EXPIRY = timedelta(minutes=15)


class HoldNotFoundError(Exception):
    """Raised when a hold key does not exist.

    Distinct from a state error: "never reserved" and "already redeemed" are
    different bugs in the caller, and collapsing them would hide which.
    """


class HoldStateError(Exception):
    """Raised when a hold cannot make the requested transition.

    Only `reserved` may become `redeemed` or `refunded`. A double redeem or a
    refund after redemption would each release budget twice, so both are
    refused rather than treated as idempotent.
    """


async def _load(session: AsyncSession, hold_key: str) -> AllowanceHold:
    """Fetch a hold by key.

    Args:
        session: An async SQLAlchemy session.
        hold_key: The hold's key.

    Returns:
        The hold.

    Raises:
        HoldNotFoundError: If no hold has that key.
    """
    result = await session.execute(
        select(AllowanceHold).where(AllowanceHold.hold_key == hold_key)
    )
    hold = result.scalar_one_or_none()
    if hold is None:
        raise HoldNotFoundError(f"No allowance hold with key {hold_key!r}")
    return hold


async def reserve(
    session: AsyncSession,
    *,
    hold_key: str,
    capability: str,
    app_name: str,
    units: int,
) -> AllowanceHold:
    """Claim `units` of a capability's remaining allowance for this run.

    Google-style docstring per project convention.

    Args:
        session: An async SQLAlchemy session.
        hold_key: The run's own identifier. The table's primary key, so a
            retried request cannot reserve the same budget twice.
        capability: The capability being held.
        app_name: The app making the reservation.
        units: How many provider calls the run intends to make.

    Returns:
        The created hold, in state `reserved`.

    Raises:
        HoldStateError: If a hold with this key already exists. Refused rather
            than overwritten: a second reservation under the same key would
            silently release the first one's claim.
    """
    existing = await session.execute(
        select(AllowanceHold).where(AllowanceHold.hold_key == hold_key)
    )
    if existing.scalar_one_or_none() is not None:
        raise HoldStateError(f"Allowance hold {hold_key!r} already exists")

    hold = AllowanceHold(
        hold_key=hold_key,
        capability=capability,
        app_name=app_name,
        units=units,
        window_start=utc_window(),
        state=STATE_RESERVED,
    )
    session.add(hold)
    await session.commit()

    logger.info(
        "allowance_hold_reserved",
        hold_key=hold_key,
        capability=capability,
        app_name=app_name,
        units=units,
    )
    return hold


async def _transition(
    session: AsyncSession, hold_key: str, *, to_state: str, event: str
) -> AllowanceHold:
    """Move a reserved hold to a terminal state.

    Args:
        session: An async SQLAlchemy session.
        hold_key: The hold's key.
        to_state: `redeemed` or `refunded`.
        event: The structlog event name to emit.

    Returns:
        The updated hold.

    Raises:
        HoldNotFoundError: If no hold has that key.
        HoldStateError: If the hold is not currently reserved.
    """
    hold = await _load(session, hold_key)
    if hold.state != STATE_RESERVED:
        raise HoldStateError(
            f"Allowance hold {hold_key!r} is {hold.state}, not {STATE_RESERVED}"
        )

    hold.state = to_state
    hold.updated_at = datetime.now(UTC)
    await session.commit()

    logger.info(event, hold_key=hold_key, capability=hold.capability, units=hold.units)
    return hold


async def redeem(session: AsyncSession, hold_key: str) -> AllowanceHold:
    """Mark a hold as spent, because the calls were made.

    Args:
        session: An async SQLAlchemy session.
        hold_key: The hold's key.

    Returns:
        The hold, in state `redeemed`.

    Raises:
        HoldNotFoundError: If no hold has that key.
        HoldStateError: If the hold is not currently reserved.
    """
    return await _transition(
        session, hold_key, to_state=STATE_REDEEMED, event="allowance_hold_redeemed"
    )


async def refund(session: AsyncSession, hold_key: str) -> AllowanceHold:
    """Release a hold, because the run will not spend it.

    Args:
        session: An async SQLAlchemy session.
        hold_key: The hold's key.

    Returns:
        The hold, in state `refunded`.

    Raises:
        HoldNotFoundError: If no hold has that key.
        HoldStateError: If the hold is not currently reserved.
    """
    return await _transition(
        session, hold_key, to_state=STATE_REFUNDED, event="allowance_hold_refunded"
    )


async def expire_stale_holds(
    session: AsyncSession, *, older_than: timedelta = HOLD_EXPIRY
) -> list[str]:
    """Refund reserved holds that have sat unresolved for too long.

    Without this a visitor who closes the tab between the delegation decision
    and the dispatch confirmation holds budget nobody can use. Sweeping them
    back is what keeps an abandoned run from costing the showcase the same as a
    completed one.

    Args:
        session: An async SQLAlchemy session.
        older_than: How old a reserved hold must be to be swept.

    Returns:
        The keys refunded, so a caller can report how many were reclaimed.
    """
    cutoff = datetime.now(UTC) - older_than

    result = await session.execute(
        select(AllowanceHold).where(
            AllowanceHold.state == STATE_RESERVED,
            AllowanceHold.created_at < cutoff,
        )
    )
    stale = list(result.scalars().all())

    for hold in stale:
        hold.state = STATE_REFUNDED
        hold.updated_at = datetime.now(UTC)

    if stale:
        await session.commit()
        logger.info(
            "allowance_holds_expired",
            count=len(stale),
            older_than_minutes=int(older_than.total_seconds() // 60),
        )

    return [hold.hold_key for hold in stale]
