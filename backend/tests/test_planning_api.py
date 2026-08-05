# Built with Spec4 AI - https://spec4.ai
"""The planning-agent app's HTTP surface: plan, then run.

Phase 1's version of this file tested a stub that streamed fixtures. What it
established about the *transport* still holds and is still tested here --
notably that `TestClient` cannot measure incremental delivery, because its
transport runs the whole app to completion into a `BytesIO` before returning.
Ordering and content go through `TestClient`; anything about *when* an event
arrives goes through `_drive_asgi`, which calls the ASGI app directly with a
timestamping `send`.

Models and Exa are mocked throughout, so no key and no database are needed.
"""

from __future__ import annotations

from typing import Any, Literal

import asyncio
import json
import time
from collections.abc import AsyncGenerator, AsyncIterator, Iterator, MutableMapping
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.app.api import planning as api
from backend.app.db.models import SearchQuery, ServiceLogEntry, UsageLimit
from backend.app.db.session import get_db_session
from backend.app.main import app
from backend.app.planning import service
from backend.app.planning.schemas import Itinerary, ItineraryBlock, Plan, StepResult
from backend.app.planning.service import ExecutionEvent, PlanOutcome
from backend.app.services import shared
from backend.app.services.moderation import ModerationCategory, ModerationVerdict


async def _allow_moderation(_text: str, _context: str) -> ModerationVerdict:
    """Stand in for the safety gate where it is called directly, not injected.

    `_stream` takes the moderator as an argument rather than reading a module
    global, because a response that outlives its handler must not hold a
    request-scoped dependency. That makes it a positional argument here.
    """
    return ModerationVerdict(
        allowed=True, category=ModerationCategory.OK, visitor_message="allowed"
    )


@pytest.fixture(autouse=True)
def _gate_allows_everything(allow_all_moderation: Any) -> None:
    """Every request here carries free text, which the shared gate now checks.

    The gate is not this file's subject, and with no `OPENAI_API_KEY` in the
    test environment it fails closed and would refuse all of them. Overridden
    per module rather than globally, so a test that *should* exercise the gate
    cannot pass by accident.
    """


client = TestClient(app)

GOAL = {"city": "Lisbon", "interests": "street food, modern art"}

PLAN = Plan.model_validate(
    {
        "goal": "One day in Lisbon for street food and modern art",
        "steps": [
            {
                "index": 1,
                "kind": "research",
                "description": "Street food",
                "search_query": "street food Lisbon",
            },
            {
                "index": 2,
                "kind": "research",
                "description": "Modern art",
                "search_query": "modern art Lisbon",
            },
            {
                "index": 3,
                "kind": "synthesis",
                "description": "Compose the day",
                "search_query": None,
            },
        ],
    }
)

ITINERARY = Itinerary(
    city="Lisbon",
    blocks=[
        ItineraryBlock(
            time_of_day="morning",
            activity="Time Out Market",
            why_it_matches="food",
            source_refs=[1],
        )
    ],
)


def _run_body(plan: Plan = PLAN) -> dict[str, Any]:
    return {**GOAL, "plan": plan.model_dump()}


def _step(
    index: int, status: Literal["completed", "failed"] = "completed"
) -> StepResult:
    return StepResult(step_index=index, status=status, summary=f"Result {index}", sources=[])


class _Result:
    def __init__(self, scalar: object = None) -> None:
        self._scalar = scalar

    def scalar_one_or_none(self) -> object:
        return self._scalar


class _Session:
    """Fake session whose usage rows persist, mirroring test_planning_orchestrator."""

    def __init__(self, caps: dict[str, int] | None = None) -> None:
        self.added: list[object] = []
        self.limits: dict[str, UsageLimit] = {}
        self._caps = caps or {}

    async def execute(self, statement: Any, *_a: object, **_k: object) -> _Result:
        try:
            capability = next(iter(statement.compile().params.values()))
        except Exception:  # noqa: BLE001 - fake session, best effort
            capability = None
        return _Result(self.limits.get(capability))

    def add(self, obj: object) -> None:
        self.added.append(obj)
        if isinstance(obj, UsageLimit):
            if obj.capability in self._caps:
                obj.cap = self._caps[obj.capability]
            self.limits[obj.capability] = obj

    async def commit(self) -> None:
        pass

    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    def used(self, capability: str) -> int:
        limit = self.limits.get(capability)
        return limit.used if limit else 0


