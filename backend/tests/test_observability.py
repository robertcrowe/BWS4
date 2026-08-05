# Built with Spec4 AI - https://spec4.ai
"""Sentry initialization must be opt-in and never break a DSN-less run."""

from typing import Any

from unittest.mock import patch

from backend.app.core.config import Settings
from backend.app.core.observability import TRACES_SAMPLE_RATE, configure_sentry


def _settings(**overrides: Any) -> Settings:
    """Build Settings with explicit values so a developer's .env can't leak in."""
    base: dict[str, Any] = {
        "database_url": "postgresql+asyncpg://test:test@localhost/test",
        "cors_origin": "http://localhost:5173",
        "openrouter_api_key": "test-openrouter-key",
        "exa_api_key": "test-exa-key",
        "sentry_dsn": None,
    }
    base.update(overrides)
    return Settings(**base)


def test_configure_sentry_noops_when_dsn_is_unset() -> None:
    with patch("backend.app.core.observability.sentry_sdk.init") as init:
        enabled = configure_sentry(_settings())

    assert enabled is False
    init.assert_not_called()


def test_configure_sentry_noops_when_dsn_is_blank() -> None:
    with patch("backend.app.core.observability.sentry_sdk.init") as init:
        enabled = configure_sentry(_settings(sentry_dsn=""))

    assert enabled is False
    init.assert_not_called()


def test_configure_sentry_initializes_when_dsn_is_set() -> None:
    dsn = "https://public@o0.ingest.sentry.io/1234567"

    with patch("backend.app.core.observability.sentry_sdk.init") as init:
        enabled = configure_sentry(
            _settings(sentry_dsn=dsn, sentry_environment="production")
        )

    assert enabled is True
    init.assert_called_once()
    kwargs = init.call_args.kwargs
    assert kwargs["dsn"] == dsn
    assert kwargs["environment"] == "production"
    assert kwargs["traces_sample_rate"] == TRACES_SAMPLE_RATE
    # Visitor questions and search queries must not be attached to events.
    assert kwargs["send_default_pii"] is False


def test_report_abort_is_a_no_op_when_sentry_is_unconfigured() -> None:
    """The abort path must cost nothing and raise nothing with no DSN set.

    `report_abort` is called from inside exception handlers on paths that
    deliberately keep a visitor's partial results — a raise from the reporter
    would turn a graceful degradation into a 500.
    """
    from backend.app.core.observability import report_abort

    # No assertion beyond "this returns": with Sentry uninitialized,
    # capture_message is a no-op by design.
    report_abort("specialists_failed", decision_id="run-1", model_calls=3)


def test_report_abort_sends_no_visitor_text() -> None:
    """`send_default_pii=False` exists so questions stay out of error reports.

    The tags are read back off the captured event rather than trusted from the
    call site, so a caller that started passing a question would be caught here
    rather than in a Sentry dashboard.
    """
    from unittest.mock import patch

    from backend.app.core import observability

    with patch("backend.app.core.observability.sentry_sdk.capture_message") as capture:
        observability.report_abort(
            "synthesis_failed", decision_id="run-1", error_type="AgentLaneError"
        )

    assert capture.call_count == 1
    message = capture.call_args[0][0]
    assert message == "run_abort:synthesis_failed"
    # The message carries an outcome, never content.
    assert "?" not in message


def test_the_abort_prefix_does_not_name_one_app_when_two_call_it() -> None:
    """It used to be `orchestrated_abort:`, and two apps call this.

    That filed collab's aborts -- leak detection among them, the most serious
    event that app can report -- under the orchestrated app's name, so they
    sorted and grouped wrong in Sentry. Each app's reasons stay distinguishable
    on their own: collab's carry a `collab_` prefix, orchestrated's are its
    `Outcome` values.
    """
    from unittest.mock import patch

    from backend.app.core import observability

    with patch("backend.app.core.observability.sentry_sdk.capture_message") as capture:
        observability.report_abort("collab_leak_detected", run_id="r1")

    assert capture.call_args[0][0] == "run_abort:collab_leak_detected"
    assert "orchestrated" not in capture.call_args[0][0]


def test_model_health_is_reported_under_its_own_prefix() -> None:
    """Chain rot is not a run abort, and grouping them together would bury the
    one inside the other -- aborts are per-run and frequent by comparison."""
    from unittest.mock import patch

    from backend.app.core import observability

    with patch("backend.app.core.observability.sentry_sdk.capture_message") as capture:
        observability.report_model_health("models_benched", models="groq/x")

    (message,) = capture.call_args[0]
    assert message == "model_health:models_benched"
    assert capture.call_args.kwargs["level"] == "warning"


def test_model_health_is_a_no_op_without_a_dsn() -> None:
    """Called from inside exception handlers and hot paths; it must never raise
    or require configuration."""
    from backend.app.core import observability

    observability.report_model_health("chain_head_not_serving", chain="tool")
