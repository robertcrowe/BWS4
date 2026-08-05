# Built with Spec4 AI - https://spec4.ai
"""Starting a run: the ordering, the refusal, and the refund.

The phase's risk assessment names three ways allowance logic goes subtly wrong
-- reserving after composing rather than before, forgetting the refund path,
and drifting from the shared UTC-hour window -- so each is asserted directly
rather than inferred from a happy path.

Follows the repo's fake-session convention: `execute()` pops pre-queued canned
results in call order, and row writes are checked on `session.added`. No
database is touched, and no provider exists to reach.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

import pytest

from backend.app.collab import runtime, service
from backend.app.collab.validation import (
    CODE_INVALID_WEIGHTING,
    CODE_UNKNOWN_SCENARIO,
    CODE_UNKNOWN_WEIGHTING,
)
from backend.app.services import shared

SCENARIO = "refurbished_laptops_school"


class _Result:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value


class _Session:
    """A fake session that returns pre-queued results in call order."""

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


def _begin(session: Any, **kwargs: Any) -> service.RunStart:
    """Run `begin_run` with sensible defaults."""
    params: dict[str, Any] = {
        "run_id": "run-1",
        "scenario_id": SCENARIO,
        "weighting_id": "lowest_price",
    }
    params.update(kwargs)
    return asyncio.run(service.begin_run(session, **params))


class TestTheOrderingIsValidateGateHoldCompose:
    def test_a_ready_run_reserves_the_whole_budget_before_composing(self) -> None:
        """The capability's rule: a run is never *begun* unless it can finish."""
        calls: list[str] = []

        async def _gate(*_a: object, **kwargs: object) -> None:
            calls.append(f"gate:{kwargs.get('units')}")

        async def _reserve(*_a: object, **kwargs: object) -> object:
            calls.append(f"hold:{kwargs.get('units')}")
            return object()

        def _compose(*_a: object, **_k: object) -> Any:
            calls.append("compose")
            from backend.app.collab.rfq import compose_rfq as real

            return real(*_a, **_k)  # type: ignore[arg-type]

        with (
            patch.object(shared, "reserve_capability", _gate),
            patch("backend.app.collab.service.allowance_holds.reserve", _reserve),
            patch.object(service, "compose_rfq", _compose),
        ):
            result = _begin(_Session())

        assert result.outcome is service.Outcome.READY
        units = service.RUN_HOLD_UNITS
        assert calls == [f"gate:{units}", f"hold:{units}", "compose"]

    def test_an_invalid_request_costs_nothing_at_all(self) -> None:
        """Neither the gate nor the hold is touched: an invalid scenario id
        should not spend, and should not leave a refund to remember."""
        gate = _never_called()
        reserve = _never_called()

        with (
            patch.object(shared, "reserve_capability", gate),
            patch("backend.app.collab.service.allowance_holds.reserve", reserve),
        ):
            result = _begin(_Session(), scenario_id="not_a_scenario")

        assert result.outcome is service.Outcome.INVALID_REQUEST
        assert result.code == CODE_UNKNOWN_SCENARIO
        assert result.quotation_request is None

    def test_a_capped_run_never_reaches_the_hold_or_the_composer(self) -> None:
        """Refused before stage 1, per the capability: cap exhaustion never
        produces a partial run."""
        reserve = _never_called()
        compose = _never_called_sync()

        async def _gate(*_a: object, **_k: object) -> None:
            raise shared.ServiceUnavailableError("the showcase is busy")

        with (
            patch.object(shared, "reserve_capability", _gate),
            patch("backend.app.collab.service.allowance_holds.reserve", reserve),
            patch.object(service, "compose_rfq", compose),
        ):
            result = _begin(_Session([None]))

        assert result.outcome is service.Outcome.USAGE_LIMIT_REACHED
        assert result.quotation_request is None


class TestTheReservation:
    def test_it_holds_the_whole_run_budget_in_one_call(self) -> None:
        """The run's whole ceiling, reserved once. Reserving in pieces would
        leave a gap where part is committed and the rest is refused."""
        seen: dict[str, Any] = {}

        async def _gate(*_a: object, **kwargs: object) -> None:
            seen["gate_units"] = kwargs.get("units")

        async def _reserve(*_a: object, **kwargs: object) -> object:
            seen["hold_units"] = kwargs.get("units")
            seen["hold_key"] = kwargs.get("hold_key")
            seen["capability"] = kwargs.get("capability")
            return object()

        with (
            patch.object(shared, "reserve_capability", _gate),
            patch("backend.app.collab.service.allowance_holds.reserve", _reserve),
        ):
            result = _begin(_Session(), run_id="run-xyz")

        assert seen["gate_units"] == service.RUN_HOLD_UNITS
        assert seen["hold_units"] == service.RUN_HOLD_UNITS
        # Keyed by the run, so a retried request cannot reserve twice.
        assert seen["hold_key"] == "run-xyz"
        # The same shared capability every other example draws on.
        assert seen["capability"] == shared.CAPABILITY_GENERATION
        assert result.hold_units == service.RUN_HOLD_UNITS

    def test_the_arithmetic_is_stated_rather_than_hardcoded(self) -> None:
        """The hold is the run ceiling, not a second count of the same steps.

        It used to be `NEGOTIATION_STAGE_CALLS + EXPLANATION_CALLS`, which was
        the right figure only while the run had no room for the repairs it
        actually makes. Deriving both from one constant is what stops a hold
        that promises less than the ceiling permits.
        """
        assert service.RUN_HOLD_UNITS == runtime.MAX_PROVIDER_REQUESTS
        assert service.RUN_HOLD_UNITS > (
            service.NEGOTIATION_STAGE_CALLS + service.EXPLANATION_CALLS
        ), "the run has no headroom for the repairs the sequencer makes"
        # What the visitor is told is the negotiation, not the explanations and
        # not the headroom.
        assert service.VISITOR_FACING_CALL_COUNT == 6


