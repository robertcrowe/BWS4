# Built with Spec4 AI - https://spec4.ai
"""Tests for the detector that notices a chain serving from its tail.

The condition being detected produces no error: every request succeeds, just
from further down a list ordered by preference. So the assertions that matter
are the ones about *silence* -- a detector that alerts on a healthy chain, on a
deployment running fewer providers on purpose, or twice for one fault, is worse
than none, because the operator learns to ignore it.
"""

from __future__ import annotations

from typing import Any

from collections.abc import Iterator

from unittest.mock import patch

import pytest
from structlog.testing import capture_logs

from backend.app.services import chain_health, model_registry

TOOL = model_registry.TOOL_MODEL_CHAIN
HEAD = TOOL[0]
TAIL = TOOL[-1]


@pytest.fixture(autouse=True)
def _clean() -> Iterator[None]:
    chain_health.reset()
    model_registry.reset_cooldowns()
    yield
    chain_health.reset()
    model_registry.reset_cooldowns()


def _serve(model: str, times: int = 1, chain: str = "tool") -> list[Any]:
    """Serve `times` requests and return the alerts raised for one chain.

    Scoped to a chain because both shipped chains lead with the *same* slug, so
    a single unusable head degrades both and reports for each. That is the
    intended behaviour -- two capabilities really are affected -- but it means
    an unfiltered count measures the overlap rather than the logic under test.
    """
    with capture_logs() as logs:
        for _ in range(times):
            chain_health.note_served(model)
    return [
        log
        for log in logs
        if log["event"] == "chain_head_not_serving" and log["chain"] == chain
    ]


class TestItStaysQuietWhenItShould:
    def test_a_head_that_serves_raises_nothing(self) -> None:
        assert _serve(HEAD, times=chain_health.HEAD_MISS_THRESHOLD * 3) == []

    def test_a_few_misses_are_not_rot(self) -> None:
        """An intermittent head still wins most requests.

        `groq/llama-3.3-70b-versatile` fails roughly two attempts in three and
        must not trip this; only a head that misses *every* time should.
        """
        assert _serve(TAIL, times=chain_health.HEAD_MISS_THRESHOLD - 1) == []

    def test_one_success_resets_the_run(self) -> None:
        """Consecutive, not cumulative -- otherwise every long-lived process
        eventually alerts regardless of health."""
        _serve(TAIL, times=chain_health.HEAD_MISS_THRESHOLD - 1)
        _serve(HEAD)

        assert _serve(TAIL, times=chain_health.HEAD_MISS_THRESHOLD - 1) == []

    def test_an_unconfigured_head_is_a_deployment_choice_not_a_fault(self) -> None:
        """A deployment running on fewer providers would otherwise alert forever.

        Guaranteed by the same `active_chain` check that suppresses a benched
        head, since it drops unconfigured providers too. An explicit
        `configured_providers()` guard was written alongside it and deleted: a
        mutation removing it changed no behaviour, which is the definition of
        redundant.
        """
        with patch.object(
            model_registry,
            "configured_providers",
            return_value=frozenset({"openrouter"}),
        ):
            assert _serve(TAIL, times=chain_health.HEAD_MISS_THRESHOLD * 2) == []

    def test_a_benched_head_is_not_reported_twice(self) -> None:
        """`note_failure` already reported it; this would be a second alarm for
        one fault, and the noisier of the two."""
        model_registry.note_failure(
            RuntimeError(f"{HEAD.split('/', 1)[1]}: No endpoints found")
        )

        assert _serve(TAIL, times=chain_health.HEAD_MISS_THRESHOLD * 2) == []

    def test_a_slug_from_no_watched_chain_is_ignored(self) -> None:
        """It says nothing about any head, so it is neither hit nor miss."""
        assert (
            _serve("acme/unknown-model", times=chain_health.HEAD_MISS_THRESHOLD * 2)
            == []
        )


class TestItReportsRealRot:
    def test_a_head_that_never_serves_is_reported(self) -> None:
        alerts = _serve(TAIL, times=chain_health.HEAD_MISS_THRESHOLD)

        assert len(alerts) == 1
        assert alerts[0]["head"] == HEAD
        assert alerts[0]["served_by"] == TAIL
        assert alerts[0]["position"] == len(TOOL)

    def test_it_reports_once_per_cooldown_not_once_per_request(self) -> None:
        """The condition stays true for as long as the head is unusable."""
        first = _serve(TAIL, times=chain_health.HEAD_MISS_THRESHOLD)
        again = _serve(TAIL, times=chain_health.HEAD_MISS_THRESHOLD * 3)

        assert len(first) == 1
        assert again == []

    def test_it_reaches_sentry_and_not_only_the_log(self) -> None:
        """structlog here writes to stdout without going through stdlib
        `logging`, so Sentry's LoggingIntegration never sees a line of it. A
        `logger.warning` is not a report -- the explicit call is the only route.
        """
        with patch.object(chain_health, "report_model_health") as reported:
            _serve(TAIL, times=chain_health.HEAD_MISS_THRESHOLD)

        tool_calls = [c for c in reported.call_args_list if c.kwargs["chain"] == "tool"]
        assert len(tool_calls) == 1
        assert tool_calls[0].args[0] == "chain_head_not_serving"
        assert tool_calls[0].kwargs["head"] == HEAD

    def test_the_report_carries_no_visitor_text(self) -> None:
        """Same rule the abort reporter documents: identifiers and counts only."""
        with patch.object(chain_health, "report_model_health") as reported:
            _serve(TAIL, times=chain_health.HEAD_MISS_THRESHOLD)

        for call in reported.call_args_list:
            for value in call.kwargs.values():
                assert isinstance(value, str | int)

    def test_each_chain_is_tracked_separately(self) -> None:
        """A generation slug serving must not clear the tool chain's counter."""
        generation_only = next(
            slug
            for slug in model_registry.GENERATION_MODEL_CHAIN
            if slug not in TOOL and slug != model_registry.GENERATION_MODEL_CHAIN[0]
        )
        _serve(TAIL, times=chain_health.HEAD_MISS_THRESHOLD - 1)
        _serve(generation_only)

        assert len(_serve(TAIL, times=1)) == 1


def test_two_chains_sharing_a_head_each_report_their_own_degradation() -> None:
    """One unusable slug, two affected capabilities, two alerts -- on purpose.

    Both shipped chains lead with the same model, so a single fault degrades
    tool calling and text generation alike. Collapsing that into one alert would
    save a line at the cost of the thing an operator needs first: *which*
    capability is now being served from its tail.
    """
    with capture_logs() as logs:
        for _ in range(chain_health.HEAD_MISS_THRESHOLD):
            chain_health.note_served(TAIL)

    chains = {log["chain"] for log in logs if log["event"] == "chain_head_not_serving"}

    assert chains == {"tool", "generation"}
    assert TOOL[0] == model_registry.GENERATION_MODEL_CHAIN[0]
