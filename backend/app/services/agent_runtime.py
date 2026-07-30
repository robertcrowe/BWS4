# Built with Spec4 AI - https://spec4.ai
"""The PydanticAI lane: shared substrate for any example app that coordinates
typed model calls through PydanticAI `Agent`s.

This is the framework-level counterpart of `services/generation.py`. That module
is the **LiteLLM lane** -- one `completion()` call with a `fallbacks` list. This
one is the **PydanticAI lane** -- a typed `Agent` over a `FallbackModel`, used
where an app wants the framework to bind and validate the model's output rather
than parsing JSON out of prose itself.

It lives in `services/` rather than inside the app that first needed it, for the
same reason `web_search.py` does: the chained-calls example app is the first
caller, not the owner. A later example that coordinates several agents should
call this rather than importing from a sibling example.

**Both lanes read one model list.** `services/model_registry.py` owns the
chains, the cooldown bench, and the provider→credential table; this module adds
only the part LiteLLM does not need, which is how to *construct* a PydanticAI
`Model` for a given provider. A slug benched here disappears from the LiteLLM
lane too, because `note_failure()` is shared.

## Adding a provider

Three edits, none of them in an example app:

1. `Settings` grows an optional `<name>_api_key` field.
2. `model_registry.PROVIDER_CREDENTIALS` grows one entry naming that field and
   the environment variable LiteLLM reads it from.
3. `register_provider(...)` below -- usually one line via
   `openai_compatible_adapter()`, since most providers expose an
   OpenAI-shaped `/chat/completions` endpoint.

Then add the provider's slugs to whichever chain in `model_registry` they
belong to, **and probe them for this lane** (see AGENT_LANE_KNOWN_BAD).

## Credentials work differently here, and that is not an inconsistency

The LiteLLM lane must never be passed `api_key=`: one key would be applied to
every fallback, including the ones belonging to the other provider, so
`model_registry.ensure_provider_credentials()` exports keys to the environment
instead. PydanticAI has no such problem -- a provider object, and therefore a
key, is attached to each individual model -- so this lane passes keys directly
and never touches `os.environ`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import structlog
from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.models import Model
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.providers.openrouter import OpenRouterProvider

from backend.app.services import model_registry

logger = structlog.get_logger()

#: Slugs excluded from **this lane only**, each verified by probe.
#:
#: Kept separate from `discover_models.TOOL_KNOWN_BAD` on the standing rule that
#: a probe result belongs to a capability, not to a model -- and this set is the
#: proof of it rather than a precaution. `groq/llama-3.1-8b-instant` ships in
#: both TOOL_MODEL_CHAIN and GENERATION_MODEL_CHAIN and works in each: it emits
#: well-formed `web_search` calls for the tool-use agent and returns clean
#: answer_v2 JSON for RAG. Asked for *typed output* here, it invents a tool that
#: was never offered to it and Groq 400s the request -- three probes returned
#: three different fabricated tool names (`brave_search`,
#: `brute_force_random_text`, ...). PydanticAI binds typed output through a
#: synthetic output tool, which is a third requirement neither existing probe
#: covers.
#:
#: Everything else in GENERATION_MODEL_CHAIN was probed for this lane with both
#: of the chained-calls app's output shapes and returned conforming objects.
AGENT_LANE_KNOWN_BAD = frozenset({"groq/llama-3.1-8b-instant"})


class AgentLaneError(Exception):
    """Raised when a typed agent step could not be completed.

    Carries the caller's label so a multi-step app can say *which* step failed:
    that distinction is usually the whole decision, since an early failure ends
    the run while a late one may leave usable output on the table.
    """

    def __init__(self, label: str, message: str) -> None:
        self.label = label
        super().__init__(message)


@dataclass(frozen=True)
class ProviderAdapter:
    """How to reach one provider through PydanticAI.

    Attributes:
        name: The routing prefix its chain slugs carry, matching a key in
            `model_registry.PROVIDER_CREDENTIALS`.
        build_model: Turns a **bare** model id (the slug with its routing prefix
            already stripped) into a PydanticAI model. Called per request, so it
            must be cheap; anything expensive belongs in a cached provider
            object the closure captures.
    """

    name: str
    build_model: Callable[[str], Model]


_ADAPTERS: dict[str, ProviderAdapter] = {}


def register_provider(adapter: ProviderAdapter) -> None:
    """Make a provider reachable from this lane.

    Args:
        adapter: The provider's adapter. Re-registering a name replaces it,
            which is what lets a test install a fake provider and restore the
            real one afterwards.
    """
    _ADAPTERS[adapter.name] = adapter


def registered_providers() -> frozenset[str]:
    """Return every provider this lane knows how to construct a model for."""
    return frozenset(_ADAPTERS)


def openai_compatible_adapter(*, name: str, base_url: str) -> ProviderAdapter:
    """Build an adapter for any provider exposing an OpenAI-shaped API.

    The common case by a wide margin: most inference providers serve a
    `/chat/completions` endpoint that differs from OpenAI's only in its base URL
    and credential. Reaching one that way needs no provider-specific SDK, and so
    no new dependency.

    Args:
        name: The routing prefix, matching `PROVIDER_CREDENTIALS`.
        base_url: The provider's OpenAI-compatible endpoint.

    Returns:
        An adapter that lazily builds one shared provider object -- and with it
        one HTTP connection pool -- for the life of the process.
    """
    cached: list[OpenAIProvider] = []

    def build(model_id: str) -> Model:
        if not cached:
            cached.append(
                OpenAIProvider(base_url=base_url, api_key=model_registry.provider_api_key(name))
            )
        return OpenAIChatModel(model_id, provider=cached[0])

    return ProviderAdapter(name=name, build_model=build)


def _openrouter_adapter() -> ProviderAdapter:
    """Build the OpenRouter adapter on PydanticAI's own provider class.

    Not `openai_compatible_adapter`, even though OpenRouter is OpenAI-shaped:
    PydanticAI ships `OpenRouterProvider`, which knows OpenRouter's own headers
    and error conventions, and using it costs nothing. The contrast is the point
    -- a provider with first-class support gets it, and everything else gets the
    generic factory.
    """
    cached: list[OpenRouterProvider] = []

    def build(model_id: str) -> Model:
        if not cached:
            cached.append(OpenRouterProvider(api_key=model_registry.provider_api_key("openrouter")))
        return OpenAIChatModel(model_id, provider=cached[0])

    return ProviderAdapter(name="openrouter", build_model=build)


#: Groq's OpenAI-compatible endpoint. Used in preference to PydanticAI's native
#: `GroqModel`, which requires the `groq` SDK as an extra dependency: this path
#: was probed to return conforming typed output from three of the four shipped
#: Groq slugs, so the dependency was declined. It also means the generic factory
#: is exercised by a provider this build actually ships rather than only by a
#: hypothetical future one.
GROQ_BASE_URL = "https://api.groq.com/openai/v1"


def _builtin_adapters() -> list[ProviderAdapter]:
    """Build the provider adapters this deployment ships.

    **The single definition of the built-in set.** Both module import and
    `reset_providers()` go through here, so removing a provider removes it from
    both — an earlier version listed them twice and the test hook silently
    restored what a real import no longer registered, which is a defect that
    hides itself from exactly the tests meant to catch it.

    Returns:
        A fresh adapter per provider. Fresh matters: each closes over its own
        cached provider object, so rebuilding drops the old HTTP pools.
    """
    return [
        _openrouter_adapter(),
        openai_compatible_adapter(name="groq", base_url=GROQ_BASE_URL),
    ]


for _adapter in _builtin_adapters():
    register_provider(_adapter)


@dataclass(frozen=True)
class StepResult[T: BaseModel]:
    """One completed typed model call.

    Attributes:
        output: The validated typed output.
        model: The model that actually served the call, read off the response.
            Never assumed: the lane walks a fallback chain, so naming the
            chain's head would attribute the output to a model that may never
            have run.
    """

    output: T
    model: str


def lane_chain(chain: list[str] | None = None) -> list[str]:
    """Resolve the slugs this lane may call, in preference order.

    Applies, in order: the registry's own filtering (unconfigured providers and
    the shared cooldown bench), this lane's probe exclusions, and finally
    whether a provider has been registered here at all.

    Args:
        chain: The capability's ordered chain. Defaults to
            GENERATION_MODEL_CHAIN, which is what every current caller wants;
            passed explicitly when a future capability earns its own list.

    Returns:
        Full registry slugs -- `provider/model-id`, prefix intact -- in the
        registry's order.

    Raises:
        AgentLaneError: If nothing survives. Failing loudly beats building a
            `FallbackModel` with no models, which surfaces later as an obscure
            framework error a long way from the cause.
    """
    source = model_registry.GENERATION_MODEL_CHAIN if chain is None else chain
    available = registered_providers()

    slugs = [
        model
        for model in model_registry.active_chain(source)
        if model not in AGENT_LANE_KNOWN_BAD and model_registry.provider_of(model) in available
    ]
    if not slugs:
        raise AgentLaneError(
            "lane",
            "No models are available to the PydanticAI lane: every entry is "
            "unconfigured, benched, excluded by probe, or from an unregistered provider.",
        )
    return slugs


def build_fallback_model(chain: list[str] | None = None) -> FallbackModel:
    """Build the lane's model: the head slug, with the rest behind it.

    Each entry is constructed by its own provider's adapter, so one
    `FallbackModel` can span providers -- which is the whole reason failover
    here is worth having. PydanticAI walks the list on failure using the real
    request as the signal, the same arrangement LiteLLM's `fallbacks` gives the
    other lane.

    Args:
        chain: The capability's ordered chain, or None for the default.

    Returns:
        A FallbackModel over every currently-available slug.
    """
    models = [
        _ADAPTERS[model_registry.provider_of(slug)].build_model(slug.split("/", 1)[1])
        for slug in lane_chain(chain)
    ]
    return FallbackModel(models[0], *models[1:])


async def run_typed_step[T: BaseModel](
    *,
    label: str,
    instructions: str,
    user_prompt: str,
    output_type: type[T],
    chain: list[str] | None = None,
) -> StepResult[T]:
    """Run one typed model call and return its output plus the serving model.

    The unit of work every caller of this lane is built from: one agent, one
    turn, one validated object. A multi-step app composes these; it does not
    reach past them into PydanticAI.

    Google-style docstring per project convention.

    Args:
        label: What this step is, for logs and for the error raised. Not sent to
            the model.
        instructions: The agent's system instructions.
        user_prompt: The call's user message.
        output_type: The Pydantic model the response is bound to.
        chain: The capability's ordered chain, or None for the default.

    Returns:
        The validated output and the slug that served it.

    Raises:
        AgentLaneError: If every model in the chain failed, or the surviving
            model could not produce output matching `output_type`. Both arrive
            as one exception because the caller's decision is the same either
            way -- there is no usable output for this step.
    """
    agent: Agent[None, T] = Agent(
        build_fallback_model(chain),
        output_type=output_type,
        instructions=instructions,
    )

    try:
        result = await agent.run(user_prompt)
    except Exception as exc:  # noqa: BLE001 - the framework raises several unrelated types
        # Teach the shared bench what this lane learned. A slug a provider has
        # withdrawn is withdrawn for the LiteLLM lane too, and note_failure
        # ignores anything that does not name a permanent failure.
        benched = model_registry.note_failure(exc)
        logger.warning(
            "agent_step_failed",
            label=label,
            error_type=type(exc).__name__,
            benched=benched,
        )
        raise AgentLaneError(label, f"The {label} call could not be completed.") from exc

    served = model_registry.normalize(result.response.model_name or "unknown")
    logger.info("agent_step_completed", label=label, model=served)
    return StepResult(output=result.output, model=served)


def reset_providers() -> None:
    """Restore the built-in provider adapters. Test hook.

    Process-local registration must not leak between tests, and a test that
    installs a fake provider needs a way back. Restores exactly what a fresh
    import would register, because both read `_builtin_adapters()`.
    """
    _ADAPTERS.clear()
    for adapter in _builtin_adapters():
        register_provider(adapter)
