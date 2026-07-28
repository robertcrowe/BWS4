# Built with Spec4 AI - https://spec4.ai
"""Tests for the daily reset window on usage_limits.

Before this window existed, `used` only ever incremented, so the
*_DAILY_LIMIT settings were lifetime totals: a public deployment stopped
serving permanently once the caps were reached, while still telling visitors
to try again later. These tests pin the reset so that regression can't
silently return.

Follows the repo's fake-session convention (canned results popped in call
order) and asyncio.run() rather than pytest-asyncio.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from backend.app.db.models import UsageLimit
from backend.app.db.session import get_db_session
from backend.app.main import app
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


def test_a_capability_exhausted_yesterday_serves_again_today() -> None:
    """The whole point: yesterday's total must not bar today's visitor."""
    yesterday = shared.utc_today() - timedelta(days=1)
    exhausted = UsageLimit(capability="search", used=30, cap=30, window_start=yesterday)
    session = _FakeSession(queued_results=[_FakeExecuteResult(scalar=exhausted)])

    _reserve(session)

    assert exhausted.used == 1, "counter should reset to 0 then take today's first unit"
    assert exhausted.window_start == shared.utc_today()


def test_an_exhausted_capability_still_rejects_within_the_same_day() -> None:
    today = shared.utc_today()
    exhausted = UsageLimit(capability="search", used=30, cap=30, window_start=today)
    session = _FakeSession(queued_results=[_FakeExecuteResult(scalar=exhausted)])

    with pytest.raises(shared.ServiceUnavailableError):
        _reserve(session)

    assert exhausted.used == 30, "a rejected reservation must not consume a unit"


def test_a_partially_used_window_is_not_reset_mid_day() -> None:
    today = shared.utc_today()
    limit = UsageLimit(capability="generation", used=7, cap=100, window_start=today)
    session = _FakeSession(queued_results=[_FakeExecuteResult(scalar=limit)])

    _reserve(session, "generation")

    assert limit.used == 8


def test_a_stale_window_resets_even_when_far_in_the_past() -> None:
    """A service idle for months must not come back still exhausted."""
    long_ago = shared.utc_today() - timedelta(days=400)
    limit = UsageLimit(capability="generation", used=100, cap=100, window_start=long_ago)
    session = _FakeSession(queued_results=[_FakeExecuteResult(scalar=limit)])

    _reserve(session, "generation")

    assert limit.used == 1
    assert limit.window_start == shared.utc_today()


def test_a_new_row_starts_todays_window() -> None:
    session = _FakeSession(queued_results=[_FakeExecuteResult(scalar=None)])

    _reserve(session)

    created = [obj for obj in session.added if isinstance(obj, UsageLimit)][0]
    assert created.window_start == shared.utc_today()
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
    assert limit.window_start == shared.utc_today(), "the window should be adopted, not the reset"


def test_console_status_reports_zero_used_for_a_stale_window() -> None:
    """The console must show today's budget, not a leftover total."""
    yesterday = shared.utc_today() - timedelta(days=1)
    stale = UsageLimit(capability="search", used=30, cap=30, window_start=yesterday)
    fresh = UsageLimit(
        capability="generation", used=4, cap=100, window_start=shared.utc_today()
    )
    session = _FakeSession(
        queued_results=[
            _FakeExecuteResult(all_rows=[fresh, stale]),
            _FakeExecuteResult(all_rows=[]),
        ]
    )

    async def _override_session() -> AsyncGenerator[_FakeSession, None]:
        yield session

    app.dependency_overrides[get_db_session] = _override_session
    try:
        with TestClient(app) as client:
            response = client.get("/api/console/status")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    rows = {row["capability"]: row for row in response.json()["usage_limits"]}
    assert rows["search"]["used"] == 0, "yesterday's exhausted counter is not today's usage"
    assert rows["search"]["window_start"] == yesterday.isoformat()
    assert rows["generation"]["used"] == 4


def test_the_unavailable_message_tells_the_visitor_when_it_recovers() -> None:
    """'Try again later' was a lie while the caps were lifetime totals."""
    message = str(shared.ServiceUnavailableError("search"))
    assert "today" in message
    assert "00:00 UTC" in message
