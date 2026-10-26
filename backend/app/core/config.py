# Built with Spec4 AI - https://spec4.ai
from functools import lru_cache
from pathlib import Path

from pydantic import ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: The repo root, resolved from this file rather than the process's working
#: directory: alembic runs from backend/, uvicorn and pytest run from the root,
#: and all of them must find the same single .env.
REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Application configuration loaded from environment variables/.env."""

    # A cwd-local .env is still honoured (and wins) if one exists, so a
    # per-directory override remains possible.
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", ".env"), extra="ignore"
    )

    database_url: str
    cors_origin: str
    port: int = 8000
    embedding_model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    openrouter_api_key: str
    exa_api_key: str

    #: GROQ_API_KEY and OPENAI_API_KEY are required in every environment
    #: (production, local development and tests), with no placeholders and no
    #: opt-out. An empty value counts as missing, and `get_settings` names
    #: whichever is absent. Every pytest run needs the real keys; the `-m live`
    #: smoke tests remain opt-in and deselected by default.
    #:
    #: GROQ_API_KEY: Groq's free tier is metered per model (e.g. 1,000
    #: requests/day on gpt-oss-120b) rather than as one account-wide pool like
    #: OpenRouter's (50/day unfunded, 1,000/day funded), so every chain is
    #: Groq-first and it carries most of the traffic. A deployment without it
    #: would quietly route everything through the OpenRouter tail, so it fails
    #: at startup instead.
    groq_api_key: str

    #: OPENAI_API_KEY: required, under the same contract as GROQ_API_KEY above.
    #: It is the shared moderation service's credential: the gate in front of
    #: every free-form visitor input fails closed without it, so a deployment
    #: missing it would refuse every free-text request while appearing
    #: healthy. Curated preset questions skip the gate either way.
    #:
    #: OpenAI's moderation endpoint is free of charge and does not draw on the
    #: OpenRouter allowance, which is why the safety gate costs nothing against
    #: the orchestrated run's three-call budget.
    openai_api_key: str

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
    #: minutes rather than most of a day.
    #:
    #:   generation  50/hour -> 1,200/day worst case (OpenRouter funded: 1,000/day)
    #:   storage     75/hour -> 1,800/day worst case (Neon: comfortably inside)
    #:   search      15/hour ->   360/day worst case (Exa: **the tight one**)
    #:
    #: **Generation was raised from 25 alongside the per-run budget padding, and
    #: the honest arithmetic is that 1,200/day is above a funded OpenRouter
    #: account's 1,000/day pool.** Two things make that the right trade rather
    #: than an oversight. Every chain is Groq-first, and Groq meters per model
    #: (1,000/day on `gpt-oss-120b`, 14,400 on `llama-3.1-8b-instant`), so
    #: OpenRouter is the fallback tail rather than the primary spender; and
    #: saturating all 24 hours is not a load a showcase sees. What 25 *did*
    #: guarantee was the opposite failure: the orchestrated and collaboration
    #: apps reserve their whole run ceiling up front, so padding those to 12
    #: units against a cap of 25 would have cut them from 3 runs an hour to 2 --
    #: the padding costing exactly what it was meant to buy. At 50 they get 4.
    #: This is the first dial to turn down on a tighter account.
    #:
    #: Search is the other one to watch, and it was raised for a specific
    #: reason: a planning run can now spend 4 units (2 steps x
    #: `MAX_SEARCHES_PER_STEP`) and one tool-use request up to 3, so 5/hour was
    #: less than a single planning run plus a single search. Exa's free tier is
    #: the smallest of the three, so an operator on a tighter plan should lower
    #: `SEARCH_HOURLY_LIMIT` first -- this cap is burst control, not a monthly
    #: budget, and never was: 5/hour already implied 3,600/month.
    #:
    #: There is deliberately no embedding/representation cap: that model runs
    #: in-process, so it spends local CPU and nobody's quota. See
    #: services/shared.UNMETERED_CAPABILITIES for the full reasoning.
    generation_hourly_limit: int = 50
    storage_hourly_limit: int = 75
    search_hourly_limit: int = 15

    #: Planning-agent runs per UTC hour.
    #:
    #: Not a duplicate of `generation_hourly_limit`, which this app also spends
    #: per model call: it caps this app's *share* of that shared pool. Uncapped
    #: planning could consume the whole hourly allowance and take RAG, single
    #: call, tool use and chained calls dark with it.
    #:
    #: Left at 3 while the run ceiling was padded, deliberately. Planning is the
    #: only expensive app that charges **as it goes** rather than reserving, so
    #: its ceiling of 18 is what a degrading run may spend, not what every run
    #: does: the typical run costs 6, and 3 x 6 = 18 against a cap of 50 leaves
    #: room for the other seven apps. Raising this multiplies the worst case by
    #: a number that is rarely reached, which is the wrong dial to turn.
    planning_hourly_limit: int = 3

    #: Search cycles the ReAct loop may run before it must stop.
    #:
    #: **Fixed, not visitor-settable, and there is no 3..6 clamp.** The design
    #: mock offers a cycle-budget select; that wording is superseded by the
    #: stack spec's `react_run_call_budget` decision. A run's worst case is
    #: 8 search-cycle calls + 1 final-answer call + 1 post-run hop-annotation
    #: call, and the whole worst case is what `allowance_holds` reserves before
    #: the first cycle -- so the number has to be a code invariant rather than
    #: something the request body carries, or a caller could reserve one budget
    #: and spend another.
    #:
    #: A setting rather than a module constant because it is the dial an
    #: operator on a tighter account turns first for this app: it is the
    #: gallery's most expensive example per run, and lowering it lowers both
    #: the hold and the worst-case search spend. Lowering it makes the
    #: budget-exhausted ending more common, which the app presents candidly.
    react_cycle_budget: int = 8

    #: Cosine similarity at or above which a candidate query counts as a
    #: near-duplicate of one the loop has already issued, and is refused
    #: before it reaches Exa. Consumed from Phase 2; declared here because it
    #: belongs with the budget it protects.
    #:
    #: The guard embeds candidates with the in-process shared model, so it
    #: spends local CPU and nobody's third-party quota -- which is what lets it
    #: check every candidate. 0.95 is deliberately high: refusing a *distinct*
    #: query costs the loop a hop it cannot recover, while letting one
    #: near-duplicate through costs one search out of eight.
    react_duplicate_similarity_threshold: float = 0.95

    #: Hard ceiling on the suitability check, end to end.
    #:
    #: The check is an *advisory* that must never delay Start, so this is a
    #: latency budget rather than a correctness one: past it the run proceeds
    #: with the neutral "unknown" state and nothing is blocked. Six seconds
    #: covers a chain walk past one or two benched free-tier slugs, which is the
    #: realistic slow case; longer and the visitor is waiting on a hint.
    react_suitability_timeout_seconds: float = 6.0

    #: Suitability checks one browser session may spend.
    #:
    #: The check costs a model call, and a visitor gets two runs -- so an
    #: uncapped check would let typing spend more of the shared allowance than
    #: running. Beyond this the neutral state is served with no call at all.
    react_suitability_checks_per_session: int = 5

    #: How long a verdict stays cached, keyed by the normalised question's hash.
    #:
    #: A question's structure does not change, so a long TTL is safe and is what
    #: makes re-submitting the same text free.
    react_suitability_cache_ttl_hours: int = 24

    @field_validator("groq_api_key", "openai_api_key")
    @classmethod
    def _reject_blank_credential(cls, value: str) -> str:
        """Treat an empty or whitespace-only credential as missing.

        `.env.example` ships every key as `NAME=`, so a copied-but-unfilled
        file supplies an empty string rather than nothing. Accepting it would
        be a placeholder by another name.

        Args:
            value: The raw value from the environment or .env.

        Returns:
            The value, unchanged.

        Raises:
            ValueError: If the value is blank.
        """
        if not value.strip():
            raise ValueError("is required and must not be empty")
        return value


def _env_var_names(exc: ValidationError) -> list[str]:
    """Name the environment variables behind a settings validation failure.

    Settings fields map case-insensitively onto variables of the same name, so
    the upper-cased field is exactly what the operator has to set.

    Args:
        exc: The error raised while constructing Settings.

    Returns:
        The offending variable names, in field order, without duplicates.
    """
    names = [str(error["loc"][0]).upper() for error in exc.errors() if error["loc"]]
    return list(dict.fromkeys(names))


@lru_cache
def get_settings() -> Settings:
    """Return the cached, validated application settings.

    Google-style docstring per project convention.

    Returns:
        The process-wide Settings instance.

    Raises:
        RuntimeError: If required configuration (e.g. DATABASE_URL) is missing
            or invalid, with a descriptive message for the operator. The first
            line names the specific variable(s) at fault.
    """
    try:
        # Every field comes from the environment or `.env`, which mypy cannot
        # see; pydantic-settings fills them at runtime.
        return Settings()  # type: ignore[call-arg]
    except ValidationError as exc:
        raise RuntimeError(
            "Invalid or missing configuration: "
            f"{', '.join(_env_var_names(exc))}.\n"
            "DATABASE_URL, CORS_ORIGIN, OPENROUTER_API_KEY, EXA_API_KEY, "
            "GROQ_API_KEY and OPENAI_API_KEY are all required in every "
            "environment (production, local development and tests); set them "
            "via environment variables or the repo-root .env. There is no "
            f"placeholder and no opt-out. Details: {exc}"
        ) from exc
