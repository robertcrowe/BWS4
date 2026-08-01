# Built with Spec4 AI - https://spec4.ai
"""Unit tests for the shared PydanticAI lane.

The headline assertions are the ones that keep two model lanes from rotting
apart: this lane must resolve its slugs from the *same* registry the LiteLLM
lane reads, honour the same cooldown bench, and gain a provider without any
example app being edited. Nothing here calls a model or touches a database.
"""

from __future__ import annotations

import pytest
from pydantic_ai.models.fallback import FallbackModel

from backend.app.services import agent_runtime, model_registry
from backend.app.services.agent_runtime import (
    AGENT_LANE_KNOWN_BAD,
    TOOL_LANE_KNOWN_BAD,
    AgentLaneError,
    ProviderAdapter,
    lane_chain,
    openai_compatible_adapter,
)


@pytest.fixture(autouse=True)
def _clean_lane():
    """Registration and cooldowns are process-local; they must not leak."""
    model_registry.reset_cooldowns()
    agent_runtime.reset_providers()
    yield
    model_registry.reset_cooldowns()
    agent_runtime.reset_providers()


def test_the_lane_reads_the_same_chain_as_the_litellm_lane() -> None:
    """One model list, two lanes.

    The lane may filter (unregistered providers, probe exclusions) but must not
    reorder or invent: add a model to GENERATION_MODEL_CHAIN and it appears here
    for free, which is the whole point of not keeping a second list.
    """
    litellm_lane = model_registry.active_chain(model_registry.GENERATION_MODEL_CHAIN)
    expected = [slug for slug in litellm_lane if slug not in AGENT_LANE_KNOWN_BAD]

    assert lane_chain() == expected


def test_the_lane_now_spans_both_providers() -> None:
    """The reason this refactor happened: failover that survives one provider."""
    providers = {model_registry.provider_of(slug) for slug in lane_chain()}

    assert providers == {"groq", "openrouter"}


def test_groq_leads_because_its_free_tier_is_metered_per_model() -> None:
    """Order is inherited from the registry, and the registry's order is the point.

    Groq meters its free tier per model; OpenRouter's is one account-wide pool
    shared with the other example apps (50 requests/day unfunded, 1,000/day once
    $10 of credits has been purchased). A lane that led with OpenRouter would
    drain the shared quota first and take the fallback tail out from under RAG,
    single-call, and tool-use along with it.
    """
    assert model_registry.provider_of(lane_chain()[0]) == "groq"


def test_a_probe_exclusion_applies_to_this_lane_only() -> None:
    """The standing rule, as an assertion.

    `groq/llama-3.1-8b-instant` works in both shipped chains and fails here:
    asked for typed output it invents a tool that was never offered. Excluding
    it from this lane must not remove it from the others.
    """
    assert "groq/llama-3.1-8b-instant" in AGENT_LANE_KNOWN_BAD
    assert "groq/llama-3.1-8b-instant" not in lane_chain()

    assert "groq/llama-3.1-8b-instant" in model_registry.GENERATION_MODEL_CHAIN
    assert "groq/llama-3.1-8b-instant" in model_registry.TOOL_MODEL_CHAIN


def test_a_step_with_tools_gets_a_narrower_chain_than_one_without() -> None:
    """A fourth capability, with a fourth probe result behind it.

    Offering a function tool and a typed-output tool at once is not implied by
    doing either alone: four slugs that return clean typed output cannot do it
    while calling a tool -- two never stop calling it, one emits malformed
    call syntax, one returns an empty answer.
    """
    plain = lane_chain()
    with_tools = lane_chain(tools=True)

    assert set(with_tools) < set(plain)
    assert set(plain) - set(with_tools) == set(TOOL_LANE_KNOWN_BAD) & set(plain)


def test_the_tool_capable_chain_still_spans_both_providers() -> None:
    """Failover that survives one provider must survive the narrowing too.

    The exclusions cut the chain to three entries; if they all sat on one
    provider, an outage there would take the planning app's executors down with
    no fallback at all.
    """
    providers = {model_registry.provider_of(slug) for slug in lane_chain(tools=True)}

    assert providers == {"groq", "openrouter"}


