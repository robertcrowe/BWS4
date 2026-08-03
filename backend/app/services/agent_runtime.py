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
3. `register_provider(...)` below -- often one line via
   `openai_compatible_adapter()`, since most providers expose an
   OpenAI-shaped `/chat/completions` endpoint.

Then add the provider's slugs to whichever chain in `model_registry` they
belong to, **and probe them for this lane** (see AGENT_LANE_KNOWN_BAD).

Step 3 is "often" rather than "always" one line: OpenRouter gets a bespoke
adapter because PydanticAI ships a provider class for it at no dependency cost,
while Groq uses the generic factory because its native model would need an SDK
extra this project does not install. The rule is not "prefer the generic
factory" but "take first-class support when it is free" -- see each adapter's
docstring.

## Credentials work differently here, and that is not an inconsistency

The LiteLLM lane must never be passed `api_key=`: one key would be applied to
every fallback, including the ones belonging to the other provider, so
`model_registry.ensure_provider_credentials()` exports keys to the environment
instead. PydanticAI has no such problem -- a provider object, and therefore a
key, is attached to each individual model -- so this lane passes keys directly
and never touches `os.environ`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

import structlog
from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelAPIError, UsageLimitExceeded
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.settings import ModelSettings
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.providers.openrouter import OpenRouterProvider
from pydantic_ai.usage import UsageLimits

from backend.app.services import chain_health, model_registry

logger = structlog.get_logger()

#: Slugs excluded from this lane's **tool-less** steps, each verified by probe.
#:
#: Applies to a step that asks only for typed output. The tools case has its own
#: set below and does *not* inherit this one -- see the note there.
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

#: Slugs excluded when this lane runs a step **with tools**. A *sibling* of
#: AGENT_LANE_KNOWN_BAD, not an extension of it: see the note below on why the
#: two sets are no longer nested.
#:
#: Every entry probed with a real research step (a search tool plus a typed
#: output type, which is what the planning app's executors need) against a
#: stubbed search, so no Exa quota was involved. Two cases per slug, because the
#: failure modes differ between them: results that are *useful*, and results
#: that come back *empty*.
#:
#: This is a *fourth* capability, and it needed its own probe for the reason the
#: other three did: none of the existing results transfer. Offering a function
#: tool and a typed-output tool *at the same time* is what these cannot do.
#:
#: **The line is drawn by failure mode, not by pass rate**, and that is the
#: substantive change from the first version of this list. `FallbackModel` is
#: configured to fall through on `ModelAPIError`, and the budget gate wraps it
#: from the *outside* -- so a model that answers a bad request with an HTTP
#: error costs the step one fast round trip and no quota unit at all. A model
#: that instead loops on the tool until `request_limit` trips raises
#: `StepRequestLimitExceeded`, which is terminal: nothing falls through, and the
#: step is lost. A model that returns an *empty but valid* object is worse
#: still, since the framework has no reason to reject it. Only the last two are
#: disqualifying:
#:
#: - `groq/openai/gpt-oss-20b` -- never stops calling the search tool, so the
#:   step's request limit ends it before it produces output (0 of 6 probes
#:   completed). Separately excluded from the LiteLLM tool chain for an
#:   unrelated fault, which is consistency rather than a transferred result.
#: - `openrouter/inclusionai/ling-3.0-flash:free` -- the same runaway, and it
#:   spends the whole limit doing it: 4 of 6 probes died on the request limit,
#:   and the two that answered still took all 5 requests and both searches.
#: - `openrouter/nvidia/nemotron-3-super-120b-a12b:free` -- calls the tool,
#:   reads the results, then returns an empty summary. 6 of 6, both cases.
#:
#: The survivors span both providers, so failover still crosses a provider
#: boundary. Expect this list to rot like every other; re-probe rather than
#: assuming a code fault when executors start failing.
TOOL_LANE_KNOWN_BAD = frozenset(
    {
        "groq/openai/gpt-oss-20b",
        "openrouter/inclusionai/ling-3.0-flash:free",
        "openrouter/nvidia/nemotron-3-super-120b-a12b:free",
    }
)

