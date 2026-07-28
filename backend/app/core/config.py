# Built with Spec4 AI - https://spec4.ai
from functools import lru_cache
from pathlib import Path

from pydantic import ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

#: The repo root, resolved from this file rather than the process's working
#: directory: alembic runs from backend/, uvicorn and pytest run from the root,
#: and all of them must find the same single .env.
REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Application configuration loaded from environment variables/.env."""

    # A cwd-local .env is still honoured (and wins) if one exists, so a
    # per-directory override remains possible.
    model_config = SettingsConfigDict(env_file=(REPO_ROOT / ".env", ".env"), extra="ignore")

    database_url: str
    cors_origin: str
    port: int = 8000
    embedding_model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    openrouter_api_key: str
    exa_api_key: str

    #: Optional second LLM provider for the tool-use agent's model chain.
    #: Groq's free tier is metered per model (e.g. 1,000 requests/day on
    #: gpt-oss-120b) rather than as one account-wide pool like OpenRouter's
    #: 50/day, so it carries most of the traffic when configured. Unset is
    #: fine: model_registry drops every groq/ slug from the chain and the
    #: OpenRouter entries serve alone.
    groq_api_key: str | None = None

    #: Optional error tracking. Unset (the default) disables Sentry entirely
    #: rather than failing startup — see core/observability.py.
    sentry_dsn: str | None = None
    sentry_environment: str = "development"

    #: Per-capability daily usage caps for shared_framework_services, chosen
    #: to comfortably fit inside OpenRouter's/Neon's/Exa's free tiers.
    generation_daily_limit: int = 100
    embedding_daily_limit: int = 50
    storage_daily_limit: int = 300
    search_daily_limit: int = 30


@lru_cache
def get_settings() -> Settings:
    """Return the cached, validated application settings.

    Google-style docstring per project convention.

    Returns:
        The process-wide Settings instance.

    Raises:
        RuntimeError: If required configuration (e.g. DATABASE_URL) is missing
            or invalid, with a descriptive message for the operator.
    """
    try:
        return Settings()
    except ValidationError as exc:
        raise RuntimeError(
            "Invalid or missing configuration. Ensure DATABASE_URL, "
            "CORS_ORIGIN, OPENROUTER_API_KEY, and EXA_API_KEY are set via "
            f"environment variables or a .env file. Details: {exc}"
        ) from exc