def test_a_tool_exclusion_does_not_leak_into_the_toolless_chain() -> None:
    """The standing rule again, in the direction this list makes tempting.

    These models are fine for the chained-calls app, which asks for typed output
    and offers no tools. Excluding them there would remove working capacity for
    a fault they do not have in that use.
    """
    plain = lane_chain()

    assert "groq/llama-3.3-70b-versatile" in plain
    assert "groq/llama-3.3-70b-versatile" not in lane_chain(tools=True)


def test_a_benched_model_disappears_from_this_lane_too() -> None:
    """Cooldowns are shared framework state, not one lane's private note."""
    before = lane_chain()
    head = before[0]

    benched = model_registry.note_failure(
        RuntimeError(f"No endpoints found for {head.split('/', 1)[1]}")
    )
    assert head in benched
    assert head not in lane_chain()
    assert len(lane_chain()) == len(before) - 1


def test_slugs_from_an_unregistered_provider_are_skipped_not_crashed_on() -> None:
    """A chain entry this lane cannot construct is routed around, not fatal.

    The LiteLLM lane may well support a provider this one has no adapter for.
    Dropping the slug keeps the two lanes independently extensible.
    """
    chain = ["openrouter/nvidia/nemotron-3-super-120b-a12b:free", "cerebras/some-model"]

    assert lane_chain(chain) == ["openrouter/nvidia/nemotron-3-super-120b-a12b:free"]


def test_registering_a_provider_is_all_it_takes_to_reach_its_models() -> None:
    """The extensibility contract, exercised end to end.

    A third provider must need no edit in `chained_calls/` or any other example
    app — only an adapter here, a credential entry in the registry, and slugs in
    a chain.
    """
    chain = ["acme/fast-1", "openrouter/nvidia/nemotron-3-super-120b-a12b:free"]

    # Unregistered and uncredentialed: routed around.
    assert lane_chain(chain) == ["openrouter/nvidia/nemotron-3-super-120b-a12b:free"]

    model_registry.PROVIDER_CREDENTIALS["acme"] = model_registry.ProviderCredential(
        settings_attr="openrouter_api_key", env_var="ACME_API_KEY"
    )
    agent_runtime.register_provider(
        openai_compatible_adapter(name="acme", base_url="https://api.acme.test/v1")
    )
    try:
        assert lane_chain(chain) == chain
        model = agent_runtime.build_fallback_model(chain)
        assert isinstance(model, FallbackModel)
    finally:
        del model_registry.PROVIDER_CREDENTIALS["acme"]


def test_a_provider_with_no_credential_is_dropped_from_every_chain() -> None:
    """Fail closed: better to route around a provider than 401 on it first."""
    chain = ["mystery/model-x", "groq/openai/gpt-oss-120b"]

    assert "mystery" not in model_registry.configured_providers()
    assert model_registry.configured_chain(chain) == ["groq/openai/gpt-oss-120b"]


def test_the_built_model_pairs_each_slug_with_its_own_provider() -> None:
    """One FallbackModel, several providers — the reason this is worth having.

    A single shared credential would be wrong for a mixed chain, so each entry
    is constructed by its own adapter.
    """
    chain = ["groq/openai/gpt-oss-120b", "openrouter/nvidia/nemotron-3-super-120b-a12b:free"]
    model = agent_runtime.build_fallback_model(chain)

    base_urls = [str(inner.base_url) for inner in model.models]
    assert "api.groq.com" in base_urls[0]
    assert "openrouter.ai" in base_urls[1]


def test_an_empty_lane_fails_loudly() -> None:
    """Better an explicit error than a FallbackModel with no models."""
    with pytest.raises(AgentLaneError):
        lane_chain(["cerebras/nothing-registered"])


def test_the_built_in_providers_are_registered_on_import() -> None:
    """A caller should not have to bootstrap the providers this build ships."""
    assert agent_runtime.registered_providers() == {"openrouter", "groq"}


def test_an_adapter_reuses_one_provider_object_across_calls() -> None:
    """Each provider owns an HTTP connection pool; one per request would leak."""
    adapter: ProviderAdapter = openai_compatible_adapter(
        name="openrouter", base_url="https://example.test/v1"
    )
    first = adapter.build_model("a")
    second = adapter.build_model("b")

    assert first.client is second.client
