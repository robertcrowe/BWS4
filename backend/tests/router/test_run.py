# Built with Spec4 AI - https://spec4.ai
"""The Router run: admission order, refusals, holds and the staged stream.

The fixed order is the point. Moderation (free text only) runs before the hold,
the hold is taken before the router call, and a refusal is an HTTP error with
no stream, no hold and no run. Once admitted, the stream emits its stages in a
fixed order and settles every unit it did not spend -- including when the
visitor walks away mid-run.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Awaitable, Callable, Iterator
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.app.api import router as router_api
from backend.app.main import app
from backend.app.router import classifier, service, state
from backend.app.router.classifier import Classification, RoutingDecision
from backend.app.router.presets import RouterPreset, get_preset
from backend.app.router.run_schemas import RunRequest
from backend.app.services.moderation import (
    ModerationCategory,
    ModerationVerdict,
    get_stateless_moderator,
)

client = TestClient(app)


def _preset(preset_id: str) -> RouterPreset:
    preset = get_preset(preset_id)
    assert preset is not None
    return preset


P1 = _preset("p1")
P5 = _preset("p5")


def _decision(scores: dict[str, float], route: str, expr: str | None = None) -> Any:
    return RoutingDecision.model_validate(
        {"scores": scores, "route": route, "rationale": "Fits.", "expression": expr}
    )


def _scores(
    det: float = 0.0, single: float = 0.0, rag: float = 0.0, search: float = 0.0
) -> dict[str, float]:
    return {
        "deterministic_evaluator": det,
        "single_call": single,
        "retrieval": rag,
        "search_generation": search,
    }


class Recorder:
    """Records the order in which the gate, the hold and the router run."""

    def __init__(self) -> None:
        self.calls: list[str] = []


@pytest.fixture
def recorder(stub_generation: Any, stub_search: Any, stub_retrieval: Any) -> Recorder:
    """The call-order recorder; also stubs every route's provider."""
    return Recorder()


def _moderator(recorder: Recorder, category: ModerationCategory) -> Any:
    async def moderate(_text: str, _context: str) -> ModerationVerdict:
        recorder.calls.append("moderate")
        return ModerationVerdict(
            allowed=category is ModerationCategory.OK,
            category=category,
            visitor_message=f"verdict {category.value}",
        )

    return moderate


@pytest.fixture
def moderation(recorder: Recorder) -> Iterator[Callable[[ModerationCategory], None]]:
    def set_verdict(category: ModerationCategory) -> None:
        moderate = _moderator(recorder, category)

        async def provider() -> object:
            return moderate

        app.dependency_overrides[get_stateless_moderator] = provider

    set_verdict(ModerationCategory.OK)
    yield set_verdict
    app.dependency_overrides.pop(get_stateless_moderator, None)


def _classify_returning(
    recorder: Recorder, decision: RoutingDecision | None, store: Any = None
) -> Callable[..., Awaitable[Classification]]:
    async def classify(
        request: str, *, on_request: Callable[[], Awaitable[None]] | None = None
    ) -> Classification:
        recorder.calls.append("classify")
        if store is not None:
            hold = store.hold()
            recorder.calls.append(f"hold:{hold.state if hold else None}")
            recorder.calls.append(f"used:{store.used()}")
        if on_request is not None:
            await on_request()
        return Classification(
            decision=decision,
            model="test/model",
            elapsed_ms=7,
            failure=None if decision else "schema invalid",
        )

    return classify


def _events(body: str) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    for block in body.replace("\r\n", "\n").split("\n\n"):
        name = data = None
        for line in block.split("\n"):
            if line.startswith("event:"):
                name = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data = line.split(":", 1)[1].strip()
        if name and data:
            events.append((name, json.loads(data)))
    return events


def _post(body: dict[str, Any]) -> Any:
    return client.post("/api/router/run", json={"visit_id": "v1", **body})


