# Built with Spec4 AI - https://spec4.ai
"""Ordered free-model chain for tool-calling generation, plus a cooldown set
that skips slugs OpenRouter has permanently withdrawn.

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
import time

import structlog

from backend.app.core.config import get_settings

logger = structlog.get_logger()

#: Ordered chain of free-tier slugs that emit well-formed tool calls AND
#: correctly consume tool results, verified by services/discover_models.py.
#:
#: **Groq first, OpenRouter behind it.** Groq meters its free tier per model
#: (1,000 requests/day on gpt-oss-120b, 14,400 on llama-3.1-8b-instant),
#: whereas OpenRouter's free tier is a single account-wide 50/day pool shared
#: with the RAG app. Groq therefore carries the traffic and OpenRouter is the
#: deep fallback -- the reverse of what raw model quality alone would suggest.
#:
#: The chain deliberately spans **two providers**, so an outage or a quota
#: wall at either one still leaves working entries. Like
#: generation.PRIMARY_MODEL/FALLBACK_MODEL, this list **is expected to rot**.
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

#: How long a slug stays benched after a *permanent* failure. Long enough to
#: stop hammering a withdrawn model for the life of a free-tier dyno, short
#: enough that a provider restoring the slug heals without a redeploy.
COOLDOWN_SECONDS = 30 * 60

#: Substrings that mark a model as gone rather than merely busy. Rate limits
#: and timeouts are explicitly NOT in this list: they are transient, and
#: benching a healthy model because it was briefly busy is how a fallback
#: chain eats itself.
_PERMANENT_FAILURE_MARKERS = (
    "no endpoints found",
    "unavailable for free",
    "is not a valid model id",
    "model not found",
    "does not exist",
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


def ensure_provider_credentials() -> None:
    """Publish provider API keys into the environment for LiteLLM.

    The chain spans providers, and LiteLLM resolves a per-provider key from
    the environment. Passing a single `api_key=` on the call would apply the
    wrong credential to every fallback belonging to the other provider, so
    the keys are exported instead.

    Settings has already applied the correct precedence (real environment
    variables beat .env), so assigning from Settings is not a downgrade.
    """
    settings = get_settings()
    os.environ["OPENROUTER_API_KEY"] = settings.openrouter_api_key
    if settings.groq_api_key:
        os.environ["GROQ_API_KEY"] = settings.groq_api_key


def configured_chain() -> list[str]:
    """Return the chain minus providers this deployment has no key for.

    Google-style docstring per project convention.

    Returns:
        The ordered chain with `groq/` slugs removed when GROQ_API_KEY is
        unset, so an OpenRouter-only deployment keeps working rather than
        burning its first attempts on 401s.
    """
    if get_settings().groq_api_key:
        return list(TOOL_MODEL_CHAIN)
    return [model for model in TOOL_MODEL_CHAIN if provider_of(model) != "groq"]


def active_chain() -> list[str]:
    """Return the usable model chain: configured providers, minus benched slugs.

    Google-style docstring per project convention.

    Returns:
        The ordered chain, minus any slug whose provider isn't configured and
        any slug still inside its cooldown window. Never returns an empty
        list: if every configured slug is benched the configured chain is
        returned anyway, on the grounds that trying a benched model beats
        having nothing to try at all.
    """
    now = time.monotonic()
    configured = configured_chain()
    available = [model for model in configured if _benched.get(model, 0.0) <= now]
    return available or configured


def note_failure(error: BaseException) -> list[str]:
    """Bench any chain slug the error names as permanently gone.

    LiteLLM walks the fallback chain internally and surfaces one final
    exception, so attribution is best-effort: this scans the error text for
    chain slugs mentioned alongside a permanent-failure marker.

    Args:
        error: The exception raised by the completion call.

    Returns:
        The slugs newly benched by this call, for logging/assertion.
    """
    text = str(error).lower()
    if not any(marker in text for marker in _PERMANENT_FAILURE_MARKERS):
        return []

    newly_benched = []
    for model in TOOL_MODEL_CHAIN:
        # LiteLLM may report the slug with or without its routing prefix.
        bare = model.split("/", 1)[1]
        if bare.lower() in text and model not in newly_benched:
            _benched[model] = time.monotonic() + COOLDOWN_SECONDS
            newly_benched.append(model)

    if newly_benched:
        logger.warning(
            "tool_models_benched",
            models=newly_benched,
            cooldown_seconds=COOLDOWN_SECONDS,
            remaining=len(active_chain()),
        )
    return newly_benched


def normalize(model: str) -> str:
    """Map a model name reported by LiteLLM back to its chain slug.

    LiteLLM echoes the served model on the response, usually without the
    routing prefix it was called with -- and the prefix can't be guessed,
    since "openai/gpt-oss-120b" is served by Groq here while OpenRouter has
    its own entries. So the name is matched against the chain rather than
    rewritten by string surgery.

    Args:
        model: A model name as reported on a completion response.

    Returns:
        The matching chain slug, or the input unchanged if nothing matches
        (an unknown model is worth surfacing verbatim, not disguising).
    """
    if model in TOOL_MODEL_CHAIN:
        return model
    for candidate in TOOL_MODEL_CHAIN:
        if candidate.split("/", 1)[1] == model or candidate.endswith(f"/{model}"):
            return candidate
    return model


def reset_cooldowns() -> None:
    """Clear the bench. Test hook — process-local state must not leak between tests."""
    _benched.clear()
