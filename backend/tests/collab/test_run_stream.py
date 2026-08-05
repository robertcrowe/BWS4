# Built with Spec4 AI - https://spec4.ai
"""`stream_run`: the refusal paths, and what a completed run persists.

The refusal cases are asserted here rather than by exhausting the real hourly
allowance, which the phase's verification suggests. Draining the shared gate
would take **every** example app in the showcase dark for the rest of the hour
-- RAG, tool use, single call, chained calls, planning and orchestrated all
draw on the same counter. The property under test is that a refusal happens
before stage 1 and carries a distinguishable message, and that is exactly what
a substituted gate shows.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

from backend.app.collab import service
from backend.app.services import shared


class _Result:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value


class _Session:
    """The repo's fake-session convention: canned results in call order."""

    def __init__(self, results: list[Any] | None = None) -> None:
        self.queued = list(results or [])
        self.added: list[Any] = []
        self.commits = 0

    async def execute(self, *_a: object, **_k: object) -> _Result:
        return _Result(self.queued.pop(0) if self.queued else None)

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.commits += 1


def _collect(session: Any, **kwargs: Any) -> list[Any]:
    params: dict[str, Any] = {
        "run_id": "run-1",
        "scenario_id": "refurbished_laptops_school",
        "weighting_id": "lowest_price",
    }
    params.update(kwargs)

    async def _go() -> list[Any]:
        return [event async for event in service.stream_run(session, **params)]

    return asyncio.run(_go())


class TestACappedRunIsRefusedBeforeStageOne:
    def test_it_yields_exactly_one_error_event_and_no_stages(self) -> None:
        class _Row:
            capability = shared.CAPABILITY_GENERATION
            used = 24
            cap = 25
            window_start = shared.utc_window()

        async def _gate(*_a: object, **_k: object) -> None:
            raise shared.ServiceUnavailableError("the showcase is busy this hour")

        with patch.object(shared, "reserve_capability", _gate):
            events = _collect(_Session([_Row()]))

        assert len(events) == 1
        assert events[0].kind == "error"
        assert events[0].payload["outcome"] == "usage_limit_reached"

    def test_the_cap_message_carries_what_is_left_and_when_it_returns(self) -> None:
        """Distinguishable from a service problem: the visitor is told they
        cannot fix this and roughly when it comes back."""

        class _Row:
            capability = shared.CAPABILITY_GENERATION
            used = 24
            cap = 25
            window_start = shared.utc_window()

        async def _gate(*_a: object, **_k: object) -> None:
            raise shared.ServiceUnavailableError("busy")

        with patch.object(shared, "reserve_capability", _gate):
            events = _collect(_Session([_Row()]))

        payload = events[0].payload
        assert payload["remaining"] == 1
        assert payload["cap"] == 25
        assert payload["resets_at"]

    def test_a_refused_run_persists_nothing(self) -> None:
        """ "Cap exhaustion never produces a partial run" -- so there must be no
        `negotiation_runs` row and no `peer_messages` rows to clean up."""
        session = _Session([None])

        async def _gate(*_a: object, **_k: object) -> None:
            raise shared.ServiceUnavailableError("busy")

        with patch.object(shared, "reserve_capability", _gate):
            _collect(session)

        assert session.added == []
        assert session.commits == 0


class TestAnInvalidRequestIsRefusedTheSameWay:
    def test_it_is_a_different_code_from_a_cap(self) -> None:
        """One the visitor fixes by choosing differently; the other they can
        only wait out."""
        events = _collect(_Session(), scenario_id="not_a_scenario")

        assert len(events) == 1
        assert events[0].payload["outcome"] == "invalid_request"
        assert events[0].payload["code"] == "unknown_scenario"
        # No allowance figures: nothing about the allowance was the problem.
        assert "remaining" not in events[0].payload

    def test_nothing_is_reserved_or_persisted(self) -> None:
        session = _Session()
        gate_calls: list[int] = []

        async def _gate(*_a: object, **kwargs: object) -> None:
            gate_calls.append(1)

        with patch.object(shared, "reserve_capability", _gate):
            _collect(session, scenario_id="not_a_scenario")

        assert gate_calls == []
        assert session.added == []
