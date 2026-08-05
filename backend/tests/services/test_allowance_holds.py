# Built with Spec4 AI - https://spec4.ai
"""Reserve, redeem, refund and expiry against the allowance-hold ledger.

The state machine is small and its rules are all about not releasing budget
twice: only a `reserved` hold may become terminal, and a hold that was only
ever redeemed would make an abandoned run cost the showcase the same as a
completed one.

Follows the repo's fake-session convention -- ignore the SQL, pop canned results
in call order -- and `asyncio.run()` in sync tests, since this repo has no
pytest-asyncio.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from backend.app.db.models import AllowanceHold
from backend.app.services import allowance_holds
from backend.app.services.allowance_holds import (
    HOLD_EXPIRY,
    STATE_REDEEMED,
    STATE_REFUNDED,
    STATE_RESERVED,
    HoldNotFoundError,
    HoldStateError,
    expire_stale_holds,
    redeem,
    refund,
    reserve,
)


class _Result:
    def __init__(self, scalar: object = None, rows: list[object] | None = None) -> None:
        self._scalar = scalar
        self._rows = rows or []

    def scalar_one_or_none(self) -> object:
        return self._scalar

    def scalars(self) -> _Result:
        return self

    def all(self) -> list[object]:
        return self._rows


class _Session:
    def __init__(self, queued: list[_Result] | None = None) -> None:
        self._queue = list(queued or [])
        self.added: list[object] = []
        self.commits = 0

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def execute(self, *_a: object, **_k: object) -> _Result:
        return self._queue.pop(0) if self._queue else _Result()

    async def commit(self) -> None:
        self.commits += 1


def _hold(
    state: str = STATE_RESERVED, *, age: timedelta = timedelta()
) -> AllowanceHold:
    return AllowanceHold(
        hold_key="run-1",
        capability="generation",
        app_name="Orchestrated-Subagents Example App",
        units=3,
        window_start=datetime.now(UTC).replace(minute=0, second=0, microsecond=0),
        state=state,
        created_at=datetime.now(UTC) - age,
    )


class TestReserve:
    def test_it_creates_a_reserved_hold(self) -> None:
        session: Any = _Session(queued=[_Result(scalar=None)])

        hold = asyncio.run(
            reserve(
                session,
                hold_key="run-1",
                capability="generation",
                app_name="Test App",
                units=3,
            )
        )

        assert hold.state == STATE_RESERVED
        assert hold.units == 3
        assert hold in session.added
        assert session.commits == 1

    def test_it_stamps_the_hold_with_the_current_usage_window(self) -> None:
        # A hold does not outlive the window it was taken in: once the gate has
        # rolled over there is nothing left to redeem.
        session: Any = _Session(queued=[_Result(scalar=None)])

        hold = asyncio.run(
            reserve(
                session,
                hold_key="run-1",
                capability="generation",
                app_name="A",
                units=1,
            )
        )

        assert hold.window_start == allowance_holds.utc_window()  # type: ignore[attr-defined]  # reaching the module's own import on purpose -- patch/identity at point of use

    def test_a_duplicate_key_is_refused_rather_than_overwritten(self) -> None:
        """The primary key is the run's own id, which is what makes a retry safe.

        Overwriting would silently release the first reservation's claim while
        appearing to succeed.
        """
        session: Any = _Session(queued=[_Result(scalar=_hold())])

        with pytest.raises(HoldStateError):
            asyncio.run(
                reserve(
                    session,
                    hold_key="run-1",
                    capability="generation",
                    app_name="A",
                    units=3,
                )
            )


class TestTransitions:
    def test_a_reserved_hold_can_be_redeemed(self) -> None:
        hold = _hold()
        session: Any = _Session(queued=[_Result(scalar=hold)])

        asyncio.run(redeem(session, "run-1"))

        assert hold.state == STATE_REDEEMED
        assert hold.updated_at is not None

    def test_a_reserved_hold_can_be_refunded(self) -> None:
        hold = _hold()
        session: Any = _Session(queued=[_Result(scalar=hold)])

        asyncio.run(refund(session, "run-1"))

        assert hold.state == STATE_REFUNDED

    @pytest.mark.parametrize("terminal", [STATE_REDEEMED, STATE_REFUNDED])
    def test_a_terminal_hold_cannot_be_redeemed_again(self, terminal: str) -> None:
        """Not idempotent, deliberately: each release frees budget once."""
        session: Any = _Session(queued=[_Result(scalar=_hold(terminal))])

        with pytest.raises(HoldStateError):
            asyncio.run(redeem(session, "run-1"))

    @pytest.mark.parametrize("terminal", [STATE_REDEEMED, STATE_REFUNDED])
    def test_a_terminal_hold_cannot_be_refunded_again(self, terminal: str) -> None:
        session: Any = _Session(queued=[_Result(scalar=_hold(terminal))])

        with pytest.raises(HoldStateError):
            asyncio.run(refund(session, "run-1"))

    def test_an_unknown_key_is_a_different_error_from_a_bad_state(self) -> None:
        # "never reserved" and "already redeemed" are different bugs in the
        # caller, and one exception type would hide which.
        session: Any = _Session(queued=[_Result(scalar=None)])

        with pytest.raises(HoldNotFoundError):
            asyncio.run(redeem(session, "missing"))


class TestExpiry:
    def test_a_fifteen_minute_old_reserved_hold_is_refunded(self) -> None:
        """A tab closed mid-run must not hold budget for the rest of the window."""
        stale = _hold(age=HOLD_EXPIRY + timedelta(seconds=1))
        session: Any = _Session(queued=[_Result(rows=[stale])])

        refunded = asyncio.run(expire_stale_holds(session))

        assert refunded == ["run-1"]
        assert stale.state == STATE_REFUNDED
        assert session.commits == 1

    def test_the_expiry_window_is_fifteen_minutes(self) -> None:
        assert HOLD_EXPIRY == timedelta(minutes=15)

    def test_nothing_stale_means_nothing_written(self) -> None:
        # No commit when there is nothing to change, so a sweep on a quiet
        # showcase is free.
        session: Any = _Session(queued=[_Result(rows=[])])

        refunded = asyncio.run(expire_stale_holds(session))

        assert refunded == []
        assert session.commits == 0


class TestNotAToolSurface:
    def test_none_of_these_functions_are_registered_as_model_tools(self) -> None:
        """Deterministic internal calls only.

        Exposing any of them to a model would let generated output manipulate
        the budget that bounds it — the same reasoning that keeps the quota
        check out of the planning agent's tool surface.
        """
        import backend.app.orchestrated.runtime as runtime_module

        for module in (allowance_holds, runtime_module):
            source = (
                __import__("pathlib").Path(module.__file__).read_text(encoding="utf-8")
            )
            assert "tools=[" not in source
            assert "@agent.tool" not in source
