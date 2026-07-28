# Built with Spec4 AI - https://spec4.ai
import logging

import structlog


def configure_logging() -> None:
    """Configure structlog to emit structured JSON log lines.

    Google-style docstring per project convention.
    """
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
