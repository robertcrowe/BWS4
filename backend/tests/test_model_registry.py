# Built with Spec4 AI - https://spec4.ai
"""Tests for the shared model chains and their permanent-failure cooldown.

The distinction these tests protect: a withdrawn slug should be benched, a
merely rate-limited one should not. Benching healthy models on transient 429s
is how a fallback chain eats itself.

The registry is framework-level, serving every example app, so the invariants
that apply to *any* chain (free tier only, vendor diversity, normalization)
are parametrized over all of them rather than asserted about the tool chain
alone.
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backend.app.services import model_registry
from backend.app.services.discover_models import TOOL_KNOWN_BAD, rank_cross_vendor


@pytest.fixture(autouse=True)
def _clear_cooldowns():
    model_registry.reset_cooldowns()
    yield
    model_registry.reset_cooldowns()


@pytest.fixture(autouse=True)
def _restore_groq_env():
    """ensure_provider_credentials writes to os.environ; don't leak it."""
    original = os.environ.get("GROQ_API_KEY")
    yield
    if original is None:
        os.environ.pop("GROQ_API_KEY", None)
    else:
        os.environ["GROQ_API_KEY"] = original


def _passing(model: str, note: str = "answered from tool results") -> dict:
    return {"model": model, "emits_call": True, "completes_loop": True, "note": note}


#: Local alias -- these tests reference the tool chain constantly.
TOOL = model_registry.TOOL_MODEL_CHAIN

#: Every capability chain the framework ships, for the invariants that hold
#: across all of them. Adding a chain to the registry adds it here too.
ALL_CHAINS = [
    ("tool", model_registry.TOOL_MODEL_CHAIN),
    ("generation", model_registry.GENERATION_MODEL_CHAIN),
]


def _vendor_of(slug: str) -> str:
    """The model's publisher, below the routing provider.

    `openrouter/nvidia/x:free` -> `nvidia`; `groq/llama-3.1-8b-instant` has no
    vendor segment, so the model name stands in for it.
    """
    parts = slug.split("/")
    return parts[1] if len(parts) > 2 else parts[-1]


@pytest.mark.parametrize(("name", "chain"), ALL_CHAINS)
def test_every_chain_spans_more_than_one_provider(name: str, chain: list[str]) -> None:
    """A whole-provider outage or quota wall must not empty a chain.

    Holds for every capability now that the generation chain has probed Groq
    entries. It briefly held only for the tool chain, which meant an
    OpenRouter outage took the RAG example dark while tool-use failed over.
    """
    providers = {model_registry.provider_of(slug) for slug in chain}
    assert len(providers) >= 2, f"{name} chain is single-provider: {providers}"


@pytest.mark.parametrize(("name", "chain"), ALL_CHAINS)
def test_every_chain_head_and_tail_are_different_providers(name: str, chain: list[str]) -> None:
    """The deep fallback has to be somewhere the head's outage can't reach."""
    assert model_registry.provider_of(chain[0]) != model_registry.provider_of(chain[-1]), (
        f"{name} chain starts and ends on the same provider"
    )


@pytest.mark.parametrize(("name", "chain"), ALL_CHAINS)
def test_no_chain_leads_with_two_models_from_one_vendor(name: str, chain: list[str]) -> None:
    """One vendor's withdrawal must not take out the head of a chain.

    Only the head is constrained: deeper duplicates are fine, since by then
    the request has already tried a different vendor.
    """
    assert _vendor_of(chain[0]) != _vendor_of(chain[1]), (
        f"{name} chain leads with two {_vendor_of(chain[0])} models"
    )


@pytest.mark.parametrize(("name", "chain"), ALL_CHAINS)
def test_every_chain_entry_is_a_known_free_tier_slug(name: str, chain: list[str]) -> None:
    """The binding project constraint: free tier only.

    OpenRouter marks free models in the slug; Groq's free tier is a property
    of the account, so a groq/ slug carries no marker and can only be checked
    by provider.
    """
    for slug in chain:
        provider = model_registry.provider_of(slug)
        assert provider in {"openrouter", "groq"}, f"unknown provider in {name} chain: {slug}"
        if provider == "openrouter":
            assert slug.endswith(":free"), f"non-free OpenRouter slug in {name} chain: {slug}"


@pytest.mark.parametrize(("name", "chain"), ALL_CHAINS)
def test_active_chain_returns_the_full_chain_when_nothing_is_benched(
    name: str, chain: list[str]
) -> None:
    assert model_registry.active_chain(chain) == chain


