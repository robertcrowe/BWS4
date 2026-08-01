# Built with Spec4 AI - https://spec4.ai
"""Tests for the hourly reset window on usage_limits.

Before this window existed, `used` only ever incremented, so the cap settings
were lifetime totals: a public deployment stopped serving permanently once the
caps were reached, while still telling visitors to try again later. These tests
pin the reset so that regression can't silently return.

The window was per-UTC-day until v5 (migration 0009) and is per-UTC-hour now.
The assertions below are written against `shared.utc_window()` rather than
against a literal, so they measure the boundary the production code actually
uses -- but the *offsets* are hours, which is what makes them fail if the window
silently reverts to days.

Follows the repo's fake-session convention (canned results popped in call
order) and asyncio.run() rather than pytest-asyncio.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from backend.app.db.models import UsageLimit
from backend.app.services import shared


class _FakeExecuteResult:
    def __init__(self, scalar: object = None, all_rows: list[object] | None = None) -> None:
        self._scalar = scalar
        self._all_rows = all_rows or []

    def scalar_one_or_none(self) -> object:
        return self._scalar

    def scalars(self) -> "_FakeExecuteResult":
        return self

    def all(self) -> list[object]:
        return self._all_rows


class _FakeSession:
    def __init__(self, queued_results: list[_FakeExecuteResult] | None = None) -> None:
        self._queue = list(queued_results or [])
        self.added: list[object] = []
        self.commit_count = 0

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def execute(self, *_args: object, **_kwargs: object) -> _FakeExecuteResult:
        if self._queue:
            return self._queue.pop(0)
        return _FakeExecuteResult(scalar=None)

    async def commit(self) -> None:
        self.commit_count += 1


def _reserve(session: _FakeSession, capability: str = "search") -> None:
    asyncio.run(shared.reserve_capability(session, capability, app_name="Test App"))


def test_a_capability_exhausted_last_hour_serves_again_this_hour() -> None:
    """The whole point: the previous hour's total must not bar this visitor."""
    previous = shared.utc_window() - timedelta(hours=1)
    exhausted = UsageLimit(capability="search", used=30, cap=30, window_start=previous)
    session = _FakeSession(queued_results=[_FakeExecuteResult(scalar=exhausted)])

    _reserve(session)

    assert exhausted.used == 1, "counter should reset to 0 then take this hour's first unit"
    assert exhausted.window_start == shared.utc_window()


def test_an_exhausted_capability_still_rejects_within_the_same_hour() -> None:
    now = shared.utc_window()
    exhausted = UsageLimit(capability="search", used=30, cap=30, window_start=now)
    session = _FakeSession(queued_results=[_FakeExecuteResult(scalar=exhausted)])

    with pytest.raises(shared.ServiceUnavailableError):
        _reserve(session)

    assert exhausted.used == 30, "a rejected reservation must not consume a unit"


def test_a_partially_used_window_is_not_reset_mid_hour() -> None:
    limit = UsageLimit(
        capability="generation", used=7, cap=100, window_start=shared.utc_window()
    )
    session = _FakeSession(queued_results=[_FakeExecuteResult(scalar=limit)])

    _reserve(session, "generation")

    assert limit.used == 8


def test_a_stale_window_resets_even_when_far_in_the_past() -> None:
    """A service idle for months must not come back still exhausted."""
    long_ago = shared.utc_window() - timedelta(days=400)
    limit = UsageLimit(capability="generation", used=100, cap=100, window_start=long_ago)
    session = _FakeSession(queued_results=[_FakeExecuteResult(scalar=limit)])

    _reserve(session, "generation")

    assert limit.used == 1
    assert limit.window_start == shared.utc_window()


def test_a_new_row_starts_this_hours_window() -> None:
    session = _FakeSession(queued_results=[_FakeExecuteResult(scalar=None)])

    _reserve(session)

    created = [obj for obj in session.added if isinstance(obj, UsageLimit)][0]
    assert created.window_start == shared.utc_window()
    assert created.used == 1


def test_a_missing_window_fails_closed_rather_than_clearing_the_counter() -> None:
    """A null window must not be a backdoor that disables the cap.

    The column is NOT NULL in the database, so this only arises for an
    in-memory row -- but for a spend limit the unknown case has to fail
    closed, or a single nulled column silently grants unlimited quota.
    """
    limit = UsageLimit(capability="search", used=30, cap=30)
    assert limit.window_start is None
    session = _FakeSession(queued_results=[_FakeExecuteResult(scalar=limit)])

    with pytest.raises(shared.ServiceUnavailableError):
        _reserve(session)

    assert limit.used == 30
    assert limit.window_start == shared.utc_window(), "the window should be adopted, not the reset"


def test_the_unavailable_message_tells_the_visitor_when_it_recovers() -> None:
    """'Try again later' was a lie while the caps were lifetime totals."""
    message = str(shared.ServiceUnavailableError("search"))
    assert "this hour" in message
    assert "top of the hour" in message
    assert "today" not in message, "the window is hourly; daily copy would misinform"


def test_the_window_key_is_utc_not_local_time() -> None:
    """A local-time window would reset at a different instant per deployment.

    The failure this guards is subtle: on a machine running in, say, UTC+5:30 a
    naive implementation returns a wall-clock hour that is neither the server's
    nor UTC, so two instances of the same service would disagree about which
    window a request belongs to. `tzinfo` being UTC is what rules that out --
    a naive `datetime.now()` would have none.
    """
    window = shared.utc_window()

    assert window.tzinfo == timezone.utc
    assert (window.minute, window.second, window.microsecond) == (0, 0, 0)
    assert window == datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)


def test_two_reservations_in_the_same_hour_share_one_window() -> None:
    """Same hour, same counter -- the cap would be meaningless otherwise."""
    limit = UsageLimit(
        capability="generation", used=0, cap=100, window_start=shared.utc_window()
    )
    session = _FakeSession(
        queued_results=[
            _FakeExecuteResult(scalar=limit),
            _FakeExecuteResult(scalar=limit),
        ]
    )

    _reserve(session, "generation")
    first_window = limit.window_start
    _reserve(session, "generation")

    assert limit.used == 2, "the second reservation must add to the first, not reset it"
    assert limit.window_start == first_window