class TestAdmissionOrder:
    def test_preset_skips_moderation_and_holds_two_units_before_the_router(
        self, router_store: Any, recorder: Recorder, moderation: Any
    ) -> None:
        store = router_store()
        decision = _decision(_scores(search=0.9, rag=0.3), "search_generation")
        with patch.object(
            classifier, "classify", _classify_returning(recorder, decision, store)
        ):
            response = _post({"request": P5.request, "preset_id": "p5"})

        assert response.status_code == 200
        assert "moderate" not in recorder.calls
        assert recorder.calls[:3] == ["classify", "hold:reserved", "used:2"]
        assert store.hold().units == 2

    def test_free_text_is_moderated_before_any_hold(
        self, router_store: Any, recorder: Recorder, moderation: Any
    ) -> None:
        store = router_store()
        decision = _decision(_scores(single=0.9), "single_call")
        with patch.object(
            classifier, "classify", _classify_returning(recorder, decision, store)
        ):
            response = _post({"request": "Write me a haiku about rain."})

        assert response.status_code == 200
        assert recorder.calls[0] == "moderate"
        assert recorder.calls[1:4] == ["classify", "hold:reserved", "used:2"]

    @pytest.mark.parametrize(
        ("category", "status", "code"),
        [
            (ModerationCategory.UNSAFE, 422, "moderation_blocked"),
            (ModerationCategory.UNAVAILABLE, 503, "moderation_unavailable"),
        ],
    )
    def test_moderation_refusal_is_an_http_error_with_no_hold(
        self,
        router_store: Any,
        recorder: Recorder,
        moderation: Any,
        category: ModerationCategory,
        status: int,
        code: str,
    ) -> None:
        store = router_store()
        moderation(category)
        with patch.object(classifier, "classify", _classify_returning(recorder, None)):
            response = _post({"request": "something unpleasant"})

        assert response.status_code == status
        assert response.json()["detail"]["code"] == code
        assert "classify" not in recorder.calls
        assert store.hold() is None
        assert store.used() == 0

    def test_shared_cap_refusal_names_the_shared_cap_and_holds_nothing(
        self, router_store: Any, recorder: Recorder, moderation: Any
    ) -> None:
        store = router_store(caps={"generation": 1})
        with patch.object(classifier, "classify", _classify_returning(recorder, None)):
            response = _post({"request": P1.request, "preset_id": "p1"})

        assert response.status_code == 429
        detail = response.json()["detail"]
        assert detail["code"] == "shared_cap_reached"
        assert "shared" in detail["message"]
        assert "not this app's 5-run limit" in detail["message"]
        assert "classify" not in recorder.calls
        assert store.hold() is None
        assert store.used() == 0

    def test_descriptions_not_ready_refuses_before_the_hold(
        self, router_store: Any, recorder: Recorder, moderation: Any
    ) -> None:
        store = router_store()
        state.reset_route_descriptions()

        async def unreachable(*_a: object) -> list[str]:
            raise ConnectionError("down")

        with (
            patch.object(state, "load_indexed_document_titles", unreachable),
            patch.object(classifier, "classify", _classify_returning(recorder, None)),
        ):
            response = _post({"request": P1.request, "preset_id": "p1"})

        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "descriptions_not_ready"
        assert store.hold() is None

    def test_mismatched_preset_text_is_refused(
        self, router_store: Any, recorder: Recorder, moderation: Any
    ) -> None:
        router_store()
        response = _post({"request": "Convert 1 km to m.", "preset_id": "p1"})
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "preset_mismatch"

    def test_blank_request_is_rejected(self, moderation: Any) -> None:
        assert _post({"request": "   "}).status_code == 422

    def test_over_long_request_is_rejected(self, moderation: Any) -> None:
        assert _post({"request": "x" * 301}).status_code == 422


