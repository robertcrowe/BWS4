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
