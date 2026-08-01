# Built with Spec4 AI - https://spec4.ai
"""Endpoint and chain tests for the chained_calls_example_app.

No live database and no live provider. The DB session is the project's fake
session with pre-queued canned results (see test_shared_services.py), and the
model call is stubbed at its point of use -- `service.run_step` -- so each test
drives a *different model behaviour* the way test_tool_agent.py does, rather
than asserting against one canned happy path.

Async entry points run through `asyncio.run()` in sync test functions: this
repo has no pytest-asyncio, and an `@pytest.mark.asyncio` here would silently
skip.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from backend.app.chained_calls import service
from backend.app.chained_calls.pipeline import (
    ROLE_CRITIC,
    ROLE_WRITER,
    AgentLaneError,
    StepResult,
    StoryCritique,
    StoryDraft,
)
from backend.app.chained_calls.service import (
    CHAINED_CALLS_APP_NAME,
    STATUS_COMPLETE,
    STATUS_CRITIQUE_FAILED,
    UsageLimitReachedError,
    run_chain,
)
from backend.app.db.models import UsageLimit
from backend.app.db.session import get_db_session
from backend.app.main import app
import pytest


@pytest.fixture(autouse=True)
def _gate_allows_everything(allow_all_moderation):
    """Every request here carries free text, which the shared gate now checks.

    The gate is not this file's subject, and with no `OPENAI_API_KEY` in the
    test environment it fails closed and would refuse all of them. Overridden
    per module rather than globally, so a test that *should* exercise the gate
    cannot pass by accident.
    """


_STORY = (
    "The lighthouse keeper found a bottle wedged in the rocks. Inside was a "
    "note in handwriting he almost recognised. He read it twice and then, "
    "maybe foolishly, threw it back."
)

_DRAFT = StoryDraft(title="Maybe 'The Bottle'", story=_STORY)
_CRITIQUE = StoryCritique(
    quoted_detail="a bottle wedged in the rocks",
    critique=(
        "'A bottle wedged in the rocks' is the only concrete image here, and the "
        "draft abandons it immediately. Throwing the note back is a decision the "
        "prose refuses to dramatise."
    ),
)


class _FakeResult:
    """Stands in for a SQLAlchemy Result over one canned row."""

    def __init__(self, row: object) -> None:
        self._row = row

    def scalar_one_or_none(self) -> object:
        return self._row


class FakeSession:
    """Async-session stand-in that pops pre-queued results in call order."""

    def __init__(self, results: list[object] | None = None) -> None:
        self._results = list(results or [])
        self.added: list[object] = []
        self.commits = 0

    async def execute(self, _statement: object) -> _FakeResult:
        return _FakeResult(self._results.pop(0) if self._results else None)

    def add(self, row: object) -> None:
        self.added.append(row)

    async def commit(self) -> None:
        self.commits += 1


def _client(session: FakeSession) -> TestClient:
    """A TestClient whose DB dependency is the supplied fake session."""
    app.dependency_overrides[get_db_session] = lambda: session
    return TestClient(app)


def _steps(*outcomes: object) -> AsyncMock:
    """Stub `run_step` with one scripted outcome per call, in order.

    Args:
        *outcomes: Either a StepResult to return or an exception to raise.

    Returns:
        An AsyncMock standing in for `service.run_step`.
    """
    scripted = list(outcomes)

    async def _run(**kwargs: object) -> StepResult:
        outcome = scripted.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome  # type: ignore[return-value]

    return AsyncMock(side_effect=_run)


def _ok(output: object, model: str) -> StepResult:
    return StepResult(output=output, model=model)  # type: ignore[arg-type]


def test_a_successful_chain_returns_both_role_labeled_outputs() -> None:
    """The phase's core assertion.

    Both blocks are present, each carries the role of the call that produced
    it, and the critique demonstrably references content from the story rather
    than being generic commentary.
    """
    session = FakeSession()
    steps = _steps(
        _ok(_DRAFT, "nvidia/nemotron-3-super-120b-a12b:free"),
        _ok(_CRITIQUE, "poolside/laguna-s-2.1:free"),
    )
    try:
        with patch.object(service, "run_step", steps):
            response = _client(session).post(
                "/api/chained-calls/generate",
                json={"story_prompt": "a lighthouse keeper and a message in a bottle"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()

    assert body["status"] == STATUS_COMPLETE
    assert body["intermediate_output"]["role"] == ROLE_WRITER
    assert body["intermediate_output"]["text"] == _STORY
    assert body["final_output"]["role"] == ROLE_CRITIC
    assert body["final_output"]["text"].strip()

    # The chaining, checked rather than asserted: the detail the critic quoted
    # is actually in the story the writer produced.
    assert body["final_output"]["quoted_detail"] in body["intermediate_output"]["text"]
    assert body["quality_signal"]["references_story"] is True

    assert body["writer_model"] == "nvidia/nemotron-3-super-120b-a12b:free"
    assert body["critic_model"] == "poolside/laguna-s-2.1:free"
    assert steps.await_count == 2, "the chain is exactly two calls"


def test_the_second_call_receives_the_first_calls_output_as_its_input() -> None:
    """'Each step's output feeds the next' is the defining property of the tier.

    Asserted on the actual user prompt handed to call 2, so a refactor that
    quietly re-derived the critic's input from the visitor's original idea --
    which would make this a pair of independent calls, not a chain -- fails
    here.
    """
    session = FakeSession()
    steps = _steps(_ok(_DRAFT, "writer-model"), _ok(_CRITIQUE, "critic-model"))

    with patch.object(service, "run_step", steps):
        asyncio.run(run_chain(session, story_prompt="a lighthouse keeper"))

    first, second = steps.await_args_list
    assert first.kwargs["role"] == ROLE_WRITER
    assert first.kwargs["user_prompt"] == "a lighthouse keeper"

    assert second.kwargs["role"] == ROLE_CRITIC
    assert _STORY in second.kwargs["user_prompt"]
    assert _DRAFT.title in second.kwargs["user_prompt"]


def test_a_second_call_failure_keeps_the_intermediate_output() -> None:
    """A failed critic is a partial result, not a failed request.

    The capability's escalation path: show what was generated, label the step
    that failed, and offer a scoped retry. Discarding the story because the
    critique failed would throw away the half the visitor actually watched
    happen.
    """
    session = FakeSession()
    steps = _steps(
        _ok(_DRAFT, "writer-model"),
        AgentLaneError(ROLE_CRITIC, "the harsh_critic call could not be completed"),
    )
    try:
        with patch.object(service, "run_step", steps):
            response = _client(session).post(
                "/api/chained-calls/generate", json={"story_prompt": "a lighthouse keeper"}
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, "a partial result is not an error status"
    body = response.json()

    assert body["status"] == STATUS_CRITIQUE_FAILED
    assert body["intermediate_output"]["text"] == _STORY
    assert body["final_output"] is None
    assert body["quality_signal"] is None
    assert body["notice"], "the visitor must be told which step failed"


def test_retry_critique_reruns_only_the_second_call() -> None:
    """The retry path spends one unit and does not regenerate the story.

    Regenerating would produce a *different* story, so the critique the visitor
    finally receives would not be a critique of the draft on their screen.
    """
    fresh = UsageLimit(capability="generation", used=0, cap=100, window_start=None)
    session = FakeSession([fresh])
    steps = _steps(_ok(_CRITIQUE, "critic-model"))
    try:
        with patch.object(service, "run_step", steps):
            response = _client(session).post(
                "/api/chained-calls/retry-critique",
                json={
                    "intermediate_output": {
                        "role": ROLE_WRITER,
                        "title": _DRAFT.title,
                        "text": _STORY,
                    }
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()

    assert body["status"] == STATUS_COMPLETE
    assert body["intermediate_output"]["text"] == _STORY, "the story is unchanged"
    assert body["final_output"]["role"] == ROLE_CRITIC

    assert steps.await_count == 1, "only the critic call may run"
    assert steps.await_args.kwargs["role"] == ROLE_CRITIC
    assert fresh.used == 1, "a retry spends one unit, not two"


def test_a_client_supplied_role_is_ignored_rather_than_echoed_back() -> None:
    """The server decides which persona ran; a posted role is not evidence."""
    session = FakeSession()
    try:
        with patch.object(service, "run_step", _steps(_ok(_CRITIQUE, "critic-model"))):
            body = (
                _client(session)
                .post(
                    "/api/chained-calls/retry-critique",
                    json={
                        "intermediate_output": {
                            "role": "definitely_not_a_real_role",
                            "text": _STORY,
                        }
                    },
                )
                .json()
            )
    finally:
        app.dependency_overrides.clear()

    assert body["intermediate_output"]["role"] == ROLE_WRITER


def test_an_exhausted_quota_blocks_the_whole_chain_before_any_call() -> None:
    """No partial output, and no model reached.

    The capability's failure mode is the cap running out *between* the two
    calls. Reserving both up front converts that into a clean refusal, which is
    what this pins: one unit short of the chain's cost is still a refusal.
    """
    one_short = UsageLimit(capability="generation", used=99, cap=100, window_start=None)
    session = FakeSession([one_short])
    steps = _steps()

    with patch.object(service, "run_step", steps):
        try:
            asyncio.run(run_chain(session, story_prompt="a lighthouse keeper"))
        except UsageLimitReachedError as exc:
            assert exc.code == "usage_limit_reached"
        else:  # pragma: no cover - the cap must bite
            raise AssertionError("an exhausted cap must not start the chain")

    assert steps.await_count == 0, "the cap must be checked before any model call"
    assert one_short.used == 99, "a refused chain must not spend anything"


def test_an_exhausted_quota_is_reported_as_503_with_no_partial_output() -> None:
    """The wire form of the same rule."""
    exhausted = UsageLimit(capability="generation", used=100, cap=100, window_start=None)
    session = FakeSession([exhausted])
    try:
        with patch.object(service, "run_step", _steps()):
            response = _client(session).post(
                "/api/chained-calls/generate", json={"story_prompt": "a lighthouse keeper"}
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    body = response.json()
    assert body["code"] == "usage_limit_reached"
    assert "intermediate_output" not in body


def test_a_first_call_failure_is_an_error_not_an_empty_chain() -> None:
    """Nothing was generated, so there is nothing to show -- say so."""
    session = FakeSession()
    steps = _steps(AgentLaneError(ROLE_WRITER, "every model failed"))
    try:
        with patch.object(service, "run_step", steps):
            response = _client(session).post(
                "/api/chained-calls/generate", json={"story_prompt": "a lighthouse keeper"}
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json()["code"] == "generation_unavailable"
    assert steps.await_count == 1, "call 2 must not run without call 1's output"


def test_a_blank_or_overlong_story_prompt_is_rejected_before_any_call() -> None:
    """The bound stops one paste spending a doubled token budget."""
    session = FakeSession()
    steps = _steps()
    try:
        with patch.object(service, "run_step", steps):
            blank = _client(session).post(
                "/api/chained-calls/generate", json={"story_prompt": "   "}
            )
            long = _client(session).post(
                "/api/chained-calls/generate",
                json={"story_prompt": "x" * (service.MAX_STORY_PROMPT_CHARS + 1)},
            )
    finally:
        app.dependency_overrides.clear()

    assert blank.status_code == 422
    assert blank.json()["code"] == "invalid_story_prompt"
    assert long.status_code == 422
    assert steps.await_count == 0


def test_the_chain_is_metered_and_logged_but_stores_no_authored_text() -> None:
    """The privacy requirement, pinned against the shape of the rows written.

    Every other example app calls `record_generation_request`, which persists
    prompt and response excerpts. This one must not: the capability forbids
    keeping the story prompt or the generated content beyond the request. Usage
    is still reserved and logged -- unlogged is not unmetered -- so this asserts
    both halves at once.
    """
    fresh = UsageLimit(capability="generation", used=0, cap=100, window_start=None)
    session = FakeSession([fresh])
    steps = _steps(_ok(_DRAFT, "writer-model"), _ok(_CRITIQUE, "critic-model"))

    with patch.object(service, "run_step", steps):
        outcome = asyncio.run(run_chain(session, story_prompt="a lighthouse keeper"))

    assert outcome.status == STATUS_COMPLETE
    assert fresh.used == 2, "both calls are reserved up front"

    written = [type(row).__name__ for row in session.added]
    assert written.count("ServiceLogEntry") == 2, "one log entry per call"
    assert "LanguageGenerationRequest" not in written, (
        "that row persists prompt and response excerpts, which this app must not keep"
    )

    for row in session.added:
        assert getattr(row, "app_name", None) == CHAINED_CALLS_APP_NAME
        summary = getattr(row, "summary", "")
        assert _STORY not in summary
        assert "lighthouse" not in summary.lower(), (
            "no authored or visitor text may reach the cross-app log"
        )


def test_the_plan_describes_both_roles_before_anything_runs() -> None:
    """The feature requires the visitor be told each call's job up front."""
    with TestClient(app) as client:
        response = client.get("/api/chained-calls/plan")

    assert response.status_code == 200
    body = response.json()

    assert [step["role"] for step in body["steps"]] == [ROLE_WRITER, ROLE_CRITIC]
    assert body["chain_length"] == 2
    # The other stated criterion: two is the demo's budget, not the pattern's.
    assert "any length" in body["length_note"]


def test_chained_calls_router_does_not_displace_the_existing_routes() -> None:
    """Mounting a sixth router leaves the established surface addressable."""
    with TestClient(app) as client:
        rag = client.get("/api/rag/dataset")
        presets = client.get("/api/single-call/presets")

    assert rag.status_code == 200
    assert rag.json()["documents"]
    assert presets.status_code == 200