class TestStream:
    def test_event_order_and_routed_ending(
        self, router_store: Any, recorder: Recorder, moderation: Any
    ) -> None:
        store = router_store()
        decision = _decision(_scores(search=0.9, rag=0.3), "search_generation")
        with patch.object(
            classifier, "classify", _classify_returning(recorder, decision)
        ):
            events = _events(_post({"request": P5.request, "preset_id": "p5"}).text)

        names = [name for name, _ in events]
        assert names == [
            "run_started",
            "stage",
            "decision",
            "stage",
            "answer",
            "run_end",
        ]
        decision_event = events[2][1]
        assert decision_event["kind"] == "routed"
        assert decision_event["chosen_route"] == "search_generation"
        assert len(decision_event["scores"]) == 4
        assert decision_event["agreement"] == "agreed"
        assert decision_event["expected_route"] == "search_generation"
        end = events[-1][1]
        assert end["ending"] == "routed_answer"
        assert end["units"] == {"reserved": 2, "used": 2, "released": 0}
        # Settled: the router's unit and the search route's generation call,
        # plus exactly one search against the separate search cap.
        assert store.used() == 2
        assert store.used("search") == 1
        assert store.hold().state == "redeemed"

    def test_misrouted_preset(
        self, router_store: Any, recorder: Recorder, moderation: Any
    ) -> None:
        router_store()
        decision = _decision(_scores(rag=0.9, search=0.3), "retrieval")
        with patch.object(
            classifier, "classify", _classify_returning(recorder, decision)
        ):
            events = _events(_post({"request": P5.request, "preset_id": "p5"}).text)

        assert events[2][1]["agreement"] == "misrouted"

    def test_low_confidence_card(
        self, router_store: Any, recorder: Recorder, moderation: Any
    ) -> None:
        router_store()
        decision = _decision(_scores(rag=0.62, search=0.55), "retrieval")
        with patch.object(
            classifier, "classify", _classify_returning(recorder, decision)
        ):
            events = _events(_post({"request": P5.request, "preset_id": "p5"}).text)

        card = events[2][1]
        assert card["kind"] == "low_confidence"
        assert card["chosen_route"] is None
        assert card["agreement"] == "declined"
        assert card["low_confidence"]["torn"] == ["retrieval", "search_generation"]
        assert card["low_confidence"]["dispatched"] == "retrieval"
        caveat = card["low_confidence"]["caveat"]
        assert "RAG over the space dataset" in caveat
        assert "Search + generate" in caveat
        assert "cheaper" in caveat
        assert "0.15" in caveat
        assert len(card["scores"]) == 4
        assert events[-1][1]["ending"] == "low_confidence"

    def test_malformed_decision_note(
        self, router_store: Any, recorder: Recorder, moderation: Any
    ) -> None:
        store = router_store()
        with patch.object(classifier, "classify", _classify_returning(recorder, None)):
            events = _events(_post({"request": P1.request, "preset_id": "p1"}).text)

        card = events[2][1]
        assert card["kind"] == "malformed"
        assert card["agreement"] is None
        assert card["dispatched_route"] == "single_call"
        assert "could not be read" in card["malformed_note"]
        end = events[-1][1]
        assert end["ending"] == "routed_answer"
        assert end["dispatched_route"] == "single_call"
        assert store.hold().state == "redeemed"

    def test_free_text_has_no_agreement(
        self, router_store: Any, recorder: Recorder, moderation: Any
    ) -> None:
        router_store()
        decision = _decision(_scores(single=0.9), "single_call")
        with patch.object(
            classifier, "classify", _classify_returning(recorder, decision)
        ):
            events = _events(_post({"request": "Tell me a joke."}).text)

        card = events[2][1]
        assert card["agreement"] is None
        assert card["expected_route"] is None

    def test_abandoned_run_refunds_everything(
        self, router_store: Any, stub_generation: Any
    ) -> None:
        store = router_store()

        async def scenario() -> None:
            admitted = await service.admit(
                RunRequest(request=P1.request, preset_id="p1", visit_id="v"),
                moderator=_moderator(Recorder(), ModerationCategory.OK),
            )
            assert store.used() == 2
            stream = service.stream_run(admitted)
            await anext(stream)  # run_started
            await stream.aclose()  # the visitor closed the tab

        asyncio.run(scenario())
        assert store.used() == 0
        assert store.hold().state == "refunded"


class TestStreamingRules:
    def test_no_request_scoped_session_on_the_run_path(self) -> None:
        assert not hasattr(router_api, "get_db_session")
        for function in (router_api.run, router_api._run_stream, service.stream_run):
            assert "Depends(" not in inspect.getsource(function).split('"""')[-1]

    def test_run_endpoint_takes_the_stateless_moderator(self) -> None:
        signature = inspect.signature(router_api.run)
        default = signature.parameters["moderator"].default
        assert default.dependency is get_stateless_moderator