#: Re-probed after live runs showed research steps taking 33-67s against a
#: chain with exactly one fast entry. Two slugs moved, in opposite directions,
#: and between them they are why the two exclusion sets above are siblings
#: rather than base-and-extension:
#:
#: - `groq/llama-3.1-8b-instant` is excluded *without* tools and permitted
#:   *with* them. The recorded tool-less fault is that it invents a tool that
#:   was never offered; re-probing confirms it (2 of 3 tool-less probes still
#:   400). Offer it a real tool and there is nothing to invent -- 10 of 12
#:   probes passed, and it is the fastest entry in the chain. A set built on
#:   "tools is strictly harder" could not express that, and excluding a model
#:   from the harder case because it fails the easier one is backwards.
#: - `groq/llama-3.3-70b-versatile` fails 8 of 12, always with the recorded
#:   malformed tool call (`tool_use_failed`), and is permitted anyway. It fails
#:   in ~1s and falls through for free, so the expected cost of listing it is
#:   under a second; the expected saving, when it serves rather than the run
#:   dropping to OpenRouter's free pool, is 20-40s. It is in the chain as a
#:   cheap bet, not as a reliable entry -- do not read its membership as a
#:   4-of-12 model being called healthy.
#:
#: Their shared failure mode is what makes both safe: a hard 400 that
#: `FallbackModel` absorbs, never a silent empty answer.


class AgentLaneError(Exception):
    """Raised when a typed agent step could not be completed.

    Carries the caller's label so a multi-step app can say *which* step failed:
    that distinction is usually the whole decision, since an early failure ends
    the run while a late one may leave usable output on the table.
    """

    def __init__(self, label: str, message: str) -> None:
        self.label = label
        super().__init__(message)


class StepRequestLimitExceeded(AgentLaneError):
    """Raised when a step used up its `request_limit` without producing output.

    A subclass so callers that only care that the step failed need no change,
    and a distinct type because this failure is **deterministic**: the model
    kept calling tools and never settled. Retrying it runs the same model
    against the same prompt to reach the same limit, spending a second full
    step's budget to learn nothing -- which is exactly what a live run of the
    planning app did before this existed.
    """


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
        requests: How many model requests the step actually took. One for a
            plain typed call; more when tools are in play, because each
            tool-calling turn and the final answer are separate requests. A
            caller metering a shared budget must charge what was spent, not
            what a step "usually" costs.
    """

    output: T
    model: str
    requests: int = 1


class GatedModel(WrapperModel):
    """Runs an injected async hook immediately before every model request.

    The extension point that makes "checked before every model call" a
    structural property rather than an approximation. A tool-using agent issues
    several requests inside a single `agent.run()` -- one per tool-calling turn
    plus the final answer -- so a caller that checked a budget around the run
    would be checking once and spending several times.

    The hook is *injected* rather than imported, on the same reasoning as
    `tools/agent.py`'s `execute_search`: quota lives in a database and this
    module must stay free of one, so the caller supplies a closure and this lane
    stays testable without either.

    Note the deliberate limit: only `request` is gated, not `request_stream`.
    Nothing in this project streams from a model -- the SSE stream carries
    completed steps, not tokens -- so there is no ungated path today. Anything
    that starts streaming must gate that method too.
    """

    def __init__(self, wrapped: Model, on_request: Callable[[], Awaitable[None]]) -> None:
        super().__init__(wrapped)
        self._on_request = on_request

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        """Await the hook, then delegate.

        Args:
            messages: The conversation so far.
            model_settings: Per-request model settings.
            model_request_parameters: Tool and output-schema parameters.

        Returns:
            The wrapped model's response.

        Raises:
            Exception: Whatever the hook raises, before any provider is
                contacted. A hook that refuses is the whole point.
        """
        await self._on_request()
        return await super().request(messages, model_settings, model_request_parameters)


def lane_chain(chain: list[str] | None = None, *, tools: bool = False) -> list[str]:
    """Resolve the slugs this lane may call, in preference order.

    Applies, in order: the registry's own filtering (unconfigured providers and
    the shared cooldown bench), this lane's probe exclusions, and finally
    whether a provider has been registered here at all.

    Args:
        chain: The capability's ordered chain. Defaults to
            GENERATION_MODEL_CHAIN, which is what every current caller wants;
            passed explicitly when a future capability earns its own list.
        tools: Whether the step will offer the model function tools. Selects
            which exclusion set applies -- `TOOL_LANE_KNOWN_BAD` when true,
            `AGENT_LANE_KNOWN_BAD` when false. The two are **alternatives, not
            layers**: a model that returns clean typed output is not thereby
            able to do it *while* calling a tool, and -- measured, not assumed
            -- the reverse fails too, so neither set may be applied to the
            other's case.

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
    excluded = TOOL_LANE_KNOWN_BAD if tools else AGENT_LANE_KNOWN_BAD

    slugs = [
        model
        for model in model_registry.active_chain(source)
        if model not in excluded and model_registry.provider_of(model) in available
    ]
    if not slugs:
        raise AgentLaneError(
            "lane",
            "No models are available to the PydanticAI lane: every entry is "
            "unconfigured, benched, excluded by probe, or from an unregistered provider.",
        )
    return slugs