def _override_session(session: Any) -> Any:
    """Install the fake session for `/plan`'s dependency."""

    async def _yield() -> AsyncGenerator[_Session, None]:
        yield session

    return _yield


def _patch_run_session(session: Any) -> Any:
    """Install the fake session for `/run`, which opens its own.

    `/run` deliberately does not use `Depends(get_db_session)` -- its response
    outlives the handler -- so it is patched at the factory instead, the same
    seam `test_embeddings_api.py` uses.
    """
    return patch.object(api, "async_session_factory", lambda: session)


def _stream(body: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """POST a run and collect its events, parsing the SSE wire format directly."""
    events: list[tuple[str, dict[str, Any]]] = []
    pending: str | None = None

    with client.stream("POST", "/api/planning/run", json=body) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")

        for line in response.iter_lines():
            if line.startswith("event:"):
                pending = line.removeprefix("event:").strip()
            elif line.startswith("data:") and pending is not None:
                events.append((pending, json.loads(line.removeprefix("data:").strip())))
                pending = None

    return events


def _execution(*events: ExecutionEvent) -> Any:
    """Build a fake `execute_plan` yielding the given events."""

    async def fake(_session: Any, *, goal: Any, plan: Any, calls_used: Any=0) -> AsyncIterator[Any]:
        for event in events:
            yield event

    return fake


def _completed_run() -> Any:
    return _execution(
        ExecutionEvent(kind="step_result", step_result=_step(1)),
        ExecutionEvent(kind="step_result", step_result=_step(2)),
        ExecutionEvent(kind="itinerary", itinerary=ITINERARY),
    )


class TestPlanEndpoint:
    def test_it_returns_the_validated_plan(self) -> None:
        session: Any = _Session()
        outcome = PlanOutcome(
            goal="goal",
            plan=PLAN,
            trimmed_note=None,
            replanned=False,
            model="groq/openai/gpt-oss-120b",
            calls_used=1,
        )
        app.dependency_overrides[get_db_session] = _override_session(session)
        try:
            with patch.object(service, "create_plan", return_value=outcome):
                response = client.post("/api/planning/plan", json=GOAL)
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        body = response.json()
        assert [step["index"] for step in body["plan"]["steps"]] == [1, 2, 3]
        assert body["plan"]["steps"][-1]["kind"] == "synthesis"
        assert body["calls_used"] == 1

    def test_it_fires_no_executor_call(self) -> None:
        """The human-in-the-loop checkpoint, as an assertion.

        `/plan` must reach the planner and nothing else. If this endpoint could
        execute a step, the visitor's review would be decorative.
        """
        session: Any = _Session()
        outcome = PlanOutcome(
            goal="goal", plan=PLAN, trimmed_note=None, replanned=False, model="m", calls_used=1
        )
        app.dependency_overrides[get_db_session] = _override_session(session)
        try:
            with (
                patch.object(service, "create_plan", return_value=outcome),
                patch.object(service, "execute_plan") as executed,
            ):
                client.post("/api/planning/plan", json=GOAL)
        finally:
            app.dependency_overrides.clear()

        executed.assert_not_called()

    def test_a_trimmed_plan_reports_what_was_dropped(self) -> None:
        session: Any = _Session()
        outcome = PlanOutcome(
            goal="goal",
            plan=PLAN,
            trimmed_note="Two steps were dropped.",
            replanned=True,
            model="m",
            calls_used=2,
        )
        app.dependency_overrides[get_db_session] = _override_session(session)
        try:
            with patch.object(service, "create_plan", return_value=outcome):
                body = client.post("/api/planning/plan", json=GOAL).json()
        finally:
            app.dependency_overrides.clear()

        assert body["trimmed_note"] == "Two steps were dropped."
        assert body["replanned"] is True

    @pytest.mark.parametrize(
        ("error", "status", "code"),
        [
            (service.InvalidGoalError("blank"), 422, "invalid_goal"),
            (service.UsageLimitReachedError("spent"), 503, "usage_limit_reached"),
            (service.PlanUnavailableError("no plan"), 503, "plan_unavailable"),
        ],
    )
    def test_failures_map_to_distinguishable_codes(
        self, error: Exception, status: int, code: str
    ) -> None:
        # A spent cap resets at the top of the hour and an unreachable planner does not.
        # An operator told only "503" learns neither.
        session: Any = _Session()
        app.dependency_overrides[get_db_session] = _override_session(session)
        try:
            with patch.object(service, "create_plan", side_effect=error):
                response = client.post("/api/planning/plan", json=GOAL)
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == status
        assert response.json()["code"] == code

    def test_an_over_long_city_is_rejected_by_the_schema(self) -> None:
        response = client.post(
            "/api/planning/plan", json={"city": "x" * 500, "interests": "food"}
        )

        assert response.status_code == 422


class TestRunStream:
    def test_it_streams_the_plan_then_each_step_then_the_itinerary(self) -> None:
        session: Any = _Session()

        with _patch_run_session(session), patch.object(
            service, "execute_plan", _completed_run()
        ):
            events = _stream(_run_body())

        assert [name for name, _ in events] == [
            "plan",
            "step_result",
            "step_result",
            "itinerary",
        ]

    def test_step_results_arrive_in_plan_order(self) -> None:
        session: Any = _Session()

        with _patch_run_session(session), patch.object(
            service, "execute_plan", _completed_run()
        ):
            events = _stream(_run_body())

        indices = [data["step_index"] for name, data in events if name == "step_result"]
        assert indices == [1, 2]

    def test_the_echoed_plan_is_what_will_actually_run(self) -> None:
        """Not what the client sent, if those differ.

        A plan arriving with more research steps than the budget allows is
        trimmed before execution, and the visitor must see the trimmed one --
        otherwise the screen promises steps that never run.
        """
        oversized = Plan.model_validate(
            {
                "goal": "One day in Lisbon",
                "steps": [
                    {
                        "index": i,
                        "kind": "research",
                        "description": f"r{i}",
                        "search_query": f"q{i}",
                    }
                    for i in range(1, 5)
                ]
                + [
                    {
                        "index": 5,
                        "kind": "synthesis",
                        "description": "s",
                        "search_query": None,
                    }
                ],
            }
        )
        session: Any = _Session()

        with _patch_run_session(session), patch.object(
            service, "execute_plan", _completed_run()
        ):
            events = _stream(_run_body(oversized))

        _, plan_event = events[0]
        assert len(plan_event["steps"]) == 3
        assert plan_event["trimmed_note"]

    def test_a_client_supplied_plan_is_revalidated_and_can_be_refused(self) -> None:
        """`/run` receives the plan as JSON, so it is untrusted input.

        Without re-checking, a caller could post a plan whose synthesis step is
        not last -- or twenty research steps -- and have this endpoint execute
        it. Nothing runs, and the refusal is an event rather than a broken
        stream.
        """
        bad = Plan.model_validate(
            {
                "goal": "One day",
                "steps": [
                    {
                        "index": 1,
                        "kind": "synthesis",
                        "description": "first",
                        "search_query": None,
                    },
                    {
                        "index": 2,
                        "kind": "research",
                        "description": "after",
                        "search_query": "q",
                    },
                ],
            }
        )
        session: Any = _Session()

        with _patch_run_session(session), patch.object(service, "execute_plan") as executed:
            events = _stream(_run_body(bad))

        assert [name for name, _ in events] == ["error"]
        assert events[0][1]["code"] == "invalid_plan"
        executed.assert_not_called()

    def test_a_halted_run_becomes_a_categorised_error_event_after_its_results(self) -> None:
        """Partial results survive the failure, which is the whole point.

        The chained-calls API set this convention: a run that produced output
        and then failed answers 200 and reports the failure alongside the
        output, because a 5xx would push the client's error branch and discard
        it.
        """
        session: Any = _Session()
        halted = _execution(
            ExecutionEvent(kind="step_result", step_result=_step(1)),
            ExecutionEvent(
                kind="halted",
                code="synthesis_failed",
                notice="The itinerary could not be composed.",
            ),
        )

        with _patch_run_session(session), patch.object(service, "execute_plan", halted):
            events = _stream(_run_body())

        assert [name for name, _ in events] == ["plan", "step_result", "error"]
        assert events[-1][1]["code"] == "synthesis_failed"
        assert events[-1][1]["steps_completed"] == 1

    def test_quota_exhaustion_is_reported_without_a_model_call(self) -> None:
        # The orchestrator's gate refuses before any provider is reached, and
        # the stream says which of the two 503-shaped problems it was.
        session: Any = _Session()
        halted = _execution(
            ExecutionEvent(
                kind="halted",
                code="usage_limit_reached",
                notice="Today's budget is spent.",
            )
        )

        with _patch_run_session(session), patch.object(service, "execute_plan", halted):
            events = _stream(_run_body())

        assert [name for name, _ in events] == ["plan", "error"]
        assert events[-1][1]["code"] == "usage_limit_reached"

    def test_a_failed_step_still_streams_as_a_step_result(self) -> None:
        # A research failure is shown honestly rather than hidden, and does not
        # end the run.
        session: Any = _Session()
        with_failure = _execution(
            ExecutionEvent(kind="step_result", step_result=_step(1, status="failed")),
            ExecutionEvent(kind="step_result", step_result=_step(2)),
            ExecutionEvent(kind="itinerary", itinerary=ITINERARY),
        )

        with _patch_run_session(session), patch.object(service, "execute_plan", with_failure):
            events = _stream(_run_body())

        statuses = [data["status"] for name, data in events if name == "step_result"]
        assert statuses == ["failed", "completed"]
        assert events[-1][0] == "itinerary"

    def test_the_run_starts_the_ceiling_from_the_planner_call_not_the_client(self) -> None:
        """A client that could set the starting count could reset its own ceiling."""
        session: Any = _Session()
        seen: dict[str, Any] = {}

        async def capture(_session: Any, *, goal: Any, plan: Any, calls_used: Any=0) -> AsyncIterator[Any]:
            seen["calls_used"] = calls_used
            yield ExecutionEvent(kind="itinerary", itinerary=ITINERARY)

        body = {**_run_body(), "calls_used": 0}

        with _patch_run_session(session), patch.object(service, "execute_plan", capture):
            _stream(body)

        assert seen["calls_used"] == api.PLANNER_CALL_COST


def _spaced_execution() -> Any:
    """A run whose events are separated in time, so flushing is measurable."""

    async def fake(_session: Any, *, goal: Any, plan: Any, calls_used: Any=0) -> AsyncIterator[Any]:
        for event in (
            ExecutionEvent(kind="step_result", step_result=_step(1)),
            ExecutionEvent(kind="step_result", step_result=_step(2)),
            ExecutionEvent(kind="itinerary", itinerary=ITINERARY),
        ):
            await asyncio.sleep(0.1)
            yield event

    return fake


def _drive_asgi(payload: dict[str, Any]) -> list[tuple[float, bytes]]:
    """Call the ASGI app directly and timestamp every body chunk it sends."""
    body = json.dumps(payload).encode()
    chunks: list[tuple[float, bytes]] = []
    request_sent = False

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "path": "/api/planning/run",
        "raw_path": b"/api/planning/run",
        "root_path": "",
        "scheme": "http",
        "query_string": b"",
        "headers": [
            (b"host", b"testserver"),
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ],
        "client": ("127.0.0.1", 51234),
        "server": ("testserver", 80),
    }

    async def receive() -> dict[str, Any]:
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        # sse-starlette watches this for `http.disconnect`. This client never
        # disconnects, so block; the watcher is cancelled when the generator
        # finishes, which is what ends the response.
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    async def send(message: MutableMapping[str, Any]) -> None:
        if message["type"] == "http.response.body" and message.get("body"):
            chunks.append((time.monotonic(), message["body"]))

    async def drive() -> None:
        await asyncio.wait_for(app(scope, receive, send), timeout=15)

    asyncio.run(drive())
    return chunks


