# Built with Spec4 AI - https://spec4.ai
"""The tool_use_integration agent loop: the canonical function-calling pattern.

The model is given a `web_search` tool *schema* and decides for itself whether
to call it, what query to send, and whether one search was enough. Nothing in
this module inspects the visitor's question or routes it -- the routing is the
model's decision, which is the whole point of the demonstration.

One loop iteration is:

    model  -> tool_call(query)      the model authors its own query
    us     -> execute the search    via the injected `execute_search`
    model  <- tool result           fed back into the same conversation
    model  -> tool_call | answer    search again, or answer from results

Search execution is injected rather than imported so this module stays free of
usage-limit, persistence, and logging concerns -- those live in tools/service.py
-- and so the loop is testable without a database or a live Exa key.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import litellm
import structlog

from backend.app.core.config import get_settings
from backend.app.services import model_registry
from backend.app.tools.exa_client import ExaClientError, ExaRateLimitError, ExaResult
from backend.app.tools.prompt_loader import load_prompt

logger = structlog.get_logger()

#: Hard ceiling on model turns. The loop must terminate even if the model
#: would happily keep searching forever; free-tier quota is the binding
#: constraint, not patience.
MAX_ITERATIONS = 3

#: Hard ceiling on actual search calls, independent of iterations: a model
#: that emits two tool calls in one turn must not double-spend the quota.
MAX_SEARCHES = 3

REQUEST_TIMEOUT_SECONDS = 45
MAX_RESPONSE_TOKENS = 1024

SEARCH_TOOL_NAME = "web_search"

#: The tool schema handed to the model. This -- not any Python branching -- is
#: what tells the model the capability exists and how to invoke it.
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": SEARCH_TOOL_NAME,
            "description": (
                "Search the public web for current information. Use this whenever "
                "the question concerns recent events, news, or specific facts you "
                "are not confident about. Returns ranked results with titles, "
                "summaries, and source URLs."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "The search query. Write an effective query rather than "
                            "repeating the user's question verbatim."
                        ),
                    }
                },
                "required": ["query"],
            },
        },
    }
]


class AgentError(Exception):
    """Raised when the agent loop can't produce an answer."""


@dataclass(frozen=True)
class AgentStep:
    """One observable step in the loop, for the demo's progress trace."""

    kind: str  # "decision" | "tool_call" | "tool_result" | "answer"
    label: str
    detail: str


@dataclass
class AgentRun:
    """The completed loop: what the model did, and what it concluded."""

    answer: str
    steps: list[AgentStep] = field(default_factory=list)
    results: list[ExaResult] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)
    model: str = ""
    iterations: int = 0


SearchExecutor = Callable[[str], Awaitable[list[ExaResult]]]


def _assistant_message(message: object) -> dict:
    """Rebuild an assistant turn as a plain dict for the next request.

    LiteLLM's message objects carry provider-specific and None-valued fields
    that some OpenRouter backends reject when echoed back, so the turn is
    reconstructed explicitly rather than round-tripped via model_dump().

    Args:
        message: The message object from a completion response.

    Returns:
        An OpenAI-shaped assistant message dict.
    """
    calls = getattr(message, "tool_calls", None) or []
    rebuilt: dict = {"role": "assistant", "content": getattr(message, "content", "") or ""}
    if calls:
        rebuilt["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.function.name,
                    "arguments": call.function.arguments,
                },
            }
            for call in calls
        ]
    return rebuilt


def _parse_query(call: object) -> str | None:
    """Extract the `query` argument from a tool call, if it is usable.

    Args:
        call: A tool_call object from the model's response.

    Returns:
        The query string, or None if the arguments were malformed.
    """
    try:
        arguments = json.loads(call.function.arguments)
    except (ValueError, TypeError):
        return None
    query = arguments.get("query")
    if not isinstance(query, str) or not query.strip():
        return None
    return query.strip()


async def _complete(messages: list[dict], *, pinned: str | None, force_answer: bool) -> object:
    """Call the model over the free-model chain.

    LiteLLM walks `fallbacks` itself on failure, so there is no hand-rolled
    retry logic here -- consistent with services/generation.py.

    Args:
        messages: The conversation so far.
        pinned: A model to prefer, once one has successfully served a turn,
            so a single loop keeps a single brain.
        force_answer: If True, forbid further tool calls so the model must
            answer.

    Returns:
        The LiteLLM completion response.

    Raises:
        AgentError: If every model in the chain fails.
    """
    chain = model_registry.active_chain()
    if pinned and pinned in chain:
        chain = [pinned] + [model for model in chain if model != pinned]

    model_registry.ensure_provider_credentials()

    # Two ways to forbid a further tool call, tried in order, because neither
    # works everywhere:
    #   tool_choice="none" -- keeps the schema present, which providers that
    #     validate history against `tools` require. But Groq rejects it outright
    #     when the model wants a tool ("Tool choice is none, but model called a
    #     tool", HTTP 400).
    #   omit `tools` -- universally accepted as a request, but providers that
    #     cross-check tool_calls in the history against a declared schema can
    #     400 on the history instead.
    # Asking for an answer is the loop's only termination path, so it has to
    # survive both. Normal turns use a single "auto" attempt.
    if force_answer:
        attempts: list[dict] = [
            {"tools": TOOL_SCHEMAS, "tool_choice": "none"},
            {},
        ]
    else:
        attempts = [{"tools": TOOL_SCHEMAS, "tool_choice": "auto"}]

    last_error: Exception | None = None
    for extra in attempts:
        try:
            return await litellm.acompletion(
                model=chain[0],
                messages=messages,
                fallbacks=chain[1:],
                num_retries=1,
                timeout=REQUEST_TIMEOUT_SECONDS,
                max_tokens=MAX_RESPONSE_TOKENS,
                **extra,
            )
        except Exception as exc:  # noqa: BLE001 - any provider/transport failure
            last_error = exc
            model_registry.note_failure(exc)
            logger.warning(
                "tool_agent_completion_attempt_failed",
                force_answer=force_answer,
                tool_choice=extra.get("tool_choice", "omitted"),
                error=str(exc)[:200],
            )

    raise AgentError(str(last_error)) from last_error


