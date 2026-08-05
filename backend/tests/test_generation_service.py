# Built with Spec4 AI - https://spec4.ai
"""Tests for the shared text-generation service's routing.

What these protect is the framework property: generation and tool calling go
through *one* model-routing layer, so an example app can't quietly acquire its
own fallback behaviour, its own credential handling, or its own idea of which
models are dead.
"""

from __future__ import annotations

from collections.abc import Iterator

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backend.app.services import generation, model_registry


@pytest.fixture(autouse=True)
def _clear_cooldowns() -> Iterator[None]:
    model_registry.reset_cooldowns()
    yield
    model_registry.reset_cooldowns()


def _response(content: str, model: str) -> SimpleNamespace:
    """A minimal stand-in for a LiteLLM completion response."""
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        model=model,
    )


def test_generation_passes_the_whole_shared_chain_as_fallbacks() -> None:
    """Failover is LiteLLM's job over the registry's chain -- not a local pair."""
    chain = model_registry.active_chain(model_registry.GENERATION_MODEL_CHAIN)

    with patch(
        "backend.app.services.generation.litellm.completion",
        return_value=_response("hello", chain[0]),
    ) as completion:
        generation.generate_text(system_prompt="sys", user_prompt="user")

    kwargs = completion.call_args.kwargs
    assert kwargs["model"] == chain[0]
    assert kwargs["fallbacks"] == chain[1:]
    assert len(chain) > 2, "a two-model chain is what this rework replaced"


def test_generation_never_passes_a_single_api_key() -> None:
    """One key cannot serve a chain that may span providers.

    LiteLLM applies `api_key=` to every fallback, so a cross-provider chain
    would authenticate the wrong service. Credentials go via the environment
    instead, which is why ensure_provider_credentials exists.
    """
    chain = model_registry.active_chain(model_registry.GENERATION_MODEL_CHAIN)

    with patch(
        "backend.app.services.generation.litellm.completion",
        return_value=_response("hello", chain[0]),
    ) as completion:
        with patch.object(model_registry, "ensure_provider_credentials") as ensure:
            generation.generate_text(system_prompt="sys", user_prompt="user")

    assert "api_key" not in completion.call_args.kwargs
    ensure.assert_called_once()


def test_generation_reports_the_model_that_actually_served() -> None:
    """LiteLLM echoes the served model without its routing prefix."""
    served = model_registry.GENERATION_MODEL_CHAIN[1]
    bare = served.split("/", 1)[1]

    with patch(
        "backend.app.services.generation.litellm.completion",
        return_value=_response("hello", bare),
    ):
        result = generation.generate_text(system_prompt="sys", user_prompt="user")

    assert result.text == "hello"
    assert result.model == served, "the served model must be normalized to its chain slug"


def test_generation_failure_benches_a_withdrawn_model_for_every_capability() -> None:
    """The bench is shared: a model gone for RAG is gone for the tool agent too.

    The slug used here sits in both chains, which is exactly the case that
    would break if each app kept its own list.
    """
    shared_slug = "openrouter/inclusionai/ling-3.0-flash:free"
    assert shared_slug in model_registry.GENERATION_MODEL_CHAIN
    assert shared_slug in model_registry.TOOL_MODEL_CHAIN

    bare = shared_slug.split("/", 1)[1]
    with patch(
        "backend.app.services.generation.litellm.completion",
        side_effect=RuntimeError(f"NotFoundError: {bare} - No endpoints found for this model"),
    ):
        with pytest.raises(generation.GenerationServiceError):
            generation.generate_text(system_prompt="sys", user_prompt="user")

    assert shared_slug not in model_registry.active_chain(model_registry.GENERATION_MODEL_CHAIN)
    assert shared_slug not in model_registry.active_chain(model_registry.TOOL_MODEL_CHAIN)


def test_generation_rejects_an_empty_response_rather_than_returning_it() -> None:
    """Some free models put their answer in `reasoning` and leave content empty."""
    with patch(
        "backend.app.services.generation.litellm.completion",
        return_value=_response("", model_registry.GENERATION_MODEL_CHAIN[0]),
    ):
        with pytest.raises(generation.GenerationServiceError):
            generation.generate_text(system_prompt="sys", user_prompt="user")