class TestPersistenceAndDelivery:
    def test_search_queries_and_log_entries_are_written_by_a_real_run(self) -> None:
        """Through the real orchestrator, with only the model and Exa mocked.

        The endpoint tests above stub `execute_plan`, which would make a
        persistence assertion meaningless -- so this one drives the real thing.
        """
        from pydantic_ai.messages import ModelResponse, ToolCallPart
        from pydantic_ai.models.function import FunctionModel

        from backend.app.planning import agents
        from backend.app.services.web_search import ExaResult

        searched: list[str] = []

        def behave(messages: Any, info: Any) -> ModelResponse:
            names = {tool.name for tool in info.function_tools}
            if "web_search" in names:
                if not searched or len(searched) < 1:
                    return ModelResponse(
                        parts=[ToolCallPart("web_search", {"query": "a query"})]
                    )
                return ModelResponse(
                    parts=[ToolCallPart(info.output_tools[0].name, {"summary": "found"})]
                )
            return ModelResponse(
                parts=[
                    ToolCallPart(info.output_tools[0].name, {"city": "Lisbon", "blocks": []})
                ]
            )

        async def fake_search(query: str) -> list[Any]:
            searched.append(query)
            return [ExaResult(title="T", summary="S", source="https://a.test/1")]

        session: Any = _Session()

        with (
            _patch_run_session(session),
            patch("backend.app.planning.agents.agent_runtime.build_fallback_model",
                lambda chain=None, **_: FunctionModel(behave),
            ),
            patch.object(service, "search", fake_search),
        ):
            events = _stream(_run_body())

        assert events[-1][0] == "itinerary"
        assert [row for row in session.added if isinstance(row, SearchQuery)]
        assert [row for row in session.added if isinstance(row, ServiceLogEntry)]
        assert session.used(shared.CAPABILITY_SEARCH) > 0
        assert session.used(shared.CAPABILITY_GENERATION) > 0

    def test_each_event_is_flushed_as_its_own_chunk(self) -> None:
        """Incremental delivery, measured on the server's side of the boundary.

        `TestClient` runs the app to completion before returning, so it reports
        every event as arriving at once however the server behaved. Driving the
        ASGI app directly is what makes the measurement real -- and this is the
        property the whole SSE design exists for.
        """
        session: Any = _Session()

        with _patch_run_session(session), patch.object(
            service, "execute_plan", _spaced_execution()
        ):
            chunks = _drive_asgi(_run_body())

        assert len(chunks) >= 4
        assert chunks[-1][0] - chunks[0][0] >= 0.2


