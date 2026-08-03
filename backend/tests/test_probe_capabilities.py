# Built with Spec4 AI - https://spec4.ai
"""Tests for the capability probe's classification, which decides what ships.

Nothing here calls a model. What is pinned is the judgement layer: whether a
failure disqualifies a slug, and whether a rate limit is allowed to look like
one. Both were wrong in the first version of the harness and both would have
produced a wrong chain rather than a visible error -- a harness that
misclassifies is worse than no harness, because its output looks like evidence.
"""

from __future__ import annotations

import pytest
from pydantic_ai.exceptions import FallbackExceptionGroup, ModelHTTPError

from backend.app.services.agent_runtime import AgentLaneError, StepRequestLimitExceeded
from backend.app.services.probe_capabilities import (
    TOLERABLE_FAILURES,
    ProbeResult,
    SlugReport,
    _classify_exception,
    _flatten,
)


def _wrapped(inner: Exception) -> AgentLaneError:
    """Wrap an exception the way the agent lane actually wraps provider faults.

    Args:
        inner: The provider-level exception.

    Returns:
        An AgentLaneError whose cause is a FallbackExceptionGroup, which is what
        `run_typed_step` raises.
    """
    group = FallbackExceptionGroup("All models from FallbackModel failed", [inner])
    error = AgentLaneError("probe-tool", "The probe-tool call could not be completed.")
    error.__cause__ = group
    return error


def _result(
    capability: str, ok: bool, failure: str | None, detail: str = ""
) -> ProbeResult:
    return ProbeResult(capability, "case", ok, failure, detail, 1.0)


class TestClassification:
    """A 429 must never be recorded as incapability."""

    def test_a_rate_limit_buried_two_layers_down_is_still_a_rate_limit(self) -> None:
        """The bug that would have excluded four healthy slugs.

        The agent lane wraps provider failures twice, and `str()` on the outer
        layer says only "All models from FallbackModel failed" -- so reading the
        outer frame alone classified every rate-limited slug as a plain
        `api_error`, which is the difference between "busy" and "disqualified".
        """
        error = _wrapped(
            ModelHTTPError(
                status_code=429,
                model_name="some-busy-model",
                body={"error": {"message": "You exceeded your current quota"}},
            )
        )

        assert _classify_exception(error) == "rate_limited"

    def test_a_retired_model_is_not_reported_as_an_intermittent_flake(self) -> None:
        """`unavailable` and `api_error` invite opposite decisions.

        A slug that fails intermittently with a hard error may still ship as a
        cheap bet, because the fallback absorbs it for free. A retired one fails
        every time, so listing it would just add a wasted round trip to every
        request.
        """
        error = _wrapped(
            ModelHTTPError(
                status_code=404,
                model_name="some-retired-model",
                body={
                    "error": {
                        "message": "This model is no longer available to new users."
                    }
                },
            )
        )

        assert _classify_exception(error) == "unavailable"

    def test_a_runaway_is_its_own_class(self) -> None:
        """The only failure the fallback chain cannot absorb."""
        assert (
            _classify_exception(
                StepRequestLimitExceeded("probe-tool", "used its limit")
            )
            == "runaway"
        )

    def test_an_ordinary_provider_fault_stays_tolerable(self) -> None:
        error = _wrapped(
            ModelHTTPError(
                status_code=400,
                model_name="llama-3.3-70b-versatile",
                body={"message": "Failed to call a function."},
            )
        )

        assert _classify_exception(error) == "api_error"
        assert "api_error" in TOLERABLE_FAILURES

    def test_flatten_survives_a_cyclic_cause_chain(self) -> None:
        """`__cause__` chains can loop; the walk must terminate regardless."""
        first = ValueError("first")
        second = ValueError("second")
        first.__cause__ = second
        second.__cause__ = first

        assert "first" in _flatten(first)


class TestVerdicts:
    """The line the module draws between 'ship it' and 'do not'."""

    def test_a_slug_that_only_fails_tolerably_is_still_adopted(self) -> None:
        """`groq/llama-3.3-70b-versatile` ships at 4-of-12 on exactly this rule."""
        report = SlugReport(
            "x",
            [
                _result("agent_tool", True, None),
                _result("agent_tool", False, "api_error"),
                _result("agent_tool", False, "api_error"),
            ],
        )

        assert report.verdict("agent_tool").startswith("ADOPT")

    @pytest.mark.parametrize(
        "failure", ["runaway", "empty_output", "cited_when_declining"]
    )
    def test_one_disqualifying_failure_rejects_despite_passes(
        self, failure: str
    ) -> None:
        """A majority of passes does not redeem a failure nothing can absorb."""
        report = SlugReport(
            "x",
            [
                _result("agent_tool", True, None),
                _result("agent_tool", True, None),
                _result("agent_tool", False, failure),
            ],
        )

        assert report.verdict("agent_tool").startswith("REJECT")

    def test_only_rate_limits_reads_as_inconclusive_not_rejected(self) -> None:
        """The distinction the whole pacing effort exists to preserve."""
        report = SlugReport(
            "x",
            [
                _result("generation", False, "rate_limited"),
                _result("generation", False, "rate_limited"),
            ],
        )

        assert report.verdict("generation").startswith("INCONCLUSIVE")

    def test_an_unprobed_capability_says_so_rather_than_passing(self) -> None:
        """Silence must not read as approval -- chain comments are built from this."""
        assert SlugReport("x", []).verdict("agent_tool") == "not probed"