async def run_agent(question: str, *, execute_search: SearchExecutor) -> AgentRun:
    """Run the tool-calling loop until the model answers or hits the ceiling.

    Google-style docstring per project convention.

    Args:
        question: The visitor's question, passed to the model as-is. The model
            -- not this function -- decides what to search for.
        execute_search: Async callable that performs one search and returns
            its results. Injected so usage limits, persistence, and logging
            stay in tools/service.py.

    Returns:
        The completed AgentRun: final answer, observable step trace, the
        deduplicated union of every result the model saw, and the queries it
        wrote.

    Raises:
        AgentError: If the model chain is exhausted, or the loop finishes
            without producing an answer.
        ExaRateLimitError | ExaClientError: If the very first search fails.
            A later search failing is reported back to the model instead, so
            it can answer from the results it already has.
    """
    messages: list[dict] = [
        {"role": "system", "content": load_prompt("agent_v1")},
        {"role": "user", "content": question},
    ]

    run = AgentRun(answer="")
    seen_sources: set[str] = set()
    pinned: str | None = None
    searches = 0

    for iteration in range(MAX_ITERATIONS):
        run.iterations = iteration + 1
        response = await _complete(messages, pinned=pinned, force_answer=False)

        served = getattr(response, "model", None)
        if served:
            pinned = model_registry.normalize(served)
            run.model = pinned

        message = response.choices[0].message
        calls = getattr(message, "tool_calls", None) or []

        if not calls:
            content = (getattr(message, "content", "") or "").strip()
            if content:
                run.answer = content
                run.steps.append(
                    AgentStep(
                        kind="answer",
                        label="Answered",
                        detail="Model answered from the information available.",
                    )
                )
                break
            # No call and no content: nothing more to work with.
            break

        messages.append(_assistant_message(message))

        for call in calls:
            if call.function.name != SEARCH_TOOL_NAME:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "name": call.function.name,
                        "content": json.dumps({"error": "No such tool."}),
                    }
                )
                continue

            query = _parse_query(call)
            if query is None:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "name": SEARCH_TOOL_NAME,
                        "content": json.dumps(
                            {"error": "Malformed arguments; expected {'query': string}."}
                        ),
                    }
                )
                continue

            if searches >= MAX_SEARCHES:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "name": SEARCH_TOOL_NAME,
                        "content": json.dumps(
                            {"error": "Search budget exhausted. Answer with what you have."}
                        ),
                    }
                )
                continue

            run.queries.append(query)
            run.steps.append(
                AgentStep(
                    kind="tool_call",
                    label=f"Called web_search (#{searches + 1})",
                    detail=query,
                )
            )
            searches += 1

            try:
                results = await execute_search(query)
            except (ExaRateLimitError, ExaClientError):
                # The first failure has nothing to fall back on; a later one
                # can be reported to the model, which still has earlier results.
                if not run.results:
                    raise
                logger.warning("tool_agent_search_failed_midloop", query=query)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "name": SEARCH_TOOL_NAME,
                        "content": json.dumps(
                            {"error": "Search unavailable. Answer from earlier results."}
                        ),
                    }
                )
                continue

            for result in results:
                if result.source not in seen_sources:
                    seen_sources.add(result.source)
                    run.results.append(result)

            run.steps.append(
                AgentStep(
                    kind="tool_result",
                    label=f"Received {len(results)} result(s)",
                    detail="; ".join(r.title for r in results[:3]) or "No results returned.",
                )
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "name": SEARCH_TOOL_NAME,
                    "content": json.dumps(
                        {
                            "results": [
                                {"title": r.title, "summary": r.summary, "url": r.source}
                                for r in results
                            ]
                        }
                    ),
                }
            )

    if not run.answer:
        # The model used every iteration searching. Take the tools away and
        # require an answer from what it has, rather than returning nothing.
        logger.info("tool_agent_forcing_answer", iterations=run.iterations)
        run.steps.append(
            AgentStep(
                kind="decision",
                label="Reached search limit",
                detail="Answering from the results gathered so far.",
            )
        )
        response = await _complete(messages, pinned=pinned, force_answer=True)
        content = (response.choices[0].message.content or "").strip()
        if not content:
            raise AgentError("The agent finished without producing an answer.")
        run.answer = content
        run.steps.append(
            AgentStep(kind="answer", label="Answered", detail="Answer produced under the limit.")
        )

    logger.info(
        "tool_agent_completed",
        model=run.model,
        iterations=run.iterations,
        searches=len(run.queries),
        results=len(run.results),
    )
    return run