class TestDisconnect:
    def test_a_disconnect_closes_the_orchestrator_deterministically(self) -> None:
        """An abandoned run must stop spending quota, at a defined moment.

        sse-starlette cancels this generator when the client goes away, and
        `athrow(CancelledError)` is how that arrives, so it is what the test
        injects.

        **The assertion is made inside the coroutine, and that is the whole
        test.** Abandoning an `async for` mid-iteration does not close the inner
        generator; it is left to be finalised later, which under `asyncio.run`
        means `shutdown_asyncgens()` at loop teardown. A long-running server has
        no such teardown per request, so "it gets cleaned up eventually" is not
        a guarantee that the next model call is not still in flight. Asserting
        after `asyncio.run` returned would therefore pass with or without the
        explicit `aclose()` -- verified by mutation, which is why this checks
        the moment cancellation is handled instead.
        """
        session: Any = _Session()
        produced: list[int] = []
        closed: list[str] = []

        async def counting(_session: Any, *, goal: Any, plan: Any, calls_used: Any=0) -> AsyncIterator[Any]:
            try:
                for index in (1, 2, 3):
                    produced.append(index)
                    yield ExecutionEvent(kind="step_result", step_result=_step(index))
            finally:
                closed.append("orchestrator closed")

        async def drive() -> None:
            stream = api._stream(api.RunRequest.model_validate(_run_body()), _allow_moderation)
            await stream.__anext__()  # plan
            await stream.__anext__()  # step 1
            with pytest.raises(asyncio.CancelledError):
                await stream.athrow(asyncio.CancelledError())

            # Already closed, here, before the loop tears anything down.
            assert closed == ["orchestrator closed"]
            assert produced == [1], "the orchestrator ran on after the disconnect"

        with _patch_run_session(session), patch.object(service, "execute_plan", counting):
            asyncio.run(drive())


