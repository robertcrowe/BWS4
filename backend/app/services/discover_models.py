# Built with Spec4 AI - https://spec4.ai
"""Offline discovery: find free-tier models that genuinely support the agentic
tool-calling loop, and print a ranked replacement chain.

Covers both providers the chain spans: OpenRouter's `:free` slugs (filtered by
the catalogue's own `tools` flag) and Groq's chat models (filtered by name,
since Groq publishes no such flag). Groq is skipped when GROQ_API_KEY is unset.

Run this when tool calling starts failing, rather than assuming a code bug --
free catalogues churn and slugs are withdrawn regularly:

    uv run python -m backend.app.services.discover_models

This is NOT called from the request path. See services/model_registry.py for
why probing at request time was rejected.

The check has two stages, because advertising `tools` in the catalogue only
means the endpoint accepts a `tools` array -- it says nothing about whether
the model emits well-formed calls or can consume a result:

    stage 1: given a web_search schema, does it emit a valid call with a
             non-empty string query?
    stage 2: fed a tool result, does it either produce a grounded final
             answer or issue a legitimate follow-up call?

A model must pass both to enter the chain.
"""

from __future__ import annotations

import asyncio
import json
import sys

import httpx
import litellm

from backend.app.core.config import get_settings
from backend.app.services import model_registry

litellm.suppress_debug_info = True

CATALOGUE_URL = "https://openrouter.ai/api/v1/models"
GROQ_CATALOGUE_URL = "https://api.groq.com/openai/v1/models"
REQUEST_TIMEOUT_SECONDS = 45

#: Groq's catalogue exposes no tool-support flag and lists speech/guard models
#: alongside chat ones, so candidates are filtered by name rather than by a
#: field. Anything matching these is not a general chat model.
_GROQ_NON_CHAT_MARKERS = ("whisper", "orpheus", "prompt-guard", "safeguard", "compound")

#: Free-tier limits are per-account, so firing every probe at once triggers
#: the 429s the probe is trying to measure around. Stagger starts instead.
STAGGER_SECONDS = 4.0
RATE_LIMIT_BACKOFF_SECONDS = 25

#: Models to keep out of the chain regardless of how they probe, with the
#: reason, so a future run doesn't silently re-adopt a known-bad slug.
KNOWN_BAD = {
    "openrouter/openai/gpt-oss-20b:free": (
        "returns the final answer in `reasoning` with empty `content`, so the "
        "loop can never terminate"
    ),
    "groq/openai/gpt-oss-20b": (
        "HTTP 400s on tool_choice='none' ('Tool choice is none, but model "
        "called a tool'), which is the agent loop's termination path"
    ),
    "groq/qwen/qwen3.6-27b": (
        "returns empty content when asked to stop searching and answer"
    ),
    "groq/allam-2-7b": "'tool calling is not supported with this model'",
}

PROBE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the public web for current information. Use this whenever "
                "the user asks about recent events, news, or facts you are not "
                "certain about."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query to send to the search engine.",
                    }
                },
                "required": ["query"],
            },
        },
    }
]

PROBE_SYSTEM = (
    "You are a research assistant with access to a web search tool. "
    "When the user asks about recent or factual information, call the "
    "web_search tool with a well-formed query rather than answering from memory."
)
PROBE_QUESTION = "What have astronomers learned from the James Webb Space Telescope recently?"

#: A canned tool result whose distinctive tokens let stage 2 tell a genuinely
#: grounded answer apart from one recited from the model's own memory.
PROBE_TOOL_RESULT = json.dumps(
    {
        "results": [
            {
                "title": "JWST detects carbon dioxide in exoplanet atmosphere",
                "summary": "Webb's NIRSpec confirmed CO2 in the atmosphere of WASP-39b.",
                "url": "https://example.org/jwst-co2",
            },
            {
                "title": "Webb images earliest known galaxies",
                "summary": "JADES survey identified galaxies at redshift z>14.",
                "url": "https://example.org/jades",
            },
        ]
    }
)
_GROUNDING_TOKENS = ("wasp-39", "jades", "co2", "carbon dioxide", "redshift")


async def fetch_free_tool_models() -> list[str]:
    """List catalogue slugs that are free and claim tool support.

    Returns:
        Candidate slugs in canonical `openrouter/...` form.

    Raises:
        RuntimeError: If the catalogue can't be fetched or parsed.
    """
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            response = await client.get(CATALOGUE_URL)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise RuntimeError(f"Could not fetch the OpenRouter catalogue: {exc}") from exc

    return [
        f"openrouter/{model['id']}"
        for model in payload.get("data", [])
        if model.get("id", "").endswith(":free")
        and "tools" in (model.get("supported_parameters") or [])
    ]


