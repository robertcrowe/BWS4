# Built with Spec4 AI - https://spec4.ai
"""The ReAct slice's HTTP surface: presets, the stub stream, and the read-back.

Phase 1 is an integration thread, so what is asserted here is that the *layers
connect* -- not that any agent behaves. Three properties are worth naming
because they are the phase's documented traps:

1. **The stream writes its row.** The SSE response outlives the request
   handler, so a session taken via `Depends(get_db_session)` would be closed
   while the generator was still writing. The test consumes the whole stream
   and then asserts the `react_runs` row exists, which fails loudly if that
   ever regresses -- it is the only shape of test that can, since the failure is
   intermittent and load-dependent in production.
2. **Exactly one terminal event, and it is last.** A run ends in exactly one of
   the two candid endings (or an error), and a stream that emitted both would be
   the app dressing up an unfinished run as an answer.
3. **The budget is server-fixed at 8.** No `cycle_budget` field on the request,
   and a client that sends one has it ignored rather than honoured.

`TestClient(app)` is constructed without its context manager, following
`test_identity_cards.py`: entering it runs the lifespan, which loads
sentence-transformers and fits the embeddings projection -- real work, on every
construction, for routes that touch neither a model nor that projection.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import json
import uuid
from collections.abc import AsyncGenerator, Callable, Generator
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import params as params_module
from fastapi.testclient import TestClient

from backend.app.api import collab as collab_api
from backend.app.api import react as api
from backend.app.core.config import get_settings
from backend.app.db.models import ReactRun
from backend.app.db.session import get_db_session
from backend.app.main import app
from backend.app.react import schemas
from backend.app.react.presets import PRESETS
from backend.app.react.schemas import RunRequest
from backend.app.services import agent_runtime
from backend.app.services.moderation import get_stateless_moderator

client = TestClient(app)

CYCLE_BUDGET = get_settings().react_cycle_budget


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

    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None


def _patch_run_session(session: Any) -> AbstractContextManager[Any]:
    """Install the fake session for `/run`, which opens its own.

    `/run` deliberately does not take `Depends(get_db_session)` -- its response
    outlives the handler -- so it is patched at the factory instead, the same
    seam `test_planning_api.py` and `test_embeddings_api.py` use.
    """
    return patch.object(api, "async_session_factory", lambda: session)


def _override_session(
    session: Any,
) -> Callable[[], AsyncGenerator[_Session, None]]:
    """Install the fake session for the read-back route's dependency."""

    async def _yield() -> AsyncGenerator[_Session, None]:
        yield session

    return _yield