class TestTheCapRefusalIsDistinguishable:
    def test_it_carries_remaining_allowance_and_a_reset_time(self) -> None:
        """Never a generic error: the capability requires the visitor be told
        how much is left and when it comes back."""

        class _Row:
            capability = shared.CAPABILITY_GENERATION
            used = 22
            cap = 25
            window_start = shared.utc_window()

        async def _gate(*_a: object, **_k: object) -> None:
            raise shared.ServiceUnavailableError("no room this hour")

        with patch.object(shared, "reserve_capability", _gate):
            result = _begin(_Session([_Row()]))

        assert result.outcome is service.Outcome.USAGE_LIMIT_REACHED
        assert result.allowance is not None
        assert result.allowance.remaining == 3
        assert result.allowance.cap == 25
        assert result.visitor_message

    def test_a_stale_window_is_read_as_zero_used(self) -> None:
        """The documented way to get this wrong: a reader that skipped the
        strictly-older comparison would report last hour's leftover as this
        hour's figure."""
        from datetime import timedelta

        class _StaleRow:
            capability = shared.CAPABILITY_GENERATION
            used = 25
            cap = 25
            window_start = shared.utc_window() - timedelta(hours=3)

        allowance = asyncio.run(service.read_allowance(_Session([_StaleRow()])))  # type: ignore[arg-type]

        assert allowance.remaining == 25

    def test_the_two_refusals_are_different_outcomes(self) -> None:
        """One the visitor fixes by choosing differently; the other they can
        only wait out."""
        assert (
            service.Outcome.INVALID_REQUEST is not service.Outcome.USAGE_LIMIT_REACHED  # type: ignore[comparison-overlap]  # distinctness is the assertion: two enum members given the same value would alias at runtime
        )


class TestValidationRefusesBeforeAnythingIsSpent:
    @pytest.mark.parametrize(
        ("kwargs", "code"),
        [
            ({"scenario_id": "nope"}, CODE_UNKNOWN_SCENARIO),
            ({"weighting_id": "nope"}, CODE_UNKNOWN_WEIGHTING),
            (
                {"weighting_id": None, "weights": {"price": 50, "delivery": 50}},
                CODE_INVALID_WEIGHTING,
            ),
            (
                {
                    "weighting_id": None,
                    "weights": {
                        "price": 10,
                        "delivery": 10,
                        "quantity": 10,
                        "warranty": 10,
                    },
                },
                CODE_INVALID_WEIGHTING,
            ),
        ],
        ids=["bad-scenario", "bad-weighting-id", "short-vector", "wrong-total"],
    )
    def test_each_bad_input_is_refused_with_its_own_code(
        self, kwargs: dict[str, Any], code: str
    ) -> None:
        gate = _never_called()

        with patch.object(shared, "reserve_capability", gate):
            result = _begin(_Session(), **kwargs)

        assert result.outcome is service.Outcome.INVALID_REQUEST
        assert result.code == code

    def test_a_custom_vector_that_is_valid_is_accepted(self) -> None:
        async def _noop(*_a: object, **_k: object) -> Any:
            return None

        with (
            patch.object(shared, "reserve_capability", _noop),
            patch("backend.app.collab.service.allowance_holds.reserve", _noop),
        ):
            result = _begin(
                _Session(),
                weighting_id=None,
                weights={
                    "price": 40,
                    "delivery": 30,
                    "quantity": 20,
                    "warranty": 10,
                },
            )

        assert result.outcome is service.Outcome.READY
        assert result.weighting is not None
        assert result.weighting.id == "custom"


class TestTheRefundPath:
    def test_reserved_units_are_released_when_a_run_fails(self) -> None:
        released: list[str] = []

        async def _refund(_session: object, hold_key: str) -> object:
            released.append(hold_key)
            return object()

        with patch("backend.app.collab.service.allowance_holds.refund", _refund):
            done = asyncio.run(
                service.abandon_run(_Session(), "run-1", reason="seller_failed")  # type: ignore[arg-type]
            )

        assert done is True
        assert released == ["run-1"]

    def test_a_missing_hold_does_not_raise_on_the_failure_path(self) -> None:
        """This is called from exception handlers. A refund that raised would
        turn one failure into two and lose the partial result."""

        async def _refund(*_a: object, **_k: object) -> object:
            raise service.allowance_holds.HoldNotFoundError("gone")  # type: ignore[attr-defined]  # reaching the module's own import on purpose -- patch/identity at point of use

        with patch("backend.app.collab.service.allowance_holds.refund", _refund):
            done = asyncio.run(
                service.abandon_run(_Session(), "run-1", reason="x")  # type: ignore[arg-type]
            )

        assert done is False

    def test_an_already_redeemed_hold_is_not_refunded_twice(self) -> None:
        async def _refund(*_a: object, **_k: object) -> object:
            raise service.allowance_holds.HoldStateError("already redeemed")  # type: ignore[attr-defined]  # reaching the module's own import on purpose -- patch/identity at point of use

        with patch("backend.app.collab.service.allowance_holds.refund", _refund):
            done = asyncio.run(
                service.abandon_run(_Session(), "run-1", reason="x")  # type: ignore[arg-type]
            )

        assert done is False


def _never_called() -> Any:
    async def _fail(*_a: object, **_k: object) -> Any:
        raise AssertionError("should not have been reached")

    return _fail


def _never_called_sync() -> Any:
    def _fail(*_a: object, **_k: object) -> Any:
        raise AssertionError("should not have been reached")

    return _fail