async def fetch_groq_chat_models() -> list[str]:
    """List Groq chat models that are plausible tool-calling candidates.

    Unlike OpenRouter, Groq's catalogue carries no tool-support flag, so
    non-chat models are filtered out by name and the rest are settled by
    probe. Returns an empty list when no key is configured, so discovery
    still works as an OpenRouter-only run.

    Returns:
        Candidate slugs in canonical `groq/...` form.
    """
    api_key = get_settings().groq_api_key
    if not api_key:
        return []

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            response = await client.get(
                GROQ_CATALOGUE_URL, headers={"Authorization": f"Bearer {api_key}"}
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise RuntimeError(f"Could not fetch the Groq catalogue: {exc}") from exc

    return [
        f"groq/{model['id']}"
        for model in payload.get("data", [])
        if not any(marker in model.get("id", "").lower() for marker in _GROQ_NON_CHAT_MARKERS)
    ]


async def probe_model(model: str) -> dict:
    """Run the two-stage tool-calling check against one model.

    Credentials come from the environment (see
    model_registry.ensure_provider_credentials), since candidates may belong
    to different providers within a single run.

    Args:
        model: The slug to probe, in canonical `provider/...` form.

    Returns:
        A result dict with `model`, `emits_call`, `completes_loop`, `query`,
        and a human-readable `note`.
    """
    result = {
        "model": model,
        "emits_call": False,
        "completes_loop": False,
        "query": "",
        "note": "",
    }

    try:
        first = await litellm.acompletion(
            model=model,
            messages=[
                {"role": "system", "content": PROBE_SYSTEM},
                {"role": "user", "content": PROBE_QUESTION},
            ],
            tools=PROBE_TOOLS,
            tool_choice="auto",
            timeout=REQUEST_TIMEOUT_SECONDS,
            max_tokens=1024,
        )
    except Exception as exc:  # noqa: BLE001 - any provider/transport failure
        result["note"] = f"stage 1 error: {type(exc).__name__}: {str(exc)[:100]}"
        return result

    message = first.choices[0].message
    calls = getattr(message, "tool_calls", None)
    if not calls:
        result["note"] = "emitted no tool call (answered from memory)"
        return result
    call = calls[0]
    if call.function.name != "web_search":
        result["note"] = f"called an unknown tool: {call.function.name!r}"
        return result
    try:
        arguments = json.loads(call.function.arguments)
    except (ValueError, TypeError):
        result["note"] = f"unparseable arguments: {str(call.function.arguments)[:70]!r}"
        return result
    query = arguments.get("query")
    if not isinstance(query, str) or not query.strip():
        result["note"] = f"missing or blank query: {arguments}"
        return result

    result["emits_call"] = True
    result["query"] = query.strip()

    try:
        second = await litellm.acompletion(
            model=model,
            messages=[
                {"role": "system", "content": PROBE_SYSTEM},
                {"role": "user", "content": PROBE_QUESTION},
                message.model_dump(),
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "name": "web_search",
                    "content": PROBE_TOOL_RESULT,
                },
            ],
            tools=PROBE_TOOLS,
            timeout=REQUEST_TIMEOUT_SECONDS,
            max_tokens=1024,
        )
    except Exception as exc:  # noqa: BLE001
        result["note"] = f"stage 2 error: {type(exc).__name__}: {str(exc)[:100]}"
        return result

    final_message = second.choices[0].message
    final_text = final_message.content
    if final_text and final_text.strip():
        grounded = any(token in final_text.lower() for token in _GROUNDING_TOKENS)
        result["completes_loop"] = True
        result["note"] = (
            "answered from tool results" if grounded else "answered, but not visibly grounded"
        )
        return result

    # Empty content is not a failure if the model chose to search again --
    # that is the iterative loop working, not a broken one.
    follow_up = getattr(final_message, "tool_calls", None)
    if follow_up:
        result["completes_loop"] = True
        result["note"] = "issued a follow-up search (iterative loop)"
        return result

    result["note"] = "empty content and no follow-up call"
    return result


async def probe_with_backoff(model: str, delay: float) -> dict:
    """Probe one model, staggered, retrying once past a free-tier rate limit.

    Args:
        model: The slug to probe.
        delay: Seconds to wait before starting, to spread load.

    Returns:
        The probe result dict.
    """
    await asyncio.sleep(delay)
    result = await probe_model(model)
    if "RateLimitError" in result["note"] or "Timeout" in result["note"]:
        await asyncio.sleep(RATE_LIMIT_BACKOFF_SECONDS)
        result = await probe_model(model)
    return result


