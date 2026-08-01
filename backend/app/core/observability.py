# Built with Spec4 AI - https://spec4.ai
"""Optional Sentry error tracking for the API.

Error tracking is deliberately opt-in: with no ``SENTRY_DSN`` configured the
whole module is a no-op, so local development, forks, and CI run exactly as
they did before Phase 7. When a DSN *is* present, Sentry's auto-enabling
integrations cover every path the API can raise from — FastAPI/Starlette
request handling, the ``httpx`` calls the Exa search client makes, and the
outbound HTTP LiteLLM issues against OpenRouter.
"""

import sentry_sdk
import structlog

from backend.app.core.config import Settings, get_settings

logger = structlog.get_logger(__name__)

#: Fraction of requests traced for performance spans. Low by design: the API
#: runs on a free tier and the free Sentry plan has a modest event quota.
TRACES_SAMPLE_RATE = 0.1


def configure_sentry(settings: Settings | None = None) -> bool:
    """Initialize Sentry when a DSN is configured.

    Google-style docstring per project convention.

    Args:
        settings: Application settings to read ``sentry_dsn`` from. Defaults to
            the process-wide cached settings.

    Returns:
        True if Sentry was initialized, False if no DSN was configured and
        error tracking was skipped.
    """
    settings = settings or get_settings()

    if not settings.sentry_dsn:
        logger.info("sentry_disabled", reason="SENTRY_DSN not set")
        return False

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.sentry_environment,
        traces_sample_rate=TRACES_SAMPLE_RATE,
        # Questions, search queries, and generated answers can flow through
        # request bodies; keep them out of error reports.
        send_default_pii=False,
    )
    logger.info("sentry_enabled", environment=settings.sentry_environment)
    return True


def report_abort(reason: str, **context: object) -> None:
    """Report a run that ended without producing what it set out to.

    Sentry's auto-enabling integrations capture anything that *raises* through
    a request. They see nothing here, because an aborted orchestrated run is
    caught deliberately and turned into a stream event so the visitor keeps the
    partial results — which means the operator would otherwise learn about a
    100% abort rate from nowhere at all. This is the explicit report for those
    paths.

    Safe to call unconditionally: with no DSN, `sentry_sdk` was never
    initialized and `capture_message` is a no-op, so the whole path costs
    nothing and raises nothing.

    **Pass no visitor text.** The context reaches Sentry, `send_default_pii` is
    off precisely so questions and generated answers stay out of error reports,
    and a caller passing one here would defeat that.

    Args:
        reason: The abort's machine-readable outcome, used as the message.
        **context: Identifiers and counts only -- a run id, an outcome, request
            totals. Never a question, a brief, or an answer.
    """
    with sentry_sdk.new_scope() as scope:
        for key, value in context.items():
            scope.set_tag(key, value)
        sentry_sdk.capture_message(f"orchestrated_abort:{reason}", level="warning")
