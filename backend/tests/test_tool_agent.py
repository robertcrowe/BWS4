# Built with Spec4 AI - https://spec4.ai
"""Tests for the tool_use_integration agent loop.

The model is stubbed at backend.app.tools.agent.litellm.acompletion -- the name
as imported into agent.py, matching this repo's patch-at-point-of-use
convention. Async entry points are driven with asyncio.run() rather than
pytest-asyncio, per the existing convention in test_shared_services.py.

The point of these tests is that routing is the *model's* decision: each one
drives a different model behaviour and asserts the loop follows it.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from backend.app.services import model_registry
from backend.app.tools.agent import (
    MAX_ITERATIONS,
    MAX_SEARCHES,
    AgentError,
    run_agent,
)
from backend.app.tools.exa_client import ExaClientError, ExaRateLimitError, ExaResult

#: LiteLLM reports the served model without its routing prefix, so the fake
#: responses do too -- normalize() must map it back to a real chain slug.
SERVED_MODEL_SLUG = model_registry.TOOL_MODEL_CHAIN[0]
SERVED_MODEL_BARE = SERVED_MODEL_SLUG.split("/", 1)[1]


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


def _search_call(query: str, call_id: str = "call_1") -> _FakeMessage:
    """A model turn that calls web_search with the given query."""
    return _FakeMessage(
        content=None,
        tool_calls=[_FakeToolCall(call_id, "web_search", json.dumps({"query": query}))],
    )


def _answer(text: str) -> _FakeMessage:
    """A model turn that answers instead of calling a tool."""
    return _FakeMessage(content=text, tool_calls=None)


def _results(*titles: str) -> list[ExaResult]:
    """Results with a distinct source per title, so dedup-by-URL isn't triggered
    accidentally by the helper itself."""
    return [
        ExaResult(
            title=title,
            summary=f"Summary of {title}",
            source=f"https://example.com/{title.lower().replace(' ', '-')}",
        )
        for title in titles
    ]


@pytest.fixture(autouse=True)
def _clear_cooldowns():
    """Cooldown state is process-local and must not leak between tests."""
    model_registry.reset_cooldowns()
    yield
    model_registry.reset_cooldowns()


def test_agent_uses_the_query_the_model_wrote_not_the_visitors_question() -> None:
    """The defining property of tool use: the model authors the arguments."""
    executed: list[str] = []

    async def execute_search(query: str) -> list[ExaResult]:
        executed.append(query)
        return _results("Webb result")

    responses = [
        _FakeResponse(_search_call("JWST discoveries 2026")),
        _FakeResponse(_answer("Recent coverage indicates Webb found water vapour.")),
    ]

    with patch("backend.app.tools.agent.litellm.acompletion", AsyncMock(side_effect=responses)):
        run = asyncio.run(
            run_agent(
                "hey, so what have astronomers learned from JWST lately??",
                execute_search=execute_search,
            )
        )

    assert executed == ["JWST discoveries 2026"]
    assert "hey, so what" not in executed[0]
    assert run.queries == ["JWST discoveries 2026"]
    assert run.answer == "Recent coverage indicates Webb found water vapour."
    assert run.model == SERVED_MODEL_SLUG


def test_agent_does_not_search_when_the_model_decides_it_is_unnecessary() -> None:
    """Routing is a model decision, so the model may decline to route at all."""
    execute_search = AsyncMock()

    with patch(
        "backend.app.tools.agent.litellm.acompletion",
        AsyncMock(side_effect=[_FakeResponse(_answer("Two plus two is four."))]),
    ):
        run = asyncio.run(run_agent("What is 2 + 2?", execute_search=execute_search))

    execute_search.assert_not_awaited()
    assert run.queries == []
    assert run.results == []
    assert run.answer == "Two plus two is four."
    assert run.iterations == 1


def test_agent_searches_again_when_the_model_refines_its_query() -> None:
    """Iteration: the model sees results and chooses to search a second time."""
    executed: list[str] = []

    async def execute_search(query: str) -> list[ExaResult]:
        executed.append(query)
        return _results(f"Result for {query}")

    responses = [
        _FakeResponse(_search_call("Mars rover status", "call_1")),
        _FakeResponse(_search_call("Perseverance rover status 2026", "call_2")),
        _FakeResponse(_answer("Perseverance is still operating in Jezero Crater.")),
    ]

    with patch("backend.app.tools.agent.litellm.acompletion", AsyncMock(side_effect=responses)):
        run = asyncio.run(
            run_agent("How's the Mars rover doing?", execute_search=execute_search)
        )

    assert executed == ["Mars rover status", "Perseverance rover status 2026"]
    assert run.iterations == 3
    assert len(run.results) == 2
    assert [step.kind for step in run.steps].count("tool_call") == 2


def test_agent_deduplicates_results_seen_across_iterations() -> None:
    """Two searches returning the same URL must not produce a duplicate result."""
    repeated = [ExaResult(title="Same", summary="Same summary", source="https://same.example")]

    responses = [
        _FakeResponse(_search_call("first", "call_1")),
        _FakeResponse(_search_call("second", "call_2")),
        _FakeResponse(_answer("Done.")),
    ]

    with patch("backend.app.tools.agent.litellm.acompletion", AsyncMock(side_effect=responses)):
        run = asyncio.run(run_agent("q", execute_search=AsyncMock(return_value=repeated)))

    assert len(run.results) == 1


def test_agent_forces_an_answer_when_the_model_never_stops_searching() -> None:
    """The loop must terminate even if the model would keep going."""
    always_searching = [
        _FakeResponse(_search_call(f"query {i}", f"call_{i}")) for i in range(MAX_ITERATIONS)
    ]
    forced = _FakeResponse(_answer("Answering with what I found."))
    acompletion = AsyncMock(side_effect=[*always_searching, forced])

    with patch("backend.app.tools.agent.litellm.acompletion", acompletion):
        run = asyncio.run(
            run_agent("q", execute_search=AsyncMock(return_value=_results("R")))
        )

    assert run.answer == "Answering with what I found."
    assert acompletion.await_count == MAX_ITERATIONS + 1

    # The final call must forbid further tool calls, or the model could keep
    # searching -- but it must keep sending the schema, since the history now
    # contains tool_calls that some providers validate against it.
    final_kwargs = acompletion.await_args_list[-1].kwargs
    assert final_kwargs["tool_choice"] == "none"
    assert final_kwargs["tools"] == acompletion.await_args_list[0].kwargs["tools"]
    assert any(step.kind == "decision" for step in run.steps)


def test_agent_stops_spending_search_quota_at_the_ceiling() -> None:
    """A model emitting many calls in one turn must not outrun MAX_SEARCHES."""
    many_calls = _FakeMessage(
        content=None,
        tool_calls=[
            _FakeToolCall(f"call_{i}", "web_search", json.dumps({"query": f"q{i}"}))
            for i in range(MAX_SEARCHES + 3)
        ],
    )
    execute_search = AsyncMock(return_value=_results("R"))

    with patch(
        "backend.app.tools.agent.litellm.acompletion",
        AsyncMock(side_effect=[_FakeResponse(many_calls), _FakeResponse(_answer("Done."))]),
    ):
        run = asyncio.run(run_agent("q", execute_search=execute_search))

    assert execute_search.await_count == MAX_SEARCHES
    assert len(run.queries) == MAX_SEARCHES


def test_agent_reports_a_later_search_failure_back_to_the_model() -> None:
    """Losing the second search shouldn't discard the first one's results."""
    execute_search = AsyncMock(
        side_effect=[_results("Good result"), ExaClientError("upstream exploded")]
    )
    responses = [
        _FakeResponse(_search_call("first", "call_1")),
        _FakeResponse(_search_call("second", "call_2")),
        _FakeResponse(_answer("Based on the first search, here is the answer.")),
    ]

    with patch("backend.app.tools.agent.litellm.acompletion", AsyncMock(side_effect=responses)):
        run = asyncio.run(run_agent("q", execute_search=execute_search))

    assert run.answer == "Based on the first search, here is the answer."
    assert len(run.results) == 1


def test_agent_propagates_a_first_search_failure() -> None:
    """With no results to fall back on, the failure must surface."""
    with patch(
        "backend.app.tools.agent.litellm.acompletion",
        AsyncMock(side_effect=[_FakeResponse(_search_call("first"))]),
    ):
        with pytest.raises(ExaRateLimitError):
            asyncio.run(
                run_agent(
                    "q",
                    execute_search=AsyncMock(side_effect=ExaRateLimitError("rate limited")),
                )
            )


def test_agent_tells_the_model_when_its_arguments_are_malformed() -> None:
    """A bad tool call is recoverable: report it and let the model retry."""
    malformed = _FakeMessage(
        content=None,
        tool_calls=[_FakeToolCall("call_1", "web_search", "{not json at all")],
    )
    execute_search = AsyncMock(return_value=_results("R"))

    with patch(
        "backend.app.tools.agent.litellm.acompletion",
        AsyncMock(
            side_effect=[
                _FakeResponse(malformed),
                _FakeResponse(_search_call("a proper query", "call_2")),
                _FakeResponse(_answer("Recovered.")),
            ]
        ),
    ):
        run = asyncio.run(run_agent("q", execute_search=execute_search))

    execute_search.assert_awaited_once_with("a proper query")
    assert run.answer == "Recovered."


def test_agent_raises_when_every_model_in_the_chain_fails() -> None:
    with patch(
        "backend.app.tools.agent.litellm.acompletion",
        AsyncMock(side_effect=RuntimeError("all models down")),
    ):
        with pytest.raises(AgentError):
            asyncio.run(run_agent("q", execute_search=AsyncMock()))


def test_agent_passes_the_whole_chain_as_fallbacks() -> None:
    """Failover is LiteLLM's job, driven by the real request -- not a probe."""
    acompletion = AsyncMock(side_effect=[_FakeResponse(_answer("Done."))])

    with patch("backend.app.tools.agent.litellm.acompletion", acompletion):
        asyncio.run(run_agent("q", execute_search=AsyncMock()))

    kwargs = acompletion.await_args_list[0].kwargs
    chain = model_registry.active_chain()
    assert kwargs["model"] == chain[0]
    assert kwargs["fallbacks"] == chain[1:]
    assert kwargs["tools"][0]["function"]["name"] == "web_search"