#: Providers in serving order. Groq leads because its free tier is metered
#: per model (1,000+ requests/day each) while OpenRouter's is a single
#: account-wide 50/day pool shared with the RAG app -- so OpenRouter is worth
#: far more as a fallback than as a primary.
_PROVIDER_PRIORITY = ["groq", "openrouter"]


def _vendor_of(model: str) -> str:
    """Return the model's originating vendor, ignoring the routing provider.

    Args:
        model: A slug like "groq/openai/gpt-oss-120b" or "groq/llama-3.1-8b".

    Returns:
        The vendor segment when the slug has one, otherwise the bare model
        name (which then simply acts as its own group).
    """
    parts = model.split("/")
    return parts[1] if len(parts) > 2 else parts[-1]


def _round_robin_vendors(entries: list[dict]) -> list[str]:
    """Interleave one provider's models so adjacent entries differ in vendor.

    Args:
        entries: Probe results belonging to a single provider.

    Returns:
        Slugs ordered by round-robin over vendors, best-first within a vendor.
    """
    by_vendor: dict[str, list[dict]] = {}
    for entry in entries:
        by_vendor.setdefault(_vendor_of(entry["model"]), []).append(entry)

    for group in by_vendor.values():
        # Prefer models that answered from the tool result over ones that
        # merely issued another call.
        group.sort(key=lambda e: "answered from tool results" not in e["note"])

    ordered: list[str] = []
    while by_vendor:
        for vendor in sorted(by_vendor):
            ordered.append(by_vendor[vendor].pop(0)["model"])
        by_vendor = {vendor: rest for vendor, rest in by_vendor.items() if rest}
    return ordered


def rank_cross_vendor(passing: list[dict]) -> list[str]:
    """Order passing models by provider priority, then interleaved by vendor.

    A chain whose entries all share a provider is one outage or quota wall
    away from being empty, which is exactly the failure this chain exists to
    survive.

    Args:
        passing: Probe results that passed both stages.

    Returns:
        Slugs ordered Groq-first, vendor-interleaved within each provider.
    """
    by_provider: dict[str, list[dict]] = {}
    for entry in passing:
        by_provider.setdefault(entry["model"].split("/", 1)[0], []).append(entry)

    def provider_rank(provider: str) -> tuple[int, str]:
        index = (
            _PROVIDER_PRIORITY.index(provider)
            if provider in _PROVIDER_PRIORITY
            else len(_PROVIDER_PRIORITY)
        )
        return (index, provider)

    ordered: list[str] = []
    for provider in sorted(by_provider, key=provider_rank):
        ordered.extend(_round_robin_vendors(by_provider[provider]))
    return ordered


async def main() -> int:
    """Probe every free tool-capable model and print a ranked chain.

    Returns:
        0 if at least one model passed, 1 otherwise.
    """
    model_registry.ensure_provider_credentials()

    discovered = await fetch_free_tool_models() + await fetch_groq_chat_models()
    excluded = [model for model in discovered if model in KNOWN_BAD]
    candidates = [model for model in discovered if model not in KNOWN_BAD]

    if not get_settings().groq_api_key:
        print("GROQ_API_KEY is unset -- probing OpenRouter only.\n")

    print(f"Probing {len(candidates)} candidate models "
          f"({len(excluded)} excluded as known-bad)...\n")

    results = await asyncio.gather(
        *(
            probe_with_backoff(model, index * STAGGER_SECONDS)
            for index, model in enumerate(candidates)
        )
    )

    print(f"{'model':<58} {'call':<6} {'loop':<6} note")
    print("-" * 132)
    for entry in sorted(
        results, key=lambda e: (not e["emits_call"], not e["completes_loop"], e["model"])
    ):
        print(
            f"{entry['model']:<58} "
            f"{'ok' if entry['emits_call'] else '--':<6} "
            f"{'ok' if entry['completes_loop'] else '--':<6} "
            f"{entry['note']}"
        )

    for model in excluded:
        print(f"{model:<58} {'skip':<6} {'skip':<6} excluded: {KNOWN_BAD[model]}")

    passing = [e for e in results if e["emits_call"] and e["completes_loop"]]
    if not passing:
        print(
            "\nNo model passed both stages. Every failure above may still be a "
            "transient rate limit -- re-run before concluding the free tier "
            "can no longer support tool calling."
        )
        return 1

    print(f"\n{len(passing)} of {len(candidates)} passed both stages.")
    print("\nPaste into model_registry.TOOL_MODEL_CHAIN (ordered cross-vendor):\n")
    print("TOOL_MODEL_CHAIN = [")
    for model in rank_cross_vendor(passing):
        print(f'    "{model}",')
    print("]")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
