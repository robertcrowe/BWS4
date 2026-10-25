# Built with Spec4 AI - https://spec4.ai
"""Deterministic and single-call dispatch, and the units each path spends.

Driven through the real `admit` and `stream_run` with only the classification
call and the generation service stubbed, so the hold, the early release, the
evaluator gate and the settle are all production code.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

import pytest

from backend.app.router import classifier, dispatch, service
from backend.app.router.classifier import Classification, RoutingDecision
from backend.app.router.decision import Malformed, decide
from backend.app.router.evaluator import Accepted, Rejected
from backend.app.router.run_schemas import RunRequest
from backend.app.router.single_call_route import truncate_at_sentence
from backend.app.services import generation
from backend.app.services.moderation import ModerationCategory, ModerationVerdict
from backend.app.services.untrusted import BLOCK_OPEN


def _scores(
    det: float = 0.0, single: float = 0.0, rag: float = 0.0, search: float = 0.0
) -> dict[str, float]:
    return {
        "deterministic_evaluator": det,
        "single_call": single,
        "retrieval": rag,
        "search_generation": search,
    }


def _decision(
    scores: dict[str, float], route: str, expression: str | None = None
) -> RoutingDecision:
    return RoutingDecision.model_validate(
        {
            "scores": scores,
            "route": route,
            "rationale": "Fits.",
            "expression": expression,
        }
    )


async def _allow(_text: str, _context: str) -> ModerationVerdict:
    return ModerationVerdict(
        allowed=True, category=ModerationCategory.OK, visitor_message="ok"
    )


def _run(
    decision: RoutingDecision | None,
    *,
    request: str,
    preset_id: str | None = None,
) -> dict[str, Any]:
    """Admit and stream one run; return its events by name."""

    async def classify(_request: str, *, on_request: Any = None) -> Classification:
        if on_request is not None:
            await on_request()
        return Classification(
            decision=decision,
            model="test/router",
            elapsed_ms=5,
            failure=None if decision else "invalid",
        )

    async def scenario() -> dict[str, Any]:
        admitted = await service.admit(
            RunRequest(request=request, preset_id=preset_id, visit_id="v"),
            moderator=_allow,
        )
        events: dict[str, Any] = {"order": []}
        async for event in service.stream_run(admitted):
            events["order"].append(event.name)
            events[event.name] = event.payload
        return events

    with patch.object(classifier, "classify", classify):
        return asyncio.run(scenario())


P1 = "Convert 72 km/h to metres per second."
P2 = 'Rewrite "hey, can u send me the report asap" so it sounds professional.'
P6 = "Explain why 1 mile is about 1.609 kilometres."


class TestDeterministicRoute:
    def test_accepted_expression_releases_the_second_unit_and_calls_no_model(
        self, router_store: Any, stub_generation: Any
    ) -> None:
        store = router_store()
        decision = _decision(
            _scores(det=0.95, single=0.1), "deterministic_evaluator", "72 km/h to m/s"
        )
        events = _run(decision, request=P1, preset_id="p1")

        answer = events["answer"]
        assert answer["kind"] == "deterministic"
        assert answer["route"] == "deterministic_evaluator"
        assert answer["route_label"] == "Deterministic evaluator"
        assert answer["value_display"] == "20 m/s"
        assert answer["expression"] == "72 km/h to m/s"
        assert answer["evaluator_verdict"] == "accepted"
        assert stub_generation.calls == []
        assert events["run_end"]["units"] == {"reserved": 2, "used": 1, "released": 1}
        assert events["decision"]["agreement"] == "agreed"
        assert store.used() == 1
        assert store.hold().state == "redeemed"

    def test_rejected_expression_keeps_the_unit_and_falls_back_to_single_call(
        self, router_store: Any, stub_generation: Any
    ) -> None:
        store = router_store()
        decision = _decision(
            _scores(det=0.9, single=0.2), "deterministic_evaluator", "abs(72)"
        )
        events = _run(decision, request=P1, preset_id="p1")

        card = events["decision"]
        assert card["kind"] == "routed"
        assert card["chosen_route"] == "deterministic_evaluator"
        assert card["dispatched_route"] == "single_call"
        note = card["evaluator_fallback_note"]
        assert note.startswith(
            "The router chose the deterministic evaluator, but the evaluator "
            "could not compute the expression ("
        )
        assert note.endswith(
            "so the request was dispatched to single call. This is a misroute "
            "of the router's own making."
        )
        # Dispatched route differs from expected: the router's own misroute.
        assert card["agreement"] == "misrouted"
        assert events["answer"]["kind"] == "text"
        assert events["answer"]["route"] == "single_call"
        assert len(stub_generation.calls) == 1
        assert events["run_end"]["ending"] == "routed_answer"
        assert events["run_end"]["units"] == {"reserved": 2, "used": 2, "released": 0}
        assert store.used() == 2

    def test_missing_expression_is_a_rejection_not_a_crash(
        self, router_store: Any, stub_generation: Any
    ) -> None:
        router_store()
        decision = _decision(_scores(det=0.9), "deterministic_evaluator", None)
        events = _run(decision, request=P1, preset_id="p1")

        assert events["decision"]["dispatched_route"] == "single_call"
        assert "could not compute" in events["decision"]["evaluator_fallback_note"]

    def test_low_confidence_tie_on_deterministic_goes_to_the_other_torn_route(
        self, router_store: Any, stub_generation: Any
    ) -> None:
        router_store()
        # Scores torn between det and single; the model's expression is junk.
        decision = _decision(
            _scores(det=0.6, single=0.55), "deterministic_evaluator", "1 +"
        )
        events = _run(decision, request=P1, preset_id="p1")

        card = events["decision"]
        assert card["kind"] == "low_confidence"
        assert card["low_confidence"]["dispatched"] == "deterministic_evaluator"
        assert card["dispatched_route"] == "single_call"
        assert card["agreement"] == "declined"
        assert (
            "the other route the router was torn between"
            in (card["evaluator_fallback_note"])
        )
        assert "could not compute the expression" in card["evaluator_fallback_note"]
        assert events["run_end"]["ending"] == "low_confidence"
        assert events["run_end"]["units"]["used"] == 2

    def test_low_confidence_tie_on_deterministic_that_is_accepted(
        self, router_store: Any, stub_generation: Any
    ) -> None:
        router_store()
        decision = _decision(
            _scores(det=0.6, single=0.55), "deterministic_evaluator", "72 km/h to m/s"
        )
        events = _run(decision, request=P1, preset_id="p1")

        assert events["answer"]["kind"] == "deterministic"
        assert events["run_end"]["ending"] == "low_confidence"
        assert events["run_end"]["units"] == {"reserved": 2, "used": 1, "released": 1}


class TestSingleCallRoute:
    def test_preset_2_is_answered_by_single_call_with_two_units(
        self, router_store: Any, stub_generation: Any
    ) -> None:
        store = router_store()
        stub_generation.text = "Could you send me the report when you have a moment?"
        events = _run(
            _decision(_scores(single=0.9), "single_call"), request=P2, preset_id="p2"
        )

        answer = events["answer"]
        assert answer["kind"] == "text"
        assert answer["route_label"] == "Single call"
        assert answer["text"].startswith("Could you send me the report")
        assert answer["model"] == "stub/model"
        assert answer["elapsed_ms"] >= 0
        assert events["run_end"]["units"] == {"reserved": 2, "used": 2, "released": 0}
        assert store.used() == 2

    def test_preset_6_end_to_end(self, router_store: Any, stub_generation: Any) -> None:
        router_store()
        events = _run(
            _decision(_scores(det=0.2, single=0.85), "single_call"),
            request=P6,
            preset_id="p6",
        )

        assert events["order"] == [
            "run_started",
            "stage",
            "decision",
            "stage",
            "answer",
            "run_end",
        ]
        assert events["decision"]["agreement"] == "agreed"
        assert events["answer"]["route"] == "single_call"

    def test_request_is_delimited_and_carries_no_router_internals(
        self, router_store: Any, stub_generation: Any
    ) -> None:
        router_store()
        _run(_decision(_scores(single=0.9), "single_call"), request=P2, preset_id="p2")

        call = stub_generation.calls[0]
        assert call["user_prompt"].startswith(BLOCK_OPEN)
        assert P2 in call["user_prompt"]
        for internal in ("deterministic_evaluator", "search_generation", "score"):
            assert internal not in call["system_prompt"]

    def test_failure_refunds_and_shows_an_error_without_an_answer(
        self, router_store: Any, stub_generation: Any
    ) -> None:
        store = router_store()
        stub_generation.error = generation.GenerationServiceError("chain exhausted")
        events = _run(
            _decision(_scores(single=0.9), "single_call"), request=P2, preset_id="p2"
        )

        answer = events["answer"]
        assert answer["kind"] == "failure"
        assert answer["text"] is None
        assert "could not produce an answer" in answer["error"]
        assert events["run_end"]["ending"] == "routed_answer"
        assert events["run_end"]["units"] == {"reserved": 2, "used": 1, "released": 1}
        assert store.used() == 1
        assert store.hold().state == "redeemed"

    def test_malformed_decision_goes_to_single_call(
        self, router_store: Any, stub_generation: Any
    ) -> None:
        router_store()
        events = _run(None, request=P2, preset_id="p2")

        assert events["decision"]["kind"] == "malformed"
        assert events["decision"]["agreement"] is None
        assert events["answer"]["route"] == "single_call"
        assert events["run_end"]["ending"] == "routed_answer"


class TestUnitCeiling:
    @pytest.mark.parametrize(
        ("decision", "request_text", "preset_id"),
        [
            (_decision(_scores(det=0.9), "deterministic_evaluator", "1+1"), P1, "p1"),
            (_decision(_scores(det=0.9), "deterministic_evaluator", "x"), P1, "p1"),
            (_decision(_scores(single=0.9), "single_call"), P2, "p2"),
            (_decision(_scores(det=0.6, single=0.6), "single_call"), P6, "p6"),
            (None, P2, "p2"),
        ],
    )
    def test_no_run_exceeds_two_units(
        self,
        router_store: Any,
        stub_generation: Any,
        decision: RoutingDecision | None,
        request_text: str,
        preset_id: str,
    ) -> None:
        store = router_store()
        events = _run(decision, request=request_text, preset_id=preset_id)

        units = events["run_end"]["units"]
        assert units["used"] <= 2
        assert units["used"] + units["released"] == units["reserved"] == 2
        assert store.used() == units["used"]


class TestPlan:
    def test_malformed_plans_to_single_call(self) -> None:
        planned = dispatch.plan(Malformed(failure="x"))
        assert planned.route == "single_call"
        assert planned.evaluation is None

    def test_accepted_deterministic_plan(self) -> None:
        outcome = decide(
            Classification(
                decision=_decision(_scores(det=0.9), "deterministic_evaluator", "2*3"),
                model="m",
                elapsed_ms=1,
            )
        )
        planned = dispatch.plan(outcome)
        assert planned.route == "deterministic_evaluator"
        assert isinstance(planned.evaluation, Accepted)
        assert not planned.evaluator_fallback

    def test_rejected_deterministic_plan(self) -> None:
        outcome = decide(
            Classification(
                decision=_decision(_scores(det=0.9), "deterministic_evaluator", "1/0"),
                model="m",
                elapsed_ms=1,
            )
        )
        planned = dispatch.plan(outcome)
        assert planned.route == "single_call"
        assert isinstance(planned.evaluation, Rejected)
        assert planned.evaluator_fallback


class TestTruncation:
    def test_short_answers_are_untouched(self) -> None:
        assert truncate_at_sentence("One. Two.", 50) == ("One. Two.", False)

    def test_long_answers_are_cut_at_a_sentence_with_an_ellipsis(self) -> None:
        text, cut = truncate_at_sentence("First sentence. Second one is long.", 25)
        assert cut
        assert text == "First sentence. …"