def test_a_withdrawn_model_is_benched_and_skipped() -> None:
    withdrawn = model_registry.TOOL_MODEL_CHAIN[0]
    bare = withdrawn.split("/", 1)[1]

    benched = model_registry.note_failure(
        RuntimeError(f"NotFoundError: {bare} - No endpoints found for this model")
    )

    assert benched == [withdrawn]
    assert withdrawn not in model_registry.active_chain(TOOL)
    assert len(model_registry.active_chain(TOOL)) == len(model_registry.TOOL_MODEL_CHAIN) - 1


def test_a_rate_limited_model_is_not_benched() -> None:
    """429 means busy, not gone."""
    busy = model_registry.TOOL_MODEL_CHAIN[0]
    bare = busy.split("/", 1)[1]

    benched = model_registry.note_failure(
        RuntimeError(f"RateLimitError: {bare} - Rate limit exceeded: free-models-per-day")
    )

    assert benched == []
    assert model_registry.active_chain(TOOL) == model_registry.TOOL_MODEL_CHAIN


def test_a_timeout_is_not_benched() -> None:
    slug = model_registry.TOOL_MODEL_CHAIN[1].split("/", 1)[1]
    assert model_registry.note_failure(RuntimeError(f"Timeout: {slug} aborted")) == []
    assert model_registry.active_chain(TOOL) == model_registry.TOOL_MODEL_CHAIN


def test_paid_only_withdrawal_is_recognised_as_permanent() -> None:
    """OpenRouter's actual wording when a model leaves the free tier."""
    withdrawn = model_registry.TOOL_MODEL_CHAIN[2]
    bare = withdrawn.split("/", 1)[1]

    model_registry.note_failure(
        RuntimeError(f"{bare}: This model is unavailable for free. The paid version is available")
    )

    assert withdrawn not in model_registry.active_chain(TOOL)


def test_active_chain_never_returns_empty_even_if_everything_is_benched() -> None:
    """A benched model is still a better bet than having nothing to call."""
    for slug in model_registry.TOOL_MODEL_CHAIN:
        model_registry.note_failure(
            RuntimeError(f"{slug.split('/', 1)[1]} - No endpoints found")
        )

    assert model_registry.active_chain(TOOL) == model_registry.TOOL_MODEL_CHAIN


def test_an_unrelated_error_benches_nothing() -> None:
    assert model_registry.note_failure(RuntimeError("connection reset by peer")) == []
    assert model_registry.active_chain(TOOL) == model_registry.TOOL_MODEL_CHAIN


@pytest.mark.parametrize(("name", "chain"), ALL_CHAINS)
def test_normalize_maps_a_reported_model_back_to_its_chain_slug(
    name: str, chain: list[str]
) -> None:
    """The routing prefix can't be guessed -- it has to be matched.

    "openai/gpt-oss-120b" is served by Groq in this chain, so prepending
    "openrouter/" (the old behaviour) would mislabel every Groq response.

    Every chain is covered because the response doesn't say which capability
    it was serving: a generation answer and a tool call come back through the
    same normalizer.
    """
    for slug in chain:
        bare = slug.split("/", 1)[1]
        assert model_registry.normalize(bare) == slug, f"{name} chain: {slug}"
        assert model_registry.normalize(slug) == slug, f"{name} chain: {slug}"


def test_normalize_leaves_an_unrecognised_model_alone() -> None:
    assert model_registry.normalize("someone/else:free") == "someone/else:free"


def test_discovery_interleaves_vendors_so_one_outage_cannot_empty_the_head() -> None:
    """Six NVIDIA models must not produce a chain that is NVIDIA all the way down."""
    ordered = rank_cross_vendor(
        [
            _passing("openrouter/nvidia/a:free"),
            _passing("openrouter/nvidia/b:free"),
            _passing("openrouter/nvidia/c:free"),
            _passing("openrouter/google/d:free"),
            _passing("openrouter/cohere/e:free"),
        ]
    )

    assert len(ordered) == 5
    head_vendors = [slug.removeprefix("openrouter/").split("/")[0] for slug in ordered[:3]]
    assert len(set(head_vendors)) == 3


def test_discovery_prefers_models_that_answered_over_ones_that_only_looped() -> None:
    ordered = rank_cross_vendor(
        [
            _passing("openrouter/nvidia/looped:free", note="issued a follow-up search"),
            _passing("openrouter/nvidia/answered:free", note="answered from tool results"),
        ]
    )

    assert ordered[0] == "openrouter/nvidia/answered:free"