def _stream(body: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """POST a run and collect its events, parsing the SSE wire format directly."""
    events: list[tuple[str, dict[str, Any]]] = []
    pending: str | None = None

    with client.stream("POST", "/api/react/run", json=body) as response:
        assert response.status_code == 200, response.read()
        assert response.headers["content-type"].startswith("text/event-stream")

        for line in response.iter_lines():
            if line.startswith("event:"):
                pending = line.removeprefix("event:").strip()
            elif line.startswith("data:") and pending is not None:
                events.append((pending, json.loads(line.removeprefix("data:").strip())))
                pending = None

    return events


def _refusing_lane() -> AbstractContextManager[Any]:
    """Fail every model call, so a route test ends quickly and candidly."""

    async def refuse(**_kwargs: Any) -> Any:
        raise agent_runtime.AgentLaneError("react-cycle-1", "no lane in this test")

    return patch.object(agent_runtime, "run_typed_step", refuse)


def _preset_body(preset_id: str = "p1") -> dict[str, Any]:
    return {"preset_question_id": preset_id, "session_id": "session-1"}


# ---------------------------------------------------------------------------
# GET /api/react/presets
# ---------------------------------------------------------------------------


class TestThePresetsEndpoint:
    def test_it_returns_exactly_five_presets(self) -> None:
        response = client.get("/api/react/presets")

        assert response.status_code == 200
        assert len(response.json()["presets"]) == 5

    def test_every_preset_carries_its_question_verbatim(self) -> None:
        """The question the endpoint publishes is the question the run asks --
        the client renders it and the server resolves the run from the same
        constants, so a projection that reworded it would put one question on
        screen and another in the prompt."""
        payload = response_presets()

        by_id = {preset["id"]: preset for preset in payload}
        for preset in PRESETS:
            assert by_id[preset.id]["question"] == preset.question

    def test_it_publishes_no_answer_to_any_preset(self) -> None:
        """The catalogue holds no answers, so there is none to leak -- this
        asserts the projection did not invent a field to hold one."""
        raw = client.get("/api/react/presets").text.lower()

        for word in ('"answer"', '"solution"', '"expected_value"'):
            assert word not in raw

    def test_it_publishes_the_server_fixed_cycle_budget(self) -> None:
        """So the selector can state the run's cost without hardcoding a
        number free to drift from the server's."""
        assert client.get("/api/react/presets").json()["cycle_budget"] == CYCLE_BUDGET

    def test_it_needs_no_provider_key_and_no_database(self) -> None:
        """Fetched on page load, so it has to answer on a deployment with no
        keys configured and a database that is asleep. No dependency override
        is installed by this test, and it still returns 200."""
        assert client.get("/api/react/presets").status_code == 200


def response_presets() -> list[dict[str, Any]]:
    """Fetch the presets payload once, for the assertions above."""
    presets: list[dict[str, Any]] = client.get("/api/react/presets").json()["presets"]
    return presets


# ---------------------------------------------------------------------------
# POST /api/react/run
# ---------------------------------------------------------------------------


class TestTheRunStreamSurface:
    """What the *route* guarantees. The loop's own behaviour is in
    `test_react_loop.py`, which drives it with a stubbed lane and recorded Exa
    fixtures -- this file stays about the HTTP surface."""

    def test_it_streams_rather_than_returning_a_document(self) -> None:
        session = _Session()

        with _patch_run_session(session), _refusing_lane():
            with client.stream("POST", "/api/react/run", json=_preset_body()) as r:
                assert r.status_code == 200
                assert r.headers["content-type"].startswith("text/event-stream")
                r.read()

    def test_a_failing_run_is_a_200_with_an_error_event(self) -> None:
        """Refusals ride the stream as events, not as an HTTP error: a run that
        produced cycles and then stopped must not push the client's error
        branch and discard them."""
        session = _Session()

        with _patch_run_session(session), _refusing_lane():
            events = _stream(_preset_body())

        assert events[-1][0] in schemas.TERMINAL_EVENTS

    def test_an_unknown_preset_is_one_error_event_and_nothing_else(self) -> None:
        """A refusal before cycle 1 yields exactly one event and reserves
        nothing, so there is nothing to give back."""
        session = _Session()

        with _patch_run_session(session):
            events = _stream({"preset_question_id": "p99", "session_id": "s"})

        assert [name for name, _ in events] == [schemas.EVENT_ERROR]
        assert events[0][1]["code"] == "unknown_preset"
        assert session.added == []


class TestTheRequestBody:
    def test_it_refuses_both_question_sources_at_once(self) -> None:
        """Two sources means the server picks one, and the visitor cannot see
        which -- the edited-textarea trap the single-call app hit."""
        response = client.post(
            "/api/react/run",
            json={
                "preset_question_id": "p1",
                "visitor_question": "something else",
                "session_id": "s",
            },
        )

        assert response.status_code == 422

    def test_it_refuses_neither(self) -> None:
        response = client.post("/api/react/run", json={"session_id": "s"})

        assert response.status_code == 422

    def test_a_whitespace_only_question_counts_as_absent(self) -> None:
        response = client.post(
            "/api/react/run", json={"visitor_question": "   ", "session_id": "s"}
        )

        assert response.status_code == 422

    def test_the_request_carries_no_cycle_budget_field(self) -> None:
        """**The budget is server-fixed and is not visitor-settable.** The
        design mock offers a 3..6 select; that is superseded by the stack
        spec's `react_run_call_budget` decision. It matters beyond tidiness:
        the run's whole worst case is reserved through `allowance_holds` before
        the first cycle, so a client-supplied budget would let a caller reserve
        one number and spend another."""
        assert "cycle_budget" not in schemas.RunRequest.model_fields

    def test_a_client_supplied_budget_is_ignored_rather_than_honoured(self) -> None:
        session = _Session()

        with _patch_run_session(session), _refusing_lane():
            events = _stream({**_preset_body(), "cycle_budget": 3})

        assert events[0][1]["cycle_budget"] == CYCLE_BUDGET


# ---------------------------------------------------------------------------
# GET /api/react/run/{run_id}
# ---------------------------------------------------------------------------


class TestTheTraceReadBack:
    @pytest.fixture(autouse=True)
    def _cleanup(self) -> Generator[None, None, None]:
        yield
        app.dependency_overrides.pop(get_db_session, None)

    def test_it_returns_a_persisted_run_whole(self) -> None:
        """The write path and the read path exercised against one another."""
        written = ReactRun(
            id=uuid.uuid4(),
            question_origin="p1",
            cycle_budget=CYCLE_BUDGET,
            searches_used=3,
            ending=schemas.ENDING_FINAL_ANSWER,
            duplicate_queries_blocked=1,
            empty_observations=0,
            cycle_trace=[{"cycle": 1, "thought": "t", "action": {"kind": "search"}}],
            terminal_card={"answer": "An answer."},
            cycle_timings={"cycle_1": 1.5},
        )
        app.dependency_overrides[get_db_session] = _override_session(
            _Session([written])
        )

        body = client.get(f"/api/react/run/{written.id}").json()

        assert body["run_id"] == str(written.id)
        assert body["question_origin"] == "p1"
        assert body["searches_used"] == 3
        assert body["ending"] == schemas.ENDING_FINAL_ANSWER
        assert body["duplicate_queries_blocked"] == 1
        assert len(body["cycle_trace"]) == 1
        assert body["terminal_card"]["answer"] == "An answer."
        assert body["cycle_timings"] == {"cycle_1": 1.5}

    def test_an_unknown_run_is_a_404(self) -> None:
        app.dependency_overrides[get_db_session] = _override_session(_Session([None]))

        response = client.get(f"/api/react/run/{uuid.uuid4()}")

        assert response.status_code == 404

    def test_an_unparseable_id_is_also_a_404(self) -> None:
        """An id that is not a UUID names no run, which is the same answer --
        and answering 422 instead would tell a scanner the id format."""
        app.dependency_overrides[get_db_session] = _override_session(_Session([None]))

        assert client.get("/api/react/run/not-a-uuid").status_code == 404

    def test_a_preset_run_carries_no_suitability_verdict(self) -> None:
        """Null on every preset run: the check is for free-form questions, and
        presets skip it. Read alongside `question_origin`, which is what
        distinguishes 'no verdict was reached' from 'none was needed'."""
        run = ReactRun(
            id=uuid.uuid4(),
            question_origin="p1",
            cycle_budget=CYCLE_BUDGET,
            searches_used=2,
            ending=schemas.ENDING_FINAL_ANSWER,
            duplicate_queries_blocked=0,
            empty_observations=0,
            cycle_trace=[],
            terminal_card={},
        )
        app.dependency_overrides[get_db_session] = _override_session(_Session([run]))

        body = client.get(f"/api/react/run/{run.id}").json()

        assert body["suitability"] is None


# ---------------------------------------------------------------------------
# The phase's own boundary
# ---------------------------------------------------------------------------


class TestThisPhaseCallsNoProvider:
    def test_the_run_route_never_takes_a_request_scoped_session(self) -> None:
        """The phase's headline trap, pinned at the signature rather than only
        by behaviour.

        A `Depends(get_db_session)` session is bound to the request scope, and
        this response outlives the handler -- the generator is still writing the
        run's row while the body streams. The behavioural test above catches the
        write failing; this catches the dependency being *added*, which is the
        edit somebody makes, and it fails before the intermittent
        under-load-only symptom ever has a chance to appear.
        """
        params = inspect.signature(api.run).parameters

        assert "session" not in params

        # A dependency is not the problem -- a *session-bound* one is. Phase 5
        # gives this route the moderation gate, and it takes the **stateless**
        # moderator for exactly this reason: it holds no session, so it cannot
        # be closed out from under a response that outlives its handler. The
        # assertion is therefore about which dependency, not whether.
        for name, param in params.items():
            if not isinstance(param.default, params_module.Depends):
                continue
            assert param.default.dependency is get_stateless_moderator, (
                f"{name} takes a request-scoped dependency"
            )
            assert param.default.dependency is not get_db_session

        # The read-back route is the opposite case and *should* have one: it is
        # assembled and returned before the handler exits.
        assert "session" in inspect.signature(api.get_run).parameters

    def test_the_stream_keeps_alive_on_the_same_interval_as_collab(self) -> None:
        """Render's proxy closes an idle connection, and a real cycle waits on
        a model and then on a search with nothing to say for tens of seconds.

        **Read what this does and does not establish.** sse-starlette's own
        `DEFAULT_PING_INTERVAL` is currently also 15, so deleting the explicit
        `ping=` argument leaves `ping_interval` at 15 and this test still
        passes -- mutation-verified, and stated here rather than left for the
        next person to discover. What it does catch is the two apps drifting
        apart, and a library default that moves out from under an endpoint that
        stopped passing its own value. The explicit argument is what makes this
        route's interval independent of that default in the first place.
        """
        assert api.PING_SECONDS == collab_api.PING_SECONDS

        response = asyncio.run(
            api.run(
                RunRequest(
                    preset_question_id="p1",
                    visitor_question=None,
                    session_id="s",
                )
            )
        )
        assert response.ping_interval == api.PING_SECONDS

    def test_the_slice_reaches_a_provider_only_through_the_shared_lanes(
        self,
    ) -> None:
        """Phase 1 asserted this package imported *nothing* that reaches a model
        or Exa, which was right while there was no agent logic to blame a
        failure on. Phase 2 introduces exactly those calls, so the assertion
        that survives is the narrower and permanent one: the slice may reach a
        provider **only** through the shared lanes, never by standing up its
        own client.

        A second Exa client or a bare PydanticAI `Agent` here would each cost
        something specific -- the first bypasses the shared search quota gate,
        the second bypasses the registry's chain-walk failover, its
        withdrawn-slug bench and this project's fallback observation.

        Parsed with `ast` rather than grepped, because 'search' and 'model'
        appear legitimately in prose throughout this slice -- an earlier version
        of this check in the orchestrated app failed on a docstring.
        """
        forbidden = {
            # No second LLM client. `services/agent_runtime.py` is the lane.
            "litellm",
            "pydantic_ai",
            "openai",
            # No second HTTP client reaching a provider. `services/web_search.py`
            # is the one Exa client in this project.
            "httpx",
        }

        package = Path(api.__file__).resolve().parents[1] / "react"
        modules = [Path(api.__file__)] + sorted(package.glob("*.py"))

        for module in modules:
            tree = ast.parse(module.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = {alias.name for alias in node.names}
                elif isinstance(node, ast.ImportFrom):
                    names = {(node.module or "").split(".")[0]}
                else:
                    continue
                assert not names & forbidden, f"{module.name} imports {names}"

    def test_no_model_slug_appears_anywhere_in_the_slice(self) -> None:
        """`model_registry` is the single source of truth for slugs, and the
        free-tier chains are documented to rot as providers retire them.

        A slug pinned here would keep being requested after its provider
        withdrew it, and the failure would look like a code fault rather than a
        chain that needs re-probing. Scans the prompt too: a prompt naming a
        model is the same defect in a file the linter never reads.
        """
        markers = (
            "openrouter/",
            "groq/",
            ":free",
            "gpt-oss",
            "llama-",
            "nemotron",
            "qwen",
            "gemini",
        )

        package = Path(api.__file__).resolve().parents[1] / "react"
        files = [Path(api.__file__), *package.rglob("*.py"), *package.rglob("*.md")]

        for path in files:
            text = path.read_text().lower()
            for marker in markers:
                assert marker not in text, f"{path.name} names a model slug: {marker}"

    def test_the_router_did_not_displace_the_existing_ones(self) -> None:
        """Mounting a tenth router must not take an existing app dark, which is
        the NFR this phase's goal check names."""
        # Read from the generated OpenAPI schema rather than by walking
        # `app.routes`: FastAPI wraps included routers, so the top-level list
        # holds router objects with no `path` of their own and an assertion
        # over it silently checks nothing.
        paths = set(app.openapi()["paths"])

        for path in (
            "/health",
            "/api/rag/ask",
            "/api/tools/search",
            "/api/collab/identity-cards",
            "/api/react/presets",
        ):
            assert path in paths