def _observe_fallback(label: str) -> Callable[[Exception], bool]:
    """Build the handler `FallbackModel` consults before walking to the next model.

    This exists because **a successful run hides the failures underneath it**.
    When the head slug is rate-limited and the next model answers, the step
    succeeds and `agent_step_completed` records only the model that served --
    so a chain quietly serving every request from its slow tail looks exactly
    like a healthy one, and diagnosing it needs a probe rather than a log. Live,
    that state persisted long enough to be reported as "research steps are slow"
    with nothing in the console to say why.

    Two things happen per skipped model, and neither changes the outcome of the
    request:

    * The step is logged, so the walk is visible.
    * A rate limit benches that slug for the window its provider stated, so the
      *next* step does not pay for the same refusal again.

    Returns the default eligibility rule unchanged: PydanticAI's own default is
    `(ModelAPIError,)`, and this handler replaces it, so it must reproduce it or
    it would silently change which errors fall through.

    Args:
        label: The calling step's label, so a log line says which step walked.

    Returns:
        A predicate deciding whether `exc` should fall through to the next model.
    """

    def observe(exc: Exception) -> bool:
        eligible = isinstance(exc, ModelAPIError)
        status = getattr(exc, "status_code", None)
        reported = getattr(exc, "model_name", None)
        slug = model_registry.normalize(reported) if reported else "unknown"

        # `str(exc)` carries the provider's body, which for a Groq 400 embeds
        # `failed_generation` -- the model's own attempted output, which on a
        # research step is derived from the visitor's city and interests. It is
        # read for the retry window and classified for the log; it is never
        # logged. Same rule the planning app's own telemetry follows.
        detail = str(exc)
        rate_limited = status == 429 or (status is None and model_registry.looks_rate_limited(detail))

        benched_for = model_registry.note_rate_limit(slug, detail) if rate_limited else None

        logger.warning(
            "model_fallback",
            label=label,
            model=slug,
            status=status,
            error_type=type(exc).__name__,
            reason="rate_limited" if rate_limited else "error",
            benched_seconds=None if benched_for is None else round(benched_for, 1),
            falls_through=eligible,
        )
        return eligible

    return observe


def build_fallback_model(
    chain: list[str] | None = None, *, tools: bool = False, label: str = "lane"
) -> FallbackModel:
    """Build the lane's model: the head slug, with the rest behind it.

    Each entry is constructed by its own provider's adapter, so one
    `FallbackModel` can span providers -- which is the whole reason failover
    here is worth having. PydanticAI walks the list on failure using the real
    request as the signal, the same arrangement LiteLLM's `fallbacks` gives the
    other lane.

    Args:
        chain: The capability's ordered chain, or None for the default.
        tools: Whether the step will offer function tools, which selects the
            exclusion set. See `lane_chain`.
        label: The calling step's label, carried into the fallback log.

    Returns:
        A FallbackModel over every currently-available slug, instrumented to
        log and bench whatever it walks past.
    """
    models = [
        _ADAPTERS[model_registry.provider_of(slug)].build_model(slug.split("/", 1)[1])
        for slug in lane_chain(chain, tools=tools)
    ]
    return FallbackModel(models[0], *models[1:], fallback_on=_observe_fallback(label))