def test_discovery_handles_a_single_vendor_without_dropping_entries() -> None:
    ordered = rank_cross_vendor(
        [_passing("openrouter/nvidia/a:free"), _passing("openrouter/nvidia/b:free")]
    )
    assert sorted(ordered) == ["openrouter/nvidia/a:free", "openrouter/nvidia/b:free"]


def test_discovery_puts_groq_ahead_of_openrouter() -> None:
    """Groq meters per model; OpenRouter free is one 50/day account-wide pool.

    Ordering by raw model quality alone would invert this, so the priority is
    pinned rather than left to chance.
    """
    ordered = rank_cross_vendor(
        [
            _passing("openrouter/nvidia/a:free"),
            _passing("groq/openai/gpt-oss-120b"),
            _passing("openrouter/google/b:free"),
            _passing("groq/llama-3.1-8b-instant"),
        ]
    )

    providers = [slug.split("/", 1)[0] for slug in ordered]
    assert providers == ["groq", "groq", "openrouter", "openrouter"]


def test_discovery_groups_groq_models_without_a_vendor_segment() -> None:
    """`groq/llama-3.1-8b-instant` has no vendor segment; it must not crash."""
    ordered = rank_cross_vendor(
        [
            _passing("groq/llama-3.1-8b-instant"),
            _passing("groq/llama-3.3-70b-versatile"),
            _passing("groq/openai/gpt-oss-120b"),
        ]
    )
    assert len(ordered) == 3
    assert set(ordered) == {
        "groq/llama-3.1-8b-instant",
        "groq/llama-3.3-70b-versatile",
        "groq/openai/gpt-oss-120b",
    }


def test_the_known_bad_models_are_not_in_the_shipped_chain() -> None:
    """Discovery excludes them; the chain must not have them either."""
    for slug in TOOL_KNOWN_BAD:
        assert slug not in model_registry.TOOL_MODEL_CHAIN


def _fake_settings(groq_key: str | None):
    """A stand-in for Settings; pydantic fields can't be patched as properties."""
    return SimpleNamespace(openrouter_api_key="test-openrouter-key", groq_api_key=groq_key)


def test_groq_slugs_are_dropped_when_no_groq_key_is_configured() -> None:
    """An OpenRouter-only deployment must not burn attempts on 401s."""
    with patch(
        "backend.app.services.model_registry.get_settings", return_value=_fake_settings(None)
    ):
        chain = model_registry.configured_chain(TOOL)

    assert chain, "dropping Groq must not empty the chain"
    assert all(model_registry.provider_of(slug) == "openrouter" for slug in chain)


def test_groq_slugs_are_kept_when_a_groq_key_is_configured() -> None:
    with patch(
        "backend.app.services.model_registry.get_settings",
        return_value=_fake_settings("test-groq-key"),
    ):
        chain = model_registry.configured_chain(TOOL)

    assert chain == model_registry.TOOL_MODEL_CHAIN


def test_active_chain_drops_groq_before_applying_cooldowns() -> None:
    """Without a key, a benched OpenRouter slug must not resurrect Groq ones."""
    with patch(
        "backend.app.services.model_registry.get_settings", return_value=_fake_settings(None)
    ):
        openrouter_slugs = model_registry.configured_chain(TOOL)
        for slug in openrouter_slugs:
            model_registry.note_failure(
                RuntimeError(f"{slug.split('/', 1)[1]} - No endpoints found")
            )
        chain = model_registry.active_chain(TOOL)

    assert all(model_registry.provider_of(slug) == "openrouter" for slug in chain)


def test_ensure_provider_credentials_exports_both_keys() -> None:
    with patch(
        "backend.app.services.model_registry.get_settings",
        return_value=_fake_settings("test-groq-key"),
    ):
        model_registry.ensure_provider_credentials()

    assert os.environ["OPENROUTER_API_KEY"] == "test-openrouter-key"
    assert os.environ["GROQ_API_KEY"] == "test-groq-key"


def test_ensure_provider_credentials_omits_groq_when_unset() -> None:
    os.environ.pop("GROQ_API_KEY", None)

    with patch(
        "backend.app.services.model_registry.get_settings", return_value=_fake_settings(None)
    ):
        model_registry.ensure_provider_credentials()

    assert "GROQ_API_KEY" not in os.environ
