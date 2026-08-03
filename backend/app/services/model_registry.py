# Built with Spec4 AI - https://spec4.ai
"""Framework-level model routing: ordered free-model chains, provider
credentials, and a cooldown set that skips slugs a provider has withdrawn.

This is a *shared framework service*, not an example app's helper. Every
example app that calls a language model routes through here, so that failover,
provider-key handling, and the withdrawn-model bench behave identically no
matter which app made the request -- the same reasoning that puts usage limits
and request logging in services/shared.py.

The chains are **per capability**, because the capability requirements differ
and each list is backed by its own probe evidence: TOOL_MODEL_CHAIN entries are
verified to emit well-formed tool calls and consume tool results,
GENERATION_MODEL_CHAIN entries are verified to return schema-valid structured
output. Everything around the chains -- cooldowns, credentials, name
normalization -- is shared, and a slug benched by one capability stays benched
for the other, since a withdrawn model is withdrawn for everyone.

Discovery and serving are deliberately split:

* **Serving** (this module, in the request path) never probes. It hands the
  whole ordered chain to LiteLLM's ``fallbacks``, which walks it on failure
  using the real request as the signal — no extra calls, no added latency.
* **Discovery** (``services/discover_models.py``, run offline) probes the live
  catalogue and prints a replacement for ``TOOL_MODEL_CHAIN`` below.

Probing in the request path was considered and rejected: OpenRouter's free
rate limit is per-account, so probing N candidates to serve one question both
multiplies the quota cost and triggers the very 429s it is trying to route
around — and a 429 is indistinguishable from incapability at probe time, so
the selection is non-deterministic. Two consecutive discovery runs disagreed
about which models were healthy while agreeing completely about which were
*capable*.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass

import structlog

from backend.app.core.config import get_settings
from backend.app.core.observability import report_model_health

logger = structlog.get_logger()


@dataclass(frozen=True)
class ProviderCredential:
    """Where one provider's API key lives, on both sides of the fence.

    Attributes:
        settings_attr: The `Settings` field holding the key. Settings has
            already resolved precedence (a real environment variable beats
            `.env`), so this is the authoritative reading.
        env_var: The environment variable LiteLLM expects to find it in.
            PydanticAI does not need this -- it takes the key directly on the
            provider object -- but LiteLLM resolves per-provider keys from the
            environment, so the value has to be published there for that lane.
    """

    settings_attr: str
    env_var: str


#: Every provider this deployment can route to, keyed by the routing prefix its
#: chain slugs carry. **This table is the one place a provider is declared.**
#: Adding one means one entry here, one optional field on `Settings`, and
#: (for the PydanticAI lane) one `register_provider()` call in
#: `services/agent_runtime.py` -- nothing else in the codebase names a provider.
#:
#: A slug whose prefix is absent from this table is treated as unconfigured and
#: silently dropped from every chain, which is the fail-closed direction: better
#: to route around a provider nobody supplied credentials for than to spend the
#: first attempt of every request on a 401.
PROVIDER_CREDENTIALS: dict[str, ProviderCredential] = {
    "openrouter": ProviderCredential(
        settings_attr="openrouter_api_key", env_var="OPENROUTER_API_KEY"
    ),
    "groq": ProviderCredential(settings_attr="groq_api_key", env_var="GROQ_API_KEY"),
}

#: Ordered chain of free-tier slugs that emit well-formed tool calls AND
#: correctly consume tool results, verified by services/discover_models.py.
#:
#: **Groq first, OpenRouter behind it.** Groq meters its free tier per model
#: (1,000 requests/day on gpt-oss-120b, 14,400 on llama-3.1-8b-instant),
#: whereas OpenRouter's is a single **account-wide** pool shared by every
#: example app here: 50 requests/day on an unfunded account, 1,000/day once
#: $10 of credits has been purchased, plus 20 requests/**minute** either way.
#: Groq therefore carries the traffic and OpenRouter is the deep fallback --
#: the reverse of what raw model quality alone would suggest. Note the margin
#: is much narrower on a funded account (1,000 per model vs 1,000 shared) than
#: on an unfunded one; the ordering still holds, but not overwhelmingly.
#:
#: The chain deliberately spans **two providers**, so an outage or a quota
#: wall at either one still leaves working entries. Like
#: GENERATION_MODEL_CHAIN below, this list **is expected to rot**.
#: When tool calling starts failing, re-run discovery rather than assuming a
#: code bug:
#:
#:     uv run python -m backend.app.services.discover_models
#:
#: Note that a Groq slug carries no `:free` marker -- the free tier is a
#: property of the account, not the model id.
#:
#: Deliberately excluded, all three verified by probe:
#:   * openrouter/openai/gpt-oss-20b:free -- returns its final answer in
#:     `reasoning` with empty `content`, so the loop can never terminate.
#:   * groq/openai/gpt-oss-20b -- HTTP 400s on tool_choice="none" ("Tool
#:     choice is none, but model called a tool"), which is the loop's
#:     termination path. agent.py can now fall back past this, but a model
#:     that needs the fallback on every forced answer doesn't belong in front.
#:   * groq/qwen/qwen3.6-27b -- returns empty content when asked to stop
#:     searching and answer.
TOOL_MODEL_CHAIN = [
    "groq/openai/gpt-oss-120b",
    "groq/llama-3.3-70b-versatile",
    "groq/llama-3.1-8b-instant",
    "openrouter/nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
    "openrouter/poolside/laguna-s-2.1:free",
    "openrouter/inclusionai/ling-3.0-flash:free",
]

#: Ordered chain of free-tier slugs for plain/structured text generation --
#: the capability behind the RAG example's answer synthesis, the single-call
#: example's plain mode, and shared.py's generate_text(). Separate from
#: TOOL_MODEL_CHAIN because the requirement is
#: different: these models are verified to return an answer_v2-shaped JSON
#: object that validates against rag.schemas.LlmAnswer, cite the passage that
#: actually supports the answer, and emit *no* citation markers when declining
#: -- the last of which rag/citations.py's audit depends on.
#:
#: Every entry was probed with this app's own answer_v2 prompt and passed both
#: the answerable and the unanswerable case. Like TOOL_MODEL_CHAIN this list
#: **is expected to rot**; re-probe when generation starts failing.
#:
#: The single-call example app's plain mode routes over this chain rather than
#: getting one of its own, and that is sound rather than a shortcut: returning
#: readable prose to a bare prompt is a *strictly weaker* requirement than the
#: probe these entries already passed, which additionally demanded
#: schema-valid JSON and correct citation discipline. A model that clears the
#: harder bar clears this one. Note that the reverse does not hold, so a chain
#: probed only for plain text could not be substituted here -- and if
#: single-call's structured mode later needs provider-native json_schema
#: decoding, that IS a separate requirement no probe here has established.
#:
#: Ordered **Groq first, OpenRouter behind it**, for the same quota reason as
#: TOOL_MODEL_CHAIN: Groq meters its free tier per model, while OpenRouter's is
#: one account-wide pool (50/day unfunded, 1,000/day once $10 of credits has
#: been purchased) that every example app here draws from. Vendors
#: alternate within each provider block so one vendor's withdrawal can't take
#: out the head of the chain.
#:
#: `groq/openai/gpt-oss-20b` is here despite sitting in
#: discover_models.TOOL_KNOWN_BAD. That is not an oversight: it is excluded
#: from the *tool* chain for 400ing on the loop's termination path, and it
#: returns clean, correctly-cited answer_v2 JSON. A probe result belongs to a
#: capability, not to a model -- don't propagate exclusions between chains.
#:
#: Probed and deliberately rejected:
#:   * groq/qwen/qwen3.6-27b -- emits trailing junk after its JSON object.
#:   * groq/allam-2-7b -- passes, but its 4,096-token context can't hold a
#:     real passage set, and it padded its refusal with advice to look
#:     elsewhere.
#:   * groq/groq/compound -- passes cleanly, and is excluded anyway: it is an
#:     agentic system with its own built-in web search, so it could answer
#:     from the live web while the UI reports the answer as grounded in the
#:     retrieved passages. A grounding claim nothing checked is the exact
#:     defect citations.py exists to prevent.
GENERATION_MODEL_CHAIN = [
    "groq/openai/gpt-oss-120b",
    "groq/llama-3.3-70b-versatile",
    "groq/openai/gpt-oss-20b",
    "groq/llama-3.1-8b-instant",
    "openrouter/nvidia/nemotron-3-super-120b-a12b:free",
    "openrouter/inclusionai/ling-3.0-flash:free",
    "openrouter/poolside/laguna-s-2.1:free",
    "openrouter/nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
]

#: Every slug this deployment might route to, across all capabilities. The
#: bench and the name normalizer work over this union rather than one chain:
#: a model a provider has withdrawn is withdrawn for every capability, and
#: LiteLLM echoes a served model name without saying which chain it came from.
_ALL_MODELS = list(dict.fromkeys(TOOL_MODEL_CHAIN + GENERATION_MODEL_CHAIN))

#: How long a slug stays benched after a *permanent* failure. Long enough to
#: stop hammering a withdrawn model for the life of a free-tier dyno, short
#: enough that a provider restoring the slug heals without a redeploy.
COOLDOWN_SECONDS = 30 * 60

#: Substrings that mark a model as gone rather than merely busy. Rate limits
#: and timeouts are explicitly NOT in this list: they are transient, and
#: benching a healthy model because it was briefly busy is how a fallback
#: chain eats itself. Rate limits get their own, much shorter bench below --
#: "busy until the provider says otherwise" is a third state, distinct from
#: both "healthy" and "withdrawn".
_PERMANENT_FAILURE_MARKERS = (
    "no endpoints found",
    "unavailable for free",
    "is not a valid model id",
    "model not found",
    "does not exist",
    # Observed on a Google slug while evaluating that provider: "This model
    # models/x is no longer available to new users." Kept even though Google is
    # not a shipped provider, because it matched none of the markers above --
    # all of which were written from OpenRouter's and Groq's phrasing -- and a
    # withdrawal that reads as a transient 404 is retried forever.
    "no longer available",
)

#: Bounds on how long a *rate-limited* slug sits out.
#:
#: The provider states its own retry window and that figure is honoured, but
#: never unbounded in either direction. The floor stops a sub-second hint from
#: being no bench at all; the ceiling stops one bad reading (or a provider
#: quoting the reset of a daily bucket) from taking a healthy model out of the
#: chain for the rest of a dyno's life. A window this bench under-estimates
#: costs one more failed attempt and re-benches; one it over-estimates costs
#: real capacity, so the ceiling is the tighter of the two on purpose.
MIN_RATE_LIMIT_BENCH_SECONDS = 5.0
MAX_RATE_LIMIT_BENCH_SECONDS = 10 * 60.0

#: Used when a response is plainly rate-limited but names no retry window.
DEFAULT_RATE_LIMIT_BENCH_SECONDS = 60.0

#: How long a slug sits out when the exhausted bucket is a **daily** one.
#:
#: Not a padding guess -- the provider's own figure is untrustworthy in exactly
#: this case, and this is the bucket that caused the reported slowdown. Groq
#: meters **tokens per day** as well as requests, and when that bucket drains it
#: answers "try again in 3m36s" -- a figure about its short window, not about
#: when the day's budget returns. The same shape was measured on a Google slug,
#: which reports `"retryDelay": "46s"` with its per-*day* request allowance
#: spent. Honouring either re-admits the slug in minutes to fail again, all day,
#: which is the churn the bench exists to stop. A daily bucket cannot
#: meaningfully refill in under half an hour, so a stated window is ignored when
#: the error names a daily metric.
DAILY_QUOTA_BENCH_SECONDS = 30 * 60.0

#: Substrings identifying a per-day allowance in a provider's quota metadata.
#: Google names the metric (`GenerateRequestsPerDayPerProjectPerModel`); Groq
#: spells it out in prose ("tokens per day (TPD)"); OpenRouter says
#: "free-models-per-day".
_DAILY_QUOTA_MARKERS = ("perday", "per day", "per-day", "tpd", "rpd")

#: Markers that identify a rate limit in an error whose status code is not to
#: hand -- LiteLLM surfaces one final string rather than a typed exception.
_RATE_LIMIT_MARKERS = ("rate limit", "rate_limit", "too many requests", "429")

#: Providers put the window in the message body rather than in a header, and
#: each words it differently -- Groq says "Please try again in 3m36s", Google
#: says "Please retry in 35.98s". Both spellings are matched rather than one
#: being treated as the format; the breadth costs a line and spared a provider
#: evaluation from silently falling back to the default window.
_RETRY_IN_RE = re.compile(
    r"(?:try again|retry) in\s+"
    r"(?:(\d+(?:\.\d+)?)h)?(?:(\d+(?:\.\d+)?)m)?(?:(\d+(?:\.\d+)?)s)?",
    re.IGNORECASE,
)

#: Some providers also repeat the window as structured `RetryInfo` in the error
#: body, which survives when the prose message does not.
_RETRY_DELAY_RE = re.compile(r'"?retrydelay"?\s*:\s*"?(\d+(?:\.\d+)?)s', re.IGNORECASE)

#: A plain `Retry-After` header value, in seconds.
_RETRY_AFTER_RE = re.compile(
    r"retry[-_ ]after[\"']?\s*[:=]?\s*[\"']?(\d+(?:\.\d+)?)", re.IGNORECASE
)

#: slug -> monotonic timestamp at which it becomes eligible again.
_benched: dict[str, float] = {}


def provider_of(model: str) -> str:
    """Return the routing provider a slug belongs to.

    Args:
        model: A chain slug, e.g. "groq/openai/gpt-oss-120b".

    Returns:
        The leading routing segment, e.g. "groq" or "openrouter".
    """
    return model.split("/", 1)[0]


def provider_api_key(provider: str) -> str | None:
    """Return one provider's API key, or None if it has none configured.

    Args:
        provider: A routing prefix, e.g. "groq".

    Returns:
        The key from Settings, or None when the provider is unknown to
        PROVIDER_CREDENTIALS or its Settings field is unset/empty.
    """
    credential = PROVIDER_CREDENTIALS.get(provider)
    if credential is None:
        return None
    return getattr(get_settings(), credential.settings_attr, None) or None


def configured_providers() -> frozenset[str]:
    """Return every provider this deployment actually holds a key for.

    Returns:
        The subset of PROVIDER_CREDENTIALS whose keys are present.
    """
    return frozenset(name for name in PROVIDER_CREDENTIALS if provider_api_key(name))


def ensure_provider_credentials() -> None:
    """Publish provider API keys into the environment for LiteLLM.

    The chain spans providers, and LiteLLM resolves a per-provider key from
    the environment. Passing a single `api_key=` on the call would apply the
    wrong credential to every fallback belonging to the other provider, so
    the keys are exported instead.

    Settings has already applied the correct precedence (real environment
    variables beat .env), so assigning from Settings is not a downgrade.

    The PydanticAI lane needs none of this: it attaches a provider object --
    and therefore a key -- to each individual model, so a mixed chain there
    carries the right credential per entry by construction.
    """
    for provider, credential in PROVIDER_CREDENTIALS.items():
        key = provider_api_key(provider)
        if key:
            os.environ[credential.env_var] = key


def configured_chain(chain: list[str]) -> list[str]:
    """Return a chain minus providers this deployment has no key for.

    Google-style docstring per project convention.

    Args:
        chain: The capability's ordered chain, e.g. TOOL_MODEL_CHAIN. Passed
            explicitly rather than defaulted, so no capability silently
            inherits another's model list.

    Returns:
        The ordered chain with every slug removed whose provider has no key --
        so an OpenRouter-only deployment keeps working rather than burning its
        first attempts on 401s. Driven by PROVIDER_CREDENTIALS rather than by a
        hardcoded check for one provider, so a third provider needs no edit
        here.
    """
    available = configured_providers()
    return [model for model in chain if provider_of(model) in available]


def active_chain(chain: list[str]) -> list[str]:
    """Return a usable model chain: configured providers, minus benched slugs.

    Google-style docstring per project convention.

    Args:
        chain: The capability's ordered chain, e.g. GENERATION_MODEL_CHAIN.

    Returns:
        The ordered chain, minus any slug whose provider isn't configured and
        any slug still inside its cooldown window. Never returns an empty
        list: if every configured slug is benched the configured chain is
        returned anyway, on the grounds that trying a benched model beats
        having nothing to try at all.
    """
    now = time.monotonic()
    configured = configured_chain(chain)
    available = [model for model in configured if _benched.get(model, 0.0) <= now]
    return available or configured


def _names_model(text: str, bare: str) -> bool:
    r"""Report whether `text` names exactly this model id, not a longer one.

    A plain containment test benches too much, because model ids are routinely
    prefixes of each other. The shipped slugs escape this only by coincidence --
    `openai/gpt-oss-20b` is not inside `openai/gpt-oss-120b`, because of the `1`
    -- which is not a property to keep relying on, and the wider the chains grow
    the more such pairs there are. A real example, from a provider catalogue
    surveyed while evaluating one: `gemini-2.5-flash` sits inside
    `gemini-2.5-flash-lite`, so a withdrawal notice naming *lite* would have
    benched both for half an hour.

    So the match is bounded by the characters that can *continue* a model id.
    Note the asymmetry in how a dot is treated, which a first version got wrong:
    ids carry dots as version separators (`llama-3.3-70b`), so a trailing dot
    must still terminate the match when it is sentence punctuation
    (`"model-1.0-flash. No endpoints found"`) while blocking it when a digit
    follows and the id therefore continues (`1.0` inside `1.05`). Hence
    `(?!\.\w)` rather than putting `.` in the character class.

    `normalize()` avoids the same trap by matching exactly, and
    `collab/opacity.value_appears()` exists for this class of bug on numbers.

    Args:
        text: The provider's error text, already lowercased.
        bare: The model id without its routing prefix, already lowercased.

    Returns:
        True if the id appears as a whole token.
    """
    return (
        re.search(rf"(?<![\w.-]){re.escape(bare)}(?![\w-])(?!\.\w)", text) is not None
    )


def note_failure(error: BaseException) -> list[str]:
    """Bench any chain slug the error names as permanently gone.

    LiteLLM walks the fallback chain internally and surfaces one final
    exception, so attribution is best-effort: this scans the error text for
    chain slugs mentioned alongside a permanent-failure marker.

    The scan covers every capability's chain, not just the caller's: a slug
    the provider has withdrawn is gone for whoever asks next.

    Args:
        error: The exception raised by the completion call.

    Returns:
        The slugs newly benched by this call, for logging/assertion.
    """
    text = str(error).lower()
    if not names_permanent_failure(text):
        return []

    newly_benched = []
    for model in _ALL_MODELS:
        # LiteLLM may report the slug with or without its routing prefix.
        bare = model.split("/", 1)[1]
        if _names_model(text, bare.lower()) and model not in newly_benched:
            _benched[model] = time.monotonic() + COOLDOWN_SECONDS
            newly_benched.append(model)

    if newly_benched:
        remaining_tool = len(active_chain(TOOL_MODEL_CHAIN))
        remaining_generation = len(active_chain(GENERATION_MODEL_CHAIN))
        logger.warning(
            "models_benched",
            models=newly_benched,
            cooldown_seconds=COOLDOWN_SECONDS,
            remaining_tool=remaining_tool,
            remaining_generation=remaining_generation,
        )
        # A withdrawn slug is chain rot, and rot never raises: the chain falls
        # through and answers correctly from further down, so nothing else
        # would ever tell an operator the lists have started to decay.
        report_model_health(
            "models_benched",
            models=",".join(newly_benched),
            remaining_tool=remaining_tool,
            remaining_generation=remaining_generation,
        )
    return newly_benched


def names_daily_quota(detail: str) -> bool:
    """Report whether the exhausted allowance is a per-day one.

    Matters because the two exhaust on completely different timescales while
    both arriving as a 429, and the provider's own retry hint does not
    distinguish them -- see `DAILY_QUOTA_BENCH_SECONDS`.

    Args:
        detail: The provider's error text.

    Returns:
        True if the text names a daily bucket.
    """
    lowered = detail.lower()
    return any(marker in lowered for marker in _DAILY_QUOTA_MARKERS)


def names_permanent_failure(detail: str) -> bool:
    """Report whether an error string describes a model that is gone for good.

    The opposite of `looks_rate_limited`: a withdrawn slug fails every time,
    where a rate-limited one is healthy and busy. Exposed so callers outside the
    bench -- the capability probes especially -- can tell a retired model from
    an intermittent one instead of recording it as a flake.

    Args:
        detail: The provider's error text.

    Returns:
        True if the text names a permanent failure.
    """
    lowered = detail.lower()
    return any(marker in lowered for marker in _PERMANENT_FAILURE_MARKERS)


def looks_rate_limited(detail: str) -> bool:
    """Report whether an error string describes a rate limit.

    For callers that have no status code to hand -- the LiteLLM lane surfaces
    one final string rather than a typed exception.

    Args:
        detail: The provider's error text.

    Returns:
        True if the text names a rate limit.
    """
    lowered = detail.lower()
    return any(marker in lowered for marker in _RATE_LIMIT_MARKERS)


def parse_retry_after(detail: str) -> float | None:
    """Extract the retry window a provider stated, in seconds.

    Providers say this two different ways and neither is a header this code
    ever sees: Groq writes "Please try again in 3m36s" into the message body,
    and a `Retry-After` value can appear in a stringified response. Both are
    parsed; anything else returns None so the caller can apply its default.

    Args:
        detail: The provider's error text.

    Returns:
        The stated window in seconds, or None if the text states none.
    """
    match = _RETRY_IN_RE.search(detail)
    if match and any(match.groups()):
        hours, minutes, seconds = (float(part or 0) for part in match.groups())
        return hours * 3600 + minutes * 60 + seconds

    for pattern in (_RETRY_DELAY_RE, _RETRY_AFTER_RE):
        match = pattern.search(detail)
        if match:
            return float(match.group(1))

    return None


def note_rate_limit(model: str, detail: str = "") -> float | None:
    """Bench one slug for as long as its provider asked to be left alone.

    A rate limit is the opposite of a permanent failure and must not be treated
    as one: the model is healthy and will serve again shortly, so `note_failure`
    deliberately ignores it. But *retrying it every time* is not free either --
    a saturated free-tier slug at the head of a chain costs every request a
    failed round trip before the real work starts, which is precisely how a
    fast chain comes to behave like a slow one.

    Benching for the stated window is the middle position: the slug leaves the
    chain for as long as the provider says it is unavailable, and returns by
    itself with no redeploy and no probe.

    Only ever *extends* an existing bench. A slug already benched as
    permanently gone must not have its 30-minute cooldown cut to 60 seconds by
    a later rate limit.

    Args:
        model: The chain slug, or any name `normalize` can map onto one.
        detail: The provider's error text, scanned for a stated retry window.

    Returns:
        The bench length applied in seconds, or None if the slug is unknown --
        an unrecognised name is not benched, since guessing which model a
        provider meant would take a healthy one out of the chain.
    """
    slug = normalize(model)
    if slug not in _ALL_MODELS:
        return None

    daily = names_daily_quota(detail)
    if daily:
        # The provider's stated window is about its *per-minute* bucket even
        # when the exhausted one is daily, so it is deliberately not consulted.
        window = DAILY_QUOTA_BENCH_SECONDS
        stated = None
    else:
        stated = parse_retry_after(detail)
        window = DEFAULT_RATE_LIMIT_BENCH_SECONDS if stated is None else stated
        window = min(
            max(window, MIN_RATE_LIMIT_BENCH_SECONDS), MAX_RATE_LIMIT_BENCH_SECONDS
        )

    until = time.monotonic() + window
    if _benched.get(slug, 0.0) < until:
        _benched[slug] = until

    logger.info(
        "model_rate_limited",
        model=slug,
        bench_seconds=round(window, 1),
        window_stated_by_provider=stated is not None,
        daily_quota=daily,
    )
    if daily:
        # Only the daily case is reported. A per-minute limit is ordinary
        # backpressure that clears itself in under a minute; a spent daily
        # allowance means this slug is gone until tomorrow, which changes what
        # the chain can serve for the rest of the day and is worth an operator
        # knowing before visitors find out by waiting.
        report_model_health("daily_quota_exhausted", model=slug)
    return window


def normalize(model: str) -> str:
    """Map a model name reported by LiteLLM back to its chain slug.

    LiteLLM echoes the served model on the response, usually without the
    routing prefix it was called with -- and the prefix can't be guessed,
    since "openai/gpt-oss-120b" is served by Groq here while OpenRouter has
    its own entries. So the name is matched against the known slugs rather
    than rewritten by string surgery. The match spans every capability's
    chain, since the response doesn't say which chain it came from.

    Args:
        model: A model name as reported on a completion response.

    Returns:
        The matching chain slug, or the input unchanged if nothing matches
        (an unknown model is worth surfacing verbatim, not disguising).
    """
    if model in _ALL_MODELS:
        return model
    for candidate in _ALL_MODELS:
        if candidate.split("/", 1)[1] == model or candidate.endswith(f"/{model}"):
            return candidate
    return model


def reset_cooldowns() -> None:
    """Clear the bench. Test hook — process-local state must not leak between tests."""
    _benched.clear()