async def run_typed_step[T: BaseModel](
    *,
    label: str,
    instructions: str,
    user_prompt: str,
    output_type: type[T],
    chain: list[str] | None = None,
    tools: Sequence[Callable[..., object]] | None = None,
    request_limit: int | None = None,
    on_request: Callable[[], Awaitable[None]] | None = None,
    model_settings: ModelSettings | None = None,
) -> StepResult[T]:
    """Run one typed model step and return its output plus the serving model.

    The unit of work every caller of this lane is built from. Without `tools`
    it is exactly one model call producing one validated object. With `tools`
    it is one *step* that may take several model calls -- the model calls a
    tool, reads the result, and either calls again or answers -- which is why
    `StepResult.requests` reports what it actually cost.

    Google-style docstring per project convention.

    Args:
        label: What this step is, for logs and for the error raised. Not sent to
            the model.
        instructions: The agent's system instructions.
        user_prompt: The call's user message.
        output_type: The Pydantic model the response is bound to.
        chain: The capability's ordered chain, or None for the default.
        tools: Functions to offer the model. Each becomes a tool whose schema
            PydanticAI derives from its signature and docstring, so the
            docstring is part of the interface, not a comment.
        request_limit: Hard ceiling on model requests for this step, enforced
            by PydanticAI itself. Pass it whenever tools are in play: a model
            that keeps calling tools would otherwise loop until something else
            stopped it.
        on_request: Awaited immediately before each model request. The place to
            put a budget counter or a quota reservation -- raising from it
            refuses the call before any provider is contacted.
        model_settings: Per-request settings such as temperature. Passed
            through rather than set here: sampling belongs to the capability
            making the call, and a lane-wide default would silently apply to
            every app.

    Returns:
        The validated output, the slug that served it, and the request count.

    Raises:
        AgentLaneError: If every model in the chain failed, or the surviving
            model could not produce output matching `output_type`. Both arrive
            as one exception because the caller's decision is the same either
            way -- there is no usable output for this step.
        Exception: Anything `on_request` raises propagates unchanged. A refusal
            is not a lane failure: it must not bench a model, and it must reach
            the caller as the specific error it is rather than as a generic
            "the step could not be completed".
    """
    # A step that offers tools needs a narrower chain than one that does not,
    # and the caller should not have to remember that: the presence of `tools`
    # is the signal, so it cannot be forgotten at a call site.
    model: Model = build_fallback_model(chain, tools=bool(tools), label=label)

    # Whatever the caller's hook raised, kept so the handler below can tell a
    # refusal from a model failure. Without this the gate's own exception would
    # be caught as a lane failure -- benching a healthy model for declining to
    # be called, and replacing the caller's specific error (cap reached, budget
    # spent) with a generic one. The two need different handling, so they must
    # stay distinguishable.
    refusal: list[BaseException] = []

    if on_request is not None:
        hook = on_request

        async def gate() -> None:
            try:
                await hook()
            except BaseException as exc:
                refusal.append(exc)
                raise

        model = GatedModel(model, gate)

    agent: Agent[None, T] = Agent(
        model,
        output_type=output_type,
        instructions=instructions,
        tools=list(tools) if tools else [],
    )
    limits = UsageLimits(request_limit=request_limit) if request_limit else None

    try:
        result = await agent.run(
            user_prompt, usage_limits=limits, model_settings=model_settings
        )
    except UsageLimitExceeded as exc:
        # The model never stopped calling tools. Distinct from a model failure:
        # it is deterministic, so the caller must not retry it, and it says
        # nothing about the model's health, so nothing gets benched.
        logger.warning("agent_step_hit_request_limit", label=label, limit=request_limit)
        raise StepRequestLimitExceeded(
            label, f"The {label} step used its {request_limit}-request limit without answering."
        ) from exc
    except Exception as exc:  # noqa: BLE001 - the framework raises several unrelated types
        if refusal:
            # The provider was never reached. Re-raise the hook's own exception
            # rather than `exc`, which may be a wrapper the framework put
            # around it.
            raise refusal[0] from None
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
    chain_health.note_served(served)
    requests = result.usage.requests
    logger.info("agent_step_completed", label=label, model=served, requests=requests)
    return StepResult(output=result.output, model=served, requests=requests)


def reset_providers() -> None:
    """Restore the built-in provider adapters. Test hook.

    Process-local registration must not leak between tests, and a test that
    installs a fake provider needs a way back. Restores exactly what a fresh
    import would register, because both read `_builtin_adapters()`.
    """
    _ADAPTERS.clear()
    for adapter in _builtin_adapters():
        register_provider(adapter)
