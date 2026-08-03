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
import time
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

    Note the blind spot, in case a single-vendor provider is ever added: for a
    provider that publishes only its own models, two of its slugs would read as
    two vendors and the head-of-chain rule below would not see the relation.
    Neither shipped provider is like that -- Groq serves OpenAI, Meta and Qwen
    models -- so no special case is carried for a situation that does not exist.
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
def test_every_chain_head_and_tail_are_different_providers(
    name: str, chain: list[str]
) -> None:
    """The deep fallback has to be somewhere the head's outage can't reach."""
    assert model_registry.provider_of(chain[0]) != model_registry.provider_of(
        chain[-1]
    ), f"{name} chain starts and ends on the same provider"


@pytest.mark.parametrize(("name", "chain"), ALL_CHAINS)
def test_no_chain_leads_with_two_models_from_one_vendor(
    name: str, chain: list[str]
) -> None:
    """One vendor's withdrawal must not take out the head of a chain.

    Only the head is constrained: deeper duplicates are fine, since by then
    the request has already tried a different vendor.
    """
    assert _vendor_of(chain[0]) != _vendor_of(chain[1]), (
        f"{name} chain leads with two {_vendor_of(chain[0])} models"
    )


@pytest.mark.parametrize(("name", "chain"), ALL_CHAINS)
def test_every_chain_entry_is_a_known_free_tier_slug(
    name: str, chain: list[str]
) -> None:
    """The binding project constraint: free tier only.

    OpenRouter marks free models in the slug; Groq's free tier is a property
    of the account, so a groq/ slug carries no marker and can only be checked
    by provider.
    """
    for slug in chain:
        provider = model_registry.provider_of(slug)
        assert provider in {"openrouter", "groq"}, (
            f"unknown provider in {name} chain: {slug}"
        )
        if provider == "openrouter":
            assert slug.endswith(":free"), (
                f"non-free OpenRouter slug in {name} chain: {slug}"
            )


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
    assert (
        len(model_registry.active_chain(TOOL))
        == len(model_registry.TOOL_MODEL_CHAIN) - 1
    )


