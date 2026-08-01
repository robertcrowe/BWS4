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
    #: (50/day unfunded, 1,000/day funded), so it carries most of the traffic
    #: when configured. Unset is
    #: fine: model_registry drops every groq/ slug from the chain and the
    #: OpenRouter entries serve alone.
    groq_api_key: str | None = None

    #: Optional, and read before it is used: the shared moderation service that
    #: needs it arrives in the next phase. Optional rather than required
    #: because the moderation gate guards *free-form* questions only — curated
    #: preset questions are pre-vetted and skip it — so a deployment without
    #: this key must still start and serve every existing example app.
    #:
    #: OpenAI's moderation endpoint is free of charge and does not draw on the
    #: OpenRouter allowance, which is why the safety gate costs nothing against
    #: the orchestrated run's three-call budget.
    openai_api_key: str | None = None

    #: Salt for the moderation log's question hash.
    #:
    #: Optional, and its absence is not fatal -- `services/moderation.py`
    #: generates a process-stable salt and logs that it did. What is lost then
    #: is only *comparability across restarts*: the same question hashes
    #: differently after a redeploy, so "this question keeps arriving" stops
    #: being answerable. What is never lost is the property that matters, since
    #: an unsalted hash of a short question is effectively reversible by
    #: guessing -- the space of plausible questions is small enough to
    #: enumerate.
    moderation_hash_salt: str | None = None

    #: Optional error tracking. Unset (the default) disables Sentry entirely
    #: rather than failing startup — see core/observability.py.
    sentry_dsn: str | None = None
    sentry_environment: str = "development"

    #: Per-capability **hourly** usage caps for shared_framework_services.
    #:
    #: The window moved from per-UTC-day to per-UTC-hour in v5 (migration
    #: 0009), and these values were re-based at the same time rather than
    #: carried across. Leaving the old daily numbers on an hourly window would
    #: have multiplied the showcase's worst-case spend by 24 -- 100/day becomes
    #: 100/hour, or 2,400/day -- silently, and in the one direction that costs
    #: the operator money.
    #:
    #: **An hourly window necessarily raises the theoretical daily ceiling**;
    #: that is inherent to the change, not an oversight. What it buys is
    #: recovery: a visitor who arrives just after the allowance filled waits
    #: minutes rather than most of a day. The values below are chosen so the
    #: saturated-every-hour worst case still lands inside the free tiers:
    #:
    #:   generation  25/hour ->   600/day worst case (OpenRouter funded: 1,000/day)
    #:   storage     75/hour -> 1,800/day worst case (Neon: comfortably inside)
    #:   search       5/hour ->   120/day worst case (Exa: **the tight one**)
    #:
    #: Search is the one to watch. The old cap was 30/day and Exa's free tier
    #: is the smallest of the three, so an operator on a tighter Exa plan
    #: should lower `SEARCH_HOURLY_LIMIT`; note too that one tool-use request
    #: can spend up to 3 search units, so 5/hour is already only ~2 requests.
    #:
    #: There is deliberately no embedding/representation cap: that model runs
    #: in-process, so it spends local CPU and nobody's quota. See
    #: services/shared.UNMETERED_CAPABILITIES for the full reasoning.
    generation_hourly_limit: int = 25
    storage_hourly_limit: int = 75
    search_hourly_limit: int = 5

    #: Planning-agent runs per UTC hour.
    #:
    #: Not a duplicate of `generation_hourly_limit`, which this app also spends
    #: per model call: it caps this app's *share* of that shared pool. One run
    #: costs up to 7 generation units, so uncapped planning could consume the
    #: whole hourly allowance and take RAG, single call, tool use and chained
    #: calls dark with it. At 3 runs the worst case is ~21 units against 25,
    #: which is tight by design -- planning is the most expensive app here.
    planning_hourly_limit: int = 3


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
