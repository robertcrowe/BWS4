# Built with Spec4 AI - https://spec4.ai
"""The comparison re-run: eligibility, trusted rechecks, units and history.

A re-run is a forced route, not a routing outcome: it never calls the router,
holds only the expected route's own cost, shows the router overhead as an
explicit zero, and writes nothing to either history.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.router import classifier, rerun, service
from backend.app.router.classifier import Classification, RoutingDecision
from backend.app.router.decision import Malformed, decide
from backend.app.router.dispatch import plan
from backend.app.router.presets import RouterPreset, get_preset
from backend.app.router.run_schemas import RerunRequest, RunRequest
from backend.app.services.moderation import ModerationCategory, ModerationVerdict

client = TestClient(app)


def _preset(preset_id: str) -> RouterPreset:
    preset = get_preset(preset_id)
    assert preset is not None
    return preset


def _decision(route: str, expression: str | None = None) -> Any:
    base = {
        "deterministic_evaluator": 0.0,
        "single_call": 0.0,
        "retrieval": 0.0,
        "search_generation": 0.0,
    }
    base[route] = 0.9
    return RoutingDecision.model_validate(
        {"scores": base, "route": route, "rationale": "r", "expression": expression}
    )


async def _allow(_text: str, _context: str) -> ModerationVerdict:
    return ModerationVerdict(
        allowed=True, category=ModerationCategory.OK, visitor_message="ok"
    )


class ClassifyCounter:
    def __init__(self, decision: RoutingDecision | None) -> None:
        self.decision = decision
        self.calls = 0

    async def __call__(self, _r: str, *, on_request: Any = None) -> Classification:
        self.calls += 1
        if on_request is not None:
            await on_request()
        return Classification(
            decision=self.decision,
            model="m",
            elapsed_ms=600,
            failure=None if self.decision else "x",
        )


def _collect(stream: Any) -> dict[str, Any]:
    async def go() -> dict[str, Any]:
        events: dict[str, Any] = {"order": []}
        async for event in stream:
            events["order"].append(event.name)
            events[event.name] = event.payload
        return events

    return asyncio.run(go())


def _original(
    preset_id: str | None, decision: RoutingDecision | None, request: str | None = None
) -> tuple[dict[str, Any], ClassifyCounter]:
    counter = ClassifyCounter(decision)
    text = request or _preset(preset_id or "p1").request
    with patch.object(classifier, "classify", counter):
        admitted = asyncio.run(
            service.admit(
                RunRequest(request=text, preset_id=preset_id, visit_id="v"),
                moderator=_allow,
            )
        )
        events = _collect(service.stream_run(admitted))
    return events, counter


def _rerun(preset_id: str, original_run_id: str) -> dict[str, Any]:
    admitted = asyncio.run(
        service.admit_rerun(
            RerunRequest(
                preset_id=preset_id,
                original_run_id=uuid.UUID(original_run_id),
                visit_id="v",
            )
        )
    )
    return _collect(service.stream_rerun(admitted))


class TestEligibilityMatrix:
    def _routed(self, route: str) -> Any:
        return decide(
            Classification(decision=_decision(route), model="m", elapsed_ms=1)
        )

    @pytest.mark.parametrize(
        ("case", "preset_id", "dispatched", "eligible"),
        [
            ("agreed", "p2", "single_call", False),
            ("misrouted", "p5", "retrieval", True),
            ("declined, tie-break landed wrong", "p5", "retrieval", True),
            ("declined, lucky tie-break", "p3", "retrieval", False),
            ("evaluator fallback", "p1", "single_call", True),
            ("malformed fallback, expected elsewhere", "p4", "single_call", True),
            ("malformed fallback, expected single call", "p2", "single_call", False),
        ],
    )
    def test_preset_cases(
        self, case: str, preset_id: str, dispatched: Any, eligible: bool
    ) -> None:
        assert (
            rerun.is_eligible(preset=_preset(preset_id), dispatched_route=dispatched)
            is eligible
        ), case

    def test_free_text_is_never_eligible(self) -> None:
        assert not rerun.is_eligible(preset=None, dispatched_route="retrieval")

    def test_evaluator_fallback_plans_away_from_the_expected_route(self) -> None:
        outcome = self._routed("deterministic_evaluator")
        assert not isinstance(outcome, Malformed)
        assert plan(outcome).route == "single_call"  # no expression: rejected


class TestRerunFlow:
    def test_misrouted_p6_reruns_through_single_call_without_the_router(
        self, router_store: Any, stub_generation: Any
    ) -> None:
        store = router_store()
        # p6 misrouted to deterministic with an expression the evaluator accepts.
        original, counter = _original(
            "p6", _decision("deterministic_evaluator", "1 mi to km")
        )
        assert original["run_end"]["rerun_eligible"] is True
        assert original["answer"]["kind"] == "deterministic"
        rows_before = (list(store.agreement_rows), list(store.latency_rows))

        with patch.object(classifier, "classify", counter):
            events = _rerun("p6", original["run_end"]["run_id"])

        assert counter.calls == 1, "the router must not run for a re-run"
        assert events["order"] == ["run_started", "stage", "answer", "run_end"]
        assert events["run_started"]["is_rerun"] is True
        assert events["run_started"]["units_reserved"] == 1
        assert events["answer"]["route"] == "single_call"
        end = events["run_end"]
        assert end["is_rerun"] is True
        assert end["rerun_eligible"] is False
        assert end["original_run_id"] == original["run_end"]["run_id"]
        assert end["units"] == {"reserved": 1, "used": 1, "released": 0}
        assert end["cost_strip"]["overhead"] == {"model_calls": 0, "measured_ms": 0}
        assert end["cost_strip"]["saved_nothing"] is False
        assert (store.agreement_rows, store.latency_rows) == rows_before
        hold = store.holds[f"{original['run_end']['run_id']}:rerun"]
        assert hold.units == 1
        assert hold.state == "redeemed"

    def test_a_second_rerun_is_refused(
        self, router_store: Any, stub_generation: Any
    ) -> None:
        router_store()
        original, _ = _original(
            "p6", _decision("deterministic_evaluator", "1 mi to km")
        )
        run_id = original["run_end"]["run_id"]
        _rerun("p6", run_id)

        with pytest.raises(service.RunRefusedError) as refused:
            _rerun("p6", run_id)
        assert refused.value.code == "rerun_unknown"

    def test_the_hold_key_refuses_a_repeat_even_after_a_restart(
        self, router_store: Any, stub_generation: Any
    ) -> None:
        store = router_store()
        original, _ = _original(
            "p6", _decision("deterministic_evaluator", "1 mi to km")
        )
        run_id = original["run_end"]["run_id"]
        _rerun("p6", run_id)
        used = store.used()
        # A restart forgets tickets; simulate a stale ticket being re-issued.
        rerun.TICKETS.issue(uuid.UUID(run_id), "p6", "deterministic_evaluator")

        with pytest.raises(service.RunRefusedError) as refused:
            _rerun("p6", run_id)
        assert refused.value.code == "rerun_already_used"
        assert store.used() == used  # the refused re-run's unit was given back

    def test_an_agreed_run_cannot_be_rerun(
        self, router_store: Any, stub_generation: Any
    ) -> None:
        router_store()
        original, _ = _original("p2", _decision("single_call"))
        assert original["run_end"]["rerun_eligible"] is False

        with pytest.raises(service.RunRefusedError) as refused:
            _rerun("p2", original["run_end"]["run_id"])
        assert refused.value.code == "rerun_unknown"

    def test_free_text_cannot_be_rerun(
        self, router_store: Any, stub_generation: Any
    ) -> None:
        router_store()
        original, _ = _original(
            None, _decision("single_call"), request="Tell me a joke."
        )
        assert original["run_end"]["rerun_eligible"] is False
        with pytest.raises(service.RunRefusedError):
            _rerun("p2", original["run_end"]["run_id"])

    def test_the_client_cannot_claim_a_different_preset(
        self, router_store: Any, stub_generation: Any
    ) -> None:
        router_store()
        original, _ = _original(
            "p6", _decision("deterministic_evaluator", "1 mi to km")
        )

        with pytest.raises(service.RunRefusedError) as refused:
            _rerun("p2", original["run_end"]["run_id"])
        assert refused.value.code == "rerun_mismatch"

    def test_shared_cap_refuses_without_holding(
        self, router_store: Any, stub_generation: Any
    ) -> None:
        store = router_store()
        original, _ = _original(
            "p6", _decision("deterministic_evaluator", "1 mi to km")
        )
        store.limits["generation"].cap = store.used()  # the gate is now full
        run_id = original["run_end"]["run_id"]

        with pytest.raises(service.RunRefusedError) as refused:
            _rerun("p6", run_id)
        assert refused.value.code == "shared_cap_reached"
        assert f"{run_id}:rerun" not in store.holds
        # The ticket survives a cap refusal: the visitor may try again later.
        assert rerun.TICKETS.peek(uuid.UUID(run_id)) is not None

    def test_deterministic_rerun_uses_the_curated_expression_and_spends_nothing(
        self, router_store: Any, stub_generation: Any
    ) -> None:
        router_store()
        original, _ = _original("p1", _decision("single_call"))
        assert original["run_end"]["rerun_eligible"] is True

        events = _rerun("p1", original["run_end"]["run_id"])

        assert events["answer"]["kind"] == "deterministic"
        assert events["answer"]["value_display"] == "20 m/s"
        assert events["run_end"]["units"] == {"reserved": 1, "used": 0, "released": 1}
        assert len(stub_generation.calls) == 1  # the original run's only

    def test_search_rerun_writes_no_latency_row(
        self,
        router_store: Any,
        stub_retrieval: Any,
        stub_search: Any,
        stub_generation: Any,
    ) -> None:
        store = router_store()
        original, _ = _original("p5", _decision("retrieval"))
        assert original["run_end"]["rerun_eligible"] is True
        agreement_before = len(store.agreement_rows)

        events = _rerun("p5", original["run_end"]["run_id"])

        assert events["answer"]["route"] == "search_generation"
        assert events["answer"]["searches"] == 1
        assert store.used("search") == 1
        assert store.latency_rows == []
        assert len(store.agreement_rows) == agreement_before
        assert events["run_end"]["units"]["used"] == 1


class TestRerunEndpoint:
    def test_unknown_run_is_an_http_error(self) -> None:
        response = client.post(
            "/api/router/rerun",
            json={
                "preset_id": "p5",
                "original_run_id": str(uuid.uuid4()),
                "visit_id": "v",
            },
        )
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "rerun_unknown"

    def test_malformed_run_id_is_rejected(self) -> None:
        response = client.post(
            "/api/router/rerun",
            json={"preset_id": "p5", "original_run_id": "nope", "visit_id": "v"},
        )
        assert response.status_code == 422