class TestRetrySynthesis:
    """The capability's mitigation for a failed final step.

    Phase 2 built `service.retry_synthesis` and Phase 3 never routed it, so the
    UI's retry button had nothing to call. It is a plain JSON endpoint rather
    than a stream because there is exactly one call to make and one object to
    return.
    """

    def _body(self) -> dict[str, Any]:
        return {
            **_run_body(),
            "results": [_step(1).model_dump(), _step(2).model_dump()],
        }

    def test_it_recomposes_the_itinerary_without_rerunning_research(self) -> None:
        session: Any = _Session()
        app.dependency_overrides[get_db_session] = _override_session(session)
        try:
            with (
                patch.object(service, "retry_synthesis", return_value=ITINERARY) as composed,
                patch.object(service, "execute_plan") as executed,
            ):
                response = client.post("/api/planning/retry-synthesis", json=self._body())
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json()["itinerary"]["city"] == "Lisbon"
        composed.assert_called_once()
        # The whole point: the research the visitor is looking at is not redone.
        executed.assert_not_called()

    def test_it_passes_the_existing_step_results_through_unchanged(self) -> None:
        # Re-running the research would produce *different* findings, so the
        # itinerary that came back would not be the one those results support.
        session: Any = _Session()
        app.dependency_overrides[get_db_session] = _override_session(session)
        try:
            with patch.object(
                service, "retry_synthesis", return_value=ITINERARY
            ) as composed:
                client.post("/api/planning/retry-synthesis", json=self._body())
        finally:
            app.dependency_overrides.clear()

        passed = composed.call_args.kwargs["results"]
        assert [result.step_index for result in passed] == [1, 2]

    def test_an_unexecutable_plan_is_refused(self) -> None:
        bad = Plan.model_validate(
            {
                "goal": "One day",
                "steps": [
                    {"index": 1, "kind": "synthesis", "description": "first", "search_query": None},
                    {"index": 2, "kind": "research", "description": "after", "search_query": "q"},
                ],
            }
        )
        session: Any = _Session()
        app.dependency_overrides[get_db_session] = _override_session(session)
        try:
            with patch.object(service, "retry_synthesis") as composed:
                response = client.post(
                    "/api/planning/retry-synthesis",
                    json={**_run_body(bad), "results": []},
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 422
        assert response.json()["code"] == "invalid_plan"
        composed.assert_not_called()

    @pytest.mark.parametrize(
        ("error", "code"),
        [
            (service.UsageLimitReachedError("spent"), "usage_limit_reached"),
            (service.PlanUnavailableError("still failing"), "plan_unavailable"),
        ],
    )
    def test_failures_keep_their_codes(self, error: Exception, code: str) -> None:
        session: Any = _Session()
        app.dependency_overrides[get_db_session] = _override_session(session)
        try:
            with patch.object(service, "retry_synthesis", side_effect=error):
                response = client.post("/api/planning/retry-synthesis", json=self._body())
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 503
        assert response.json()["code"] == code


class TestRoutingUnchanged:
    def test_both_planning_routes_are_mounted_alongside_the_other_apps(self) -> None:
        paths = set(app.openapi()["paths"])

        assert {
            "/health",
            "/api/rag/ask",
            "/api/embeddings/place",
            "/api/single-call/generate",
            "/api/chained-calls/generate",
            "/api/planning/plan",
            "/api/planning/run",
        } <= paths