def test_a_rate_limited_model_is_not_benched_as_withdrawn() -> None:
    """429 means busy, not gone -- so it must not take the 30-minute cooldown.

    `note_rate_limit` applies a much shorter one; this pins that the *permanent*
    path stays out of it, since a transient 429 promoted to a withdrawal is how
    a fallback chain eats itself.
    """
    busy = model_registry.TOOL_MODEL_CHAIN[0]
    bare = busy.split("/", 1)[1]

    benched = model_registry.note_failure(
        RuntimeError(
            f"RateLimitError: {bare} - Rate limit exceeded: free-models-per-day"
        )
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
        RuntimeError(
            f"{bare}: This model is unavailable for free. The paid version is available"
        )
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
    head_vendors = [
        slug.removeprefix("openrouter/").split("/")[0] for slug in ordered[:3]
    ]
    assert len(set(head_vendors)) == 3


def test_discovery_prefers_models_that_answered_over_ones_that_only_looped() -> None:
    ordered = rank_cross_vendor(
        [
            _passing("openrouter/nvidia/looped:free", note="issued a follow-up search"),
            _passing(
                "openrouter/nvidia/answered:free", note="answered from tool results"
            ),
        ]
    )

    assert ordered[0] == "openrouter/nvidia/answered:free"


def test_discovery_handles_a_single_vendor_without_dropping_entries() -> None:
    ordered = rank_cross_vendor(
        [_passing("openrouter/nvidia/a:free"), _passing("openrouter/nvidia/b:free")]
    )
    assert sorted(ordered) == ["openrouter/nvidia/a:free", "openrouter/nvidia/b:free"]


def test_discovery_puts_groq_ahead_of_openrouter() -> None:
    """Groq meters per model; OpenRouter free is one account-wide pool.

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
    return SimpleNamespace(
        openrouter_api_key="test-openrouter-key", groq_api_key=groq_key
    )


def test_groq_slugs_are_dropped_when_no_groq_key_is_configured() -> None:
    """An OpenRouter-only deployment must not burn attempts on 401s."""
    with patch(
        "backend.app.services.model_registry.get_settings",
        return_value=_fake_settings(None),
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
        "backend.app.services.model_registry.get_settings",
        return_value=_fake_settings(None),
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
        "backend.app.services.model_registry.get_settings",
        return_value=_fake_settings(None),
    ):
        model_registry.ensure_provider_credentials()

    assert "GROQ_API_KEY" not in os.environ


class TestTheRateLimitBench:
    """A third state between healthy and withdrawn: busy until a stated time.

    Reported live as "the planning agent's research steps are slow". The head
    of every chain had exhausted Groq's per-day *token* budget, so each step
    paid a failed round trip to it before falling through to OpenRouter's much
    slower free pool -- every step, for hours, because a 429 is transient and
    `note_failure` correctly refuses to bench one.
    """

    @pytest.mark.parametrize(
        ("detail", "expected"),
        [
            # Groq states the window inside the message body, not as a header.
            ("Please try again in 3m36s", 216.0),
            ("Please try again in 7.66s", 7.66),
            ("try again in 1h2m3s", 3723.0),
            ("Retry-After: 30", 30.0),
            ("retry_after = 12.5", 12.5),
            ("Rate limit reached. Slow down.", None),
            ("", None),
        ],
    )
    def test_it_reads_the_window_the_provider_stated(
        self, detail: str, expected: float | None
    ) -> None:
        assert model_registry.parse_retry_after(detail) == expected

    def test_a_stated_window_takes_the_slug_out_for_exactly_that_long(self) -> None:
        busy = model_registry.TOOL_MODEL_CHAIN[0]

        applied = model_registry.note_rate_limit(busy, "Please try again in 3m36s")

        assert applied == 216.0
        assert busy not in model_registry.active_chain(TOOL)

    def test_it_accepts_the_bare_name_a_provider_reports(self) -> None:
        """Providers echo the model without the routing prefix this code calls it by.

        `openai/gpt-oss-120b` is served by *Groq* here, so the prefix cannot be
        guessed -- `normalize` maps it back. Benching under the unprefixed name
        would silently bench nothing.
        """
        busy = model_registry.TOOL_MODEL_CHAIN[0]

        assert model_registry.note_rate_limit(busy.split("/", 1)[1], "try again in 60s")
        assert busy not in model_registry.active_chain(TOOL)

    def test_a_window_less_slug_gets_the_default(self) -> None:
        busy = model_registry.TOOL_MODEL_CHAIN[0]

        applied = model_registry.note_rate_limit(busy, "429 Too Many Requests")

        assert applied == model_registry.DEFAULT_RATE_LIMIT_BENCH_SECONDS

    def test_the_window_is_clamped_at_both_ends(self) -> None:
        """A bench this over-estimates costs real capacity, so it is bounded."""
        first, second = model_registry.TOOL_MODEL_CHAIN[:2]

        assert (
            model_registry.note_rate_limit(first, "try again in 0.2s")
            == model_registry.MIN_RATE_LIMIT_BENCH_SECONDS
        )
        assert (
            model_registry.note_rate_limit(second, "try again in 24h")
            == model_registry.MAX_RATE_LIMIT_BENCH_SECONDS
        )

    def test_an_unknown_slug_is_never_benched(self) -> None:
        """Guessing which model a provider meant would remove a healthy one."""
        before = model_registry.active_chain(TOOL)

        assert (
            model_registry.note_rate_limit("acme/not-a-real-model", "try again in 60s")
            is None
        )
        assert model_registry.active_chain(TOOL) == before

    def test_it_never_shortens_an_existing_bench(self) -> None:
        """A withdrawn model must not be restored to the chain by a later 429.

        The two benches share one dict, so a 60-second rate-limit window written
        over a 30-minute withdrawal would put a model a provider has removed
        back in front of visitors a minute later.
        """
        withdrawn = model_registry.TOOL_MODEL_CHAIN[0]
        bare = withdrawn.split("/", 1)[1]
        model_registry.note_failure(RuntimeError(f"{bare}: No endpoints found"))

        model_registry.note_rate_limit(withdrawn, "try again in 6s")

        assert withdrawn not in model_registry.active_chain(TOOL)
        assert model_registry._benched[withdrawn] > time.monotonic() + 60

    def test_looks_rate_limited_recognises_what_providers_actually_say(self) -> None:
        """For the LiteLLM lane, which surfaces a string and no status code."""
        assert model_registry.looks_rate_limited("Error code: 429 - too many requests")
        assert model_registry.looks_rate_limited("RateLimitError: rate limit exceeded")
        assert not model_registry.looks_rate_limited(
            "No endpoints found for this model"
        )


class TestModelIdsThatArePrefixesOfEachOther:
    """Benching must name one model, not every model whose id starts the same.

    Model ids are routinely prefixes of one another, so a containment test
    benches a healthy model for half an hour every time its longer sibling is
    withdrawn. The shipped slugs escape this only by coincidence, which is why
    the pair here is synthetic: the guarantee must not depend on whichever chain
    happens to be shipped today. A real instance, found in a provider catalogue
    surveyed during an evaluation: `gemini-2.5-flash` inside
    `gemini-2.5-flash-lite`.
    """

    #: Synthetic, but under a *configured* provider -- `active_chain` filters
    #: out slugs whose provider has no key, so an invented prefix would leave
    #: every assertion below comparing empty lists and passing vacuously.
    PAIR = ["openrouter/acme/model-1.0-flash", "openrouter/acme/model-1.0-flash-lite"]

    @pytest.fixture(autouse=True)
    def _synthetic_chain(self):
        with patch.object(model_registry, "_ALL_MODELS", list(self.PAIR)):
            yield

    def test_withdrawing_the_longer_id_leaves_the_shorter_one_alone(self) -> None:
        short, long = self.PAIR

        benched = model_registry.note_failure(
            RuntimeError(f"NotFoundError: {long.split('/', 1)[1]} - No endpoints found")
        )

        assert benched == [long]
        assert short in model_registry.active_chain(list(self.PAIR))

    def test_withdrawing_the_shorter_id_still_benches_it(self) -> None:
        """The fix must not overshoot into matching nothing."""
        short, long = self.PAIR

        benched = model_registry.note_failure(
            RuntimeError(f"{short.split('/', 1)[1]}: No endpoints found")
        )

        assert benched == [short]
        assert long in model_registry.active_chain(list(self.PAIR))

    @pytest.mark.parametrize(
        "template",
        [
            "{bare}: No endpoints found",
            "model not found: '{bare}'",
            "NotFoundError: the model {bare} does not exist",
            "`{bare}` is not a valid model id",
            "{bare}. No endpoints found",
        ],
    )
    def test_the_id_is_still_found_however_the_provider_punctuates_it(
        self, template: str
    ) -> None:
        """Bounding the match must not stop it matching real provider wording."""
        short = self.PAIR[0]

        benched = model_registry.note_failure(
            RuntimeError(template.format(bare=short.split("/", 1)[1]))
        )

        assert benched == [short]


def test_a_retirement_worded_the_google_way_is_recognised_as_permanent() -> None:
    """Observed while evaluating Google as a provider, and kept afterwards.

    Its wording matched none of the older markers, which were written from
    OpenRouter's and Groq's phrasing. A withdrawal that reads as a transient 404
    is retried on every request, forever -- so the marker earns its place even
    though that provider is not shipped.
    """
    message = (
        "This model models/gemini-2.5-flash-lite is no longer available to new "
        "users. Please update your code to use a newer model."
    )

    assert model_registry.names_permanent_failure(message)
    assert not model_registry.looks_rate_limited(message)


class TestADailyAllowanceIsBenchedForLongerThanTheProviderSays:
    """The one case where the provider's own retry window must be ignored.

    Measured on Gemini: with the per-*day* allowance spent, it still answers
    `"retryDelay": "46s"` -- the per-minute window, which says nothing about
    when the day's budget returns. Honouring it re-admits the slug 46 seconds
    later to fail again, all day, which is exactly the churn the bench exists to
    stop. Groq's TPD exhaustion has the same shape.
    """

    GEMINI_DAILY = (
        "Quota exceeded for quota metric: generativelanguage.googleapis.com/"
        "generate_content_free_tier_requests, quotaId: "
        '"GenerateRequestsPerDayPerProjectPerModel-FreeTier", quotaValue: "20". '
        "Please retry in 46s."
    )
    GROQ_DAILY = (
        "Rate limit reached for model `x` on tokens per day (TPD): Limit 200000, "
        "Used 199580. Please try again in 3m36s."
    )
    PER_MINUTE = (
        'quotaId: "GenerateRequestsPerMinutePerProjectPerModel-FreeTier", '
        'quotaValue: "5". Please retry in 35.9s.'
    )

    @pytest.mark.parametrize("detail", [GEMINI_DAILY, GROQ_DAILY])
    def test_a_daily_bucket_ignores_the_stated_window(self, detail: str) -> None:
        slug = model_registry.TOOL_MODEL_CHAIN[0]

        applied = model_registry.note_rate_limit(slug, detail)

        assert applied == model_registry.DAILY_QUOTA_BENCH_SECONDS
        assert slug not in model_registry.active_chain(TOOL)

    def test_a_per_minute_bucket_still_honours_it(self) -> None:
        """The fix must not swallow the ordinary case into a half-hour bench."""
        slug = model_registry.TOOL_MODEL_CHAIN[0]

        applied = model_registry.note_rate_limit(slug, self.PER_MINUTE)

        assert applied == 35.9

    def test_the_two_are_told_apart_by_the_text_alone(self) -> None:
        assert model_registry.names_daily_quota(self.GEMINI_DAILY)
        assert model_registry.names_daily_quota(self.GROQ_DAILY)
        assert not model_registry.names_daily_quota(self.PER_MINUTE)


class TestRotIsReportedAndNotJustLogged:
    """Sentry cannot see any of these events unless something says so explicitly.

    Logging here is structlog over `PrintLoggerFactory`, which writes to stdout
    without passing through stdlib `logging` -- so Sentry's LoggingIntegration
    never sees a line of it. And the auto-integrations only capture what
    *raises* through a request, while chain rot does not even fail: the chain
    falls through and answers correctly from further down. A `logger.warning`
    is therefore not a report, and these assertions are what stop one being
    mistaken for one.
    """

    def test_benching_a_withdrawn_model_is_reported(self) -> None:
        withdrawn = model_registry.TOOL_MODEL_CHAIN[0]

        with patch.object(model_registry, "report_model_health") as reported:
            model_registry.note_failure(
                RuntimeError(f"{withdrawn.split('/', 1)[1]}: No endpoints found")
            )

        reported.assert_called_once()
        assert reported.call_args.args[0] == "models_benched"
        assert withdrawn in reported.call_args.kwargs["models"]

    def test_an_error_that_benches_nothing_reports_nothing(self) -> None:
        with patch.object(model_registry, "report_model_health") as reported:
            model_registry.note_failure(RuntimeError("connection reset by peer"))

        reported.assert_not_called()

    def test_a_spent_daily_allowance_is_reported(self) -> None:
        """This slug is gone until tomorrow, which changes what the chain can
        serve for the rest of the day."""
        slug = model_registry.TOOL_MODEL_CHAIN[0]

        with patch.object(model_registry, "report_model_health") as reported:
            model_registry.note_rate_limit(
                slug, "on tokens per day (TPD): Limit 200000. Please try again in 3m36s."
            )

        reported.assert_called_once()
        assert reported.call_args.args[0] == "daily_quota_exhausted"

    def test_an_ordinary_per_minute_limit_is_not_reported(self) -> None:
        """Backpressure that clears itself inside a minute is not an incident,
        and reporting it would bury the daily case that is."""
        slug = model_registry.TOOL_MODEL_CHAIN[0]

        with patch.object(model_registry, "report_model_health") as reported:
            model_registry.note_rate_limit(slug, "Please retry in 35.9s.")

        reported.assert_not_called()

    def test_no_visitor_text_can_ride_along(self) -> None:
        """Same rule the abort reporter documents: identifiers and counts only."""
        withdrawn = model_registry.TOOL_MODEL_CHAIN[0]

        with patch.object(model_registry, "report_model_health") as reported:
            model_registry.note_failure(
                RuntimeError(f"{withdrawn.split('/', 1)[1]}: No endpoints found")
            )

        for value in reported.call_args.kwargs.values():
            assert isinstance(value, str | int)
