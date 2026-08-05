# Built with Spec4 AI - https://spec4.ai
"""Unit tests for the shared PydanticAI lane.

The headline assertions are the ones that keep two model lanes from rotting
apart: this lane must resolve its slugs from the *same* registry the LiteLLM
lane reads, honour the same cooldown bench, and gain a provider without any
example app being edited. Nothing here calls a model or touches a database.
"""

from __future__ import annotations

from collections.abc import Iterator

from unittest.mock import patch

import pytest
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.models.fallback import FallbackModel
from structlog.testing import capture_logs

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
def _clean_lane() -> Iterator[None]:
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


def test_the_two_exclusion_sets_are_alternatives_rather_than_layers() -> None:
    """A fourth capability, with a fourth probe result behind it.

    The tools case is *different*, not merely harder. It was modelled as harder
    -- tools-mode excluded both sets, so its chain was necessarily a subset --
    until `groq/llama-3.1-8b-instant` was measured failing the tool-less case
    (2 of 3 probes 400) while passing the tools case (10 of 12). Its recorded
    tool-less fault is that it invents a tool it was never offered; give it a
    real one and there is nothing to invent.

    So each set governs its own case and neither may be applied to the other's.
    Asserting a subset relation here is what would re-impose the layering.
    """
    plain = set(lane_chain())
    with_tools = set(lane_chain(tools=True))

    # Each chain excludes exactly its own set, and nothing else.
    assert plain.isdisjoint(AGENT_LANE_KNOWN_BAD)
    assert with_tools.isdisjoint(TOOL_LANE_KNOWN_BAD)

    # Neither is a subset of the other: each carries a model the other excludes.
    assert not with_tools <= plain
    assert not plain <= with_tools


def test_the_tool_capable_chain_still_spans_both_providers() -> None:
    """Failover that survives one provider must survive the narrowing too.

    The exclusions cut the chain to five entries; if they all sat on one
    provider, an outage there would take the planning app's executors down with
    no fallback at all.
    """
    providers = {model_registry.provider_of(slug) for slug in lane_chain(tools=True)}

    assert providers == {"groq", "openrouter"}


def test_an_exclusion_does_not_leak_between_the_two_cases() -> None:
    """The standing rule again, now enforced in both directions.

    `groq/openai/gpt-oss-20b` loops on the search tool until the request limit
    ends the step, and is excluded with tools. It returns clean typed output
    without them, and excluding it there would remove working capacity from the
    chained-calls app for a fault it does not have in that use.

    `groq/llama-3.1-8b-instant` is the same statement reversed, and it is the
    one that would not have been caught by a rule assuming tools are harder.
    """
    plain = lane_chain()
    with_tools = lane_chain(tools=True)

    assert "groq/openai/gpt-oss-20b" in plain
    assert "groq/openai/gpt-oss-20b" not in with_tools

    assert "groq/llama-3.1-8b-instant" in with_tools
    assert "groq/llama-3.1-8b-instant" not in plain


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
    """A caller should not have to bootstrap the providers this build ships.

    Spelled out rather than derived from `_builtin_adapters()`, which would make
    it vacuous -- the point is that *these* are reachable without a caller doing
    anything.
    """
    assert agent_runtime.registered_providers() == {"openrouter", "groq"}


def test_every_shipped_provider_can_actually_be_constructed() -> None:
    """A credential entry with no adapter drops its slugs from this lane silently.

    That combination is *supported* -- the LiteLLM lane may reach a provider this
    one cannot, and `lane_chain` routes around it deliberately. But for a
    provider this build ships slugs for, it would be a chain quietly shorter
    than it reads, which is the failure mode this whole area keeps producing.
    """
    for provider in model_registry.PROVIDER_CREDENTIALS:
        assert provider in agent_runtime.registered_providers(), (
            f"{provider} is declared in PROVIDER_CREDENTIALS but has no lane adapter"
        )


def test_an_adapter_reuses_one_provider_object_across_calls() -> None:
    """Each provider owns an HTTP connection pool; one per request would leak."""
    adapter: ProviderAdapter = openai_compatible_adapter(
        name="openrouter", base_url="https://example.test/v1"
    )
    first = adapter.build_model("a")
    second = adapter.build_model("b")

    assert first.client is second.client  # type: ignore[attr-defined]  # concrete OpenAIChatModel, not the Model protocol


