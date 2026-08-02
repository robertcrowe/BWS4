# Built with Spec4 AI - https://spec4.ai
"""End-to-end tests for POST /api/tools/search over the agent loop.

Both external dependencies are stubbed at their point of use, per this repo's
convention: the model at backend.app.tools.agent.litellm.acompletion, and the
Exa client at backend.app.tools.service.search.

Note the behaviour change from the pre-agent endpoint: the visitor's text is no
longer what reaches the search API. The model writes the query, so these tests
assert on the *model's* query rather than the visitor's.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.app.db.models import (
    LanguageGenerationRequest,
    SearchQuery,
    ServiceLogEntry,
    UsageLimit,
)
from backend.app.db.session import get_db_session
from backend.app.main import app
from backend.app.services import model_registry
from backend.app.services.web_search import ExaRateLimitError, ExaResult


@pytest.fixture(autouse=True)
def _gate_allows_everything(allow_all_moderation):
    """Every request here carries free text, which the shared gate now checks.

    The gate is not this file's subject, and with no `OPENAI_API_KEY` in the
    test environment it fails closed and would refuse all of them. Overridden
    per module rather than globally, so a test that *should* exercise the gate
    cannot pass by accident.
    """


#: LiteLLM reports the served model without its routing prefix, so the fake
#: responses do too -- normalize() must map it back to a real chain slug.
SERVED_MODEL_SLUG = model_registry.TOOL_MODEL_CHAIN[0]
SERVED_MODEL_BARE = SERVED_MODEL_SLUG.split("/", 1)[1]


class _FakeExecuteResult:
    """Mirrors the existing fake-session convention: ignores the actual
    statement and returns a canned result."""

    def __init__(self, scalar: object = None) -> None:
        self._scalar = scalar

    def scalar_one_or_none(self) -> object:
        return self._scalar


class _FakeSession:
    """Records ORM writes/commits in memory and returns pre-queued results
    for each execute() call in order, mirroring test_shared_services.py's
    _FakeSession pattern."""

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


class _FakeFunction:
    def __init__(self, name: str, arguments: str) -> None:
        self.name = name
        self.arguments = arguments


class _FakeToolCall:
    def __init__(self, call_id: str, name: str, arguments: str) -> None:
        self.id = call_id
        self.function = _FakeFunction(name, arguments)


class _FakeMessage:
    def __init__(self, content: str | None = None, tool_calls: list | None = None) -> None:
        self.content = content
        self.tool_calls = tool_calls


class _FakeChoice:
    def __init__(self, message: _FakeMessage) -> None:
        self.message = message


class _FakeResponse:
    def __init__(self, message: _FakeMessage, model: str = SERVED_MODEL_BARE) -> None:
        self.choices = [_FakeChoice(message)]
        self.model = model


def _search_call(query: str) -> _FakeResponse:
    return _FakeResponse(
        _FakeMessage(
            tool_calls=[_FakeToolCall("call_1", "web_search", json.dumps({"query": query}))]
        )
    )


def _answer(text: str) -> _FakeResponse:
    return _FakeResponse(_FakeMessage(content=text))


def _override_with(session: _FakeSession):
    async def _override() -> AsyncGenerator[_FakeSession, None]:
        yield session

    return _override


@pytest.fixture(autouse=True)
def _clear_cooldowns():
    model_registry.reset_cooldowns()
    yield
    model_registry.reset_cooldowns()


def _post(session: _FakeSession, model_responses: list, search_mock: object, query: str):
    app.dependency_overrides[get_db_session] = _override_with(session)
    try:
        with patch(
            "backend.app.tools.agent.litellm.acompletion",
            AsyncMock(side_effect=model_responses),
        ):
            with patch("backend.app.tools.service.search", search_mock):
                with TestClient(app) as client:
                    return client.post("/api/tools/search", json={"search_query": query})
    finally:
        app.dependency_overrides.clear()


def test_search_endpoint_returns_the_agents_answer_and_its_step_trace() -> None:
    session = _FakeSession(
        queued_results=[_FakeExecuteResult(scalar=None), _FakeExecuteResult(scalar=None)]
    )
    fake_results = [
        ExaResult(
            title="Result A",
            summary="Summary A",
            source="https://a.example",
            published_date="2026-07-14T00:00:00.000Z",
        ),
        # No date: Exa often cannot determine one for package indexes and docs
        # pages, and the UI has to cope rather than render "undefined".
        ExaResult(title="Result B", summary="Summary B", source="https://b.example"),
    ]
    search_mock = AsyncMock(return_value=fake_results)

    response = _post(
        session,
        [_search_call("Spec4 latest release notes"), _answer("The latest Spec4 release is v0.")],
        search_mock,
        "hey what's the latest Spec4 release?",
    )

    assert response.status_code == 200
    body = response.json()

    # The model authored the query -- the visitor's text is not what was searched.
    search_mock.assert_awaited_once_with("Spec4 latest release notes")
    assert body["queries"] == ["Spec4 latest release notes"]
    assert body["answer"] == "The latest Spec4 release is v0."
    assert body["model"] == SERVED_MODEL_SLUG
    assert body["iterations"] == 2

    # The publish date is carried end to end. Dropping it was what made a
    # stale *page* indistinguishable from a stale *answer* on screen -- the
    # visitor had no way to see that a top-ranked result was three years old.
    assert body["results"] == [
        {
            "title": "Result A",
            "summary": "Summary A",
            "source": "https://a.example",
            "rank": 1,
            "published_date": "2026-07-14T00:00:00.000Z",
        },
        {
            "title": "Result B",
            "summary": "Summary B",
            "source": "https://b.example",
            "rank": 2,
            "published_date": None,
        },
    ]

    kinds = [step["kind"] for step in body["steps"]]
    assert kinds == ["tool_call", "tool_result", "answer"]
    assert body["steps"][0]["detail"] == "Spec4 latest release notes"

    # Both the visitor's question and the model's query are persisted.
    persisted = [obj.text for obj in session.added if isinstance(obj, SearchQuery)]
    assert persisted == ["hey what's the latest Spec4 release?", "Spec4 latest release notes"]

    # Generation is reserved once for the whole loop; search once per call.
    usage = [obj for obj in session.added if isinstance(obj, UsageLimit)]
    assert [row.capability for row in usage] == ["generation", "search"]

    generation_rows = [obj for obj in session.added if isinstance(obj, LanguageGenerationRequest)]
    assert generation_rows[0].model_name == SERVED_MODEL_SLUG

    log_rows = [obj for obj in session.added if isinstance(obj, ServiceLogEntry)]
    assert log_rows[0].app_name == "Tool-Use Example App"


def test_search_endpoint_answers_without_searching_when_the_model_declines() -> None:
    """The model may decide no tool call is warranted -- that is still a valid run."""
    session = _FakeSession(queued_results=[_FakeExecuteResult(scalar=None)])
    search_mock = AsyncMock()

    response = _post(session, [_answer("Two plus two is four.")], search_mock, "What is 2 + 2?")

    assert response.status_code == 200
    body = response.json()
    search_mock.assert_not_awaited()
    assert body["answer"] == "Two plus two is four."
    assert body["queries"] == []
    assert body["results"] == []

    # No search capability was consumed, because no search happened.
    usage = [obj for obj in session.added if isinstance(obj, UsageLimit)]
    assert [row.capability for row in usage] == ["generation"]


def test_search_endpoint_returns_clear_unavailable_message_on_exa_rate_limit() -> None:
    session = _FakeSession(
        queued_results=[_FakeExecuteResult(scalar=None), _FakeExecuteResult(scalar=None)]
    )

    response = _post(
        session,
        [_search_call("some query")],
        AsyncMock(side_effect=ExaRateLimitError("rate limited")),
        "latest Spec4 release",
    )

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "error"
    assert "temporarily unavailable" in body["detail"]

    # The invocation is still recorded, even though it failed.
    assert any(isinstance(obj, SearchQuery) for obj in session.added)
    assert any(isinstance(obj, ServiceLogEntry) for obj in session.added)


def test_search_endpoint_returns_clear_unavailable_message_when_search_cap_reached() -> None:
    """Generation is available, but the search capability is exhausted."""
    exhausted = UsageLimit(capability="search", used=30, cap=30)
    session = _FakeSession(
        queued_results=[_FakeExecuteResult(scalar=None), _FakeExecuteResult(scalar=exhausted)]
    )
    search_mock = AsyncMock()

    response = _post(session, [_search_call("some query")], search_mock, "latest Spec4 release")

    search_mock.assert_not_awaited()
    assert response.status_code == 503
    body = response.json()
    assert "temporarily unavailable" in body["detail"]


def test_search_endpoint_reports_a_model_outage_distinctly_from_a_search_cap() -> None:
    """An exhausted model chain is a different operator problem from a search cap."""
    exhausted = UsageLimit(capability="generation", used=100, cap=100)
    session = _FakeSession(queued_results=[_FakeExecuteResult(scalar=exhausted)])
    search_mock = AsyncMock()

    response = _post(session, [], search_mock, "latest Spec4 release")

    search_mock.assert_not_awaited()
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert "language model" in detail
    assert "search tool" not in detail