class TestTheFallbackObserver:
    """What the chain walked past, made visible and made cheaper.

    A successful run hides the failures underneath it: when the head slug is
    rate-limited and the next model answers, the step succeeds and
    `agent_step_completed` records only the model that served. Live, a chain
    serving every research step from its slow tail was indistinguishable in the
    console from a healthy one, and was reported as "the research steps are
    slow" with nothing to say why.
    """

    def test_it_reproduces_pydantic_ais_default_eligibility_rule(self) -> None:
        """This handler *replaces* the framework default, so it must restate it.

        PydanticAI's default is `fallback_on=(ModelAPIError,)`. Passing a
        handler overrides that wholesale -- a handler that returned True for
        everything would fall through on a programming error, and one that
        returned False for a provider outage would stop failing over at all.
        """
        observe = agent_runtime._observe_fallback("research-step-1")

        assert observe(ModelHTTPError(status_code=429, model_name="x", body=None)) is True
        assert observe(ValueError("a bug in this repo, not a provider fault")) is False

    def test_a_rate_limited_slug_leaves_the_chain_for_its_stated_window(self) -> None:
        """The whole point: the *next* step must not pay for the same refusal."""
        busy = model_registry.TOOL_MODEL_CHAIN[0]
        assert busy in model_registry.active_chain(model_registry.TOOL_MODEL_CHAIN)

        agent_runtime._observe_fallback("research-step-1")(
            ModelHTTPError(
                status_code=429,
                model_name=busy.split("/", 1)[1],
                body={"message": "Rate limit reached ... Please try again in 3m36s"},
            )
        )

        assert busy not in model_registry.active_chain(model_registry.TOOL_MODEL_CHAIN)

    def test_an_ordinary_failure_benches_nothing(self) -> None:
        """A 400 is the model refusing one request, not the model being busy.

        Two of the tool chain's Groq entries 400 intermittently and are in the
        chain anyway, precisely because the cost is one fast round trip. Benching
        them on that would remove the capacity this change exists to add.
        """
        before = model_registry.active_chain(model_registry.TOOL_MODEL_CHAIN)

        agent_runtime._observe_fallback("research-step-1")(
            ModelHTTPError(
                status_code=400,
                model_name=model_registry.TOOL_MODEL_CHAIN[0].split("/", 1)[1],
                body={"message": "Failed to call a function."},
            )
        )

        assert model_registry.active_chain(model_registry.TOOL_MODEL_CHAIN) == before

    def test_the_log_line_says_which_step_walked_past_which_model(self) -> None:
        busy = model_registry.TOOL_MODEL_CHAIN[0]

        with capture_logs() as logs:
            agent_runtime._observe_fallback("research-step-2")(
                ModelHTTPError(
                    status_code=429,
                    model_name=busy.split("/", 1)[1],
                    body={"message": "Rate limit reached ... Please try again in 30s"},
                )
            )

        entry = next(log for log in logs if log["event"] == "model_fallback")
        assert entry["label"] == "research-step-2"
        assert entry["model"] == busy
        assert entry["status"] == 429
        assert entry["reason"] == "rate_limited"
        assert entry["benched_seconds"] == 30.0
        assert entry["falls_through"] is True

    def test_the_provider_body_never_reaches_the_log(self) -> None:
        """A Groq 400 body embeds `failed_generation` -- the model's own output.

        On a research step that output is derived from the visitor's city and
        interests, and this project's rule is that planning telemetry carries
        neither. The body is read for the retry window and classified; it is
        never logged. Asserted over every value of every entry rather than the
        fields this handler happens to set, so a field added later without
        thought is caught.
        """
        secret = "Kyoto-with-teenagers-on-a-budget"

        with capture_logs() as logs:
            agent_runtime._observe_fallback("research-step-1")(
                ModelHTTPError(
                    status_code=400,
                    model_name=model_registry.TOOL_MODEL_CHAIN[0].split("/", 1)[1],
                    body={"failed_generation": f"web_search(query='{secret}')"},
                )
            )

        for entry in logs:
            for value in entry.values():
                assert secret not in str(value)
                assert "failed_generation" not in str(value)

    def test_an_unrecognised_model_name_is_logged_rather_than_guessed(self) -> None:
        """Failing to attribute must not mean failing to report."""
        with capture_logs() as logs:
            agent_runtime._observe_fallback("planner")(
                ModelHTTPError(status_code=503, model_name="acme/mystery", body=None)
            )

        entry = next(log for log in logs if log["event"] == "model_fallback")
        assert entry["benched_seconds"] is None
        assert entry["reason"] == "error"

    def test_the_observer_is_actually_installed_on_the_built_model(self) -> None:
        """Otherwise every assertion above tests a function nothing calls."""
        with patch.object(
            agent_runtime, "_observe_fallback", wraps=agent_runtime._observe_fallback
        ) as spy:
            agent_runtime.build_fallback_model(label="research-step-1")

        spy.assert_called_once_with("research-step-1")
