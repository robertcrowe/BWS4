# Built with Spec4 AI - https://spec4.ai
"""Consolidated shared_framework_services interface: generation, representation,
and storage behind one consistent set of functions, with usage-limit
tracking and cross-app request logging.

Every example app -- RAG today, others later -- calls generate_text,
represent_text, get_record, and set_record from this module rather than
reaching into services/generation.py, services/embedding.py, or
services/storage.py directly, so behavior (usage limits, logging) is
consistent regardless of which app or capability is invoked.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.db.models import (
    LanguageGenerationRequest,
    ServiceLogEntry,
    StoredRecord,
    TextRepresentation,
    UsageLimit,
)
from backend.app.services import embedding, generation, storage

logger = structlog.get_logger()

CAPABILITY_GENERATION = "generation"
CAPABILITY_REPRESENTATION = "representation"
CAPABILITY_STORAGE = "storage"
CAPABILITY_SEARCH = "search"

#: Whole planning-agent runs, capped per UTC hour.
#:
#: The one capability here that meters a *unit of work* rather than a provider
#: call, and it does not replace the per-call gates -- a planning run reserves
#: generation per model call and search per query as well. What it adds is a
#: bound on one app's share of a pool five apps draw from: a run costs up to 7
#: generation units, so without this a handful of runs could spend the whole
#: hourly generation budget and take the other four example apps dark until
#: the top of the hour.
#:
#: No migration was needed to add it. `reserve_capability` inserts a
#: `usage_limits` row the first time a capability is seen, and no migration
#: seeds that table -- 0005 creates it empty and 0007 only adds `window_start`.
CAPABILITY_PLANNING = "planning"

#: The two kinds of generation call, as recorded on
#: language_generation_requests.mode. "structured" means a schema was demanded
#: of the response and validated after it came back -- whether that schema was
#: enforced by provider-native constrained decoding or only by the prompt.
MODE_PLAIN = "plain"
MODE_STRUCTURED = "structured"

#: Capabilities that are logged but never capped.
#:
#: Representation runs on the in-process sentence-transformers model, so it
#: consumes local CPU and no third-party quota -- there is no free tier to
#: protect and nothing to run out of. It was metered once, at a cap of 50
#: against generation's 100, and because the RAG app spends a representation
#: unit on *every* question but a generation unit only on above-threshold
#: ones, the local model was mathematically guaranteed to take the whole
#: showcase dark first. A windowed cap is also the wrong instrument for the one
#: real cost (CPU on a free dyno): it bounds the window, not the burst, and it
#: disables the app until the window rolls instead of shedding load. That job
#: belongs to a rate limit.
UNMETERED_CAPABILITIES = frozenset({CAPABILITY_REPRESENTATION})

_EXCERPT_MAX_LENGTH = 1000

#: Recorded when a caller couldn't determine which chain model served a
#: request. The column is NOT NULL, so it needs *some* value -- and an honest
#: "unknown" beats naming a model that may never have run.
_UNKNOWN_MODEL = "unknown"


class ServiceUnavailableError(Exception):
    """Raised when a capability's configured usage cap has been reached.

    The shared interface raises this instead of calling the underlying
    provider, per the shared_framework_services specification's success
    criterion that the service degrades clearly and visibly near usage
    limits.
    """

    def __init__(self, capability: str) -> None:
        self.capability = capability
        super().__init__(
            f"The '{capability}' capability has reached the showcase-wide usage "
            "limit for this hour. It resets at the top of the hour."
        )


def _default_cap(capability: str) -> int:
    """Look up the configured hourly cap for a metered capability.

    Args:
        capability: One of CAPABILITY_GENERATION, CAPABILITY_STORAGE,
            CAPABILITY_SEARCH, or CAPABILITY_PLANNING. The first three guard a
            real external quota; the last bounds one app's share of the first.

    Returns:
        The configured free-tier default cap for that capability.

    Raises:
        ValueError: If the capability is unmetered or unknown. Explicit
            rather than a bare KeyError, so an attempt to re-cap a local
            capability fails with the reason instead of a lookup trace.
    """
    settings = get_settings()
    caps = {
        CAPABILITY_GENERATION: settings.generation_hourly_limit,
        CAPABILITY_STORAGE: settings.storage_hourly_limit,
        CAPABILITY_SEARCH: settings.search_hourly_limit,
        CAPABILITY_PLANNING: settings.planning_hourly_limit,
    }
    if capability in UNMETERED_CAPABILITIES:
        raise ValueError(
            f"'{capability}' is deliberately unmetered -- it consumes no third-party "
            "quota. See UNMETERED_CAPABILITIES for why capping it is the wrong tool."
        )
    if capability not in caps:
        raise ValueError(f"'{capability}' is not a known metered capability")
    return caps[capability]


def utc_window() -> datetime:
    """Return the start of the current UTC hour.

    The one place the window boundary is computed. Every metered capability on
    both model lanes -- LiteLLM via `services/generation.py` and PydanticAI via
    `services/agent_runtime.py` -- reaches the gate through
    `reserve_capability`, which calls this; there is deliberately no second
    implementation for any app to drift from.

    UTC rather than server-local, so the reset happens at the same instant
    regardless of where the service is deployed. Hourly since v5 (migration
    0009): a filled allowance recovers at the top of the hour instead of
    holding the showcase dark until midnight.

    Returns:
        The current UTC hour, with minutes and finer truncated.
    """
    return datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)


async def reserve_capability(
    session: AsyncSession, capability: str, *, app_name: str, units: int = 1
) -> None:
    """Check a capability's hourly usage_limits row and increment it, or reject.

    The cap is a per-UTC-hour budget. When the stored `window_start` predates
    the current hour the counter is rolled over to zero before the cap is
    checked, so a capability that filled up an hour ago serves again at the top
    of the next one without operator intervention.

    Google-style docstring per project convention.

    Args:
        session: An async SQLAlchemy session to read/write usage_limits through.
        capability: The capability being invoked.
        app_name: The name of the app making the request (unused for the
            check itself, kept for symmetry with the other shared functions
            and future per-app quota breakdowns).
        units: How many units this one reservation spends. Defaults to 1, which
            is what every single-call app wants and leaves the existing callers
            unchanged -- `used >= cap` and `used + 1 > cap` are the same test.
            A caller that will make N provider calls passes N so the check and
            the increment happen **once**, before any of them run: the
            chained-calls app must not start a two-call chain it cannot
            finish, and reserving twice in a row would leave a gap where the
            first unit is committed and the second is refused.

    Raises:
        ServiceUnavailableError: If the capability's usage counter has
            already reached its configured cap *for this hour*, or if `units`
            would take it past the cap.
    """
    del app_name  # not yet used to partition usage, kept for interface symmetry
    window = utc_window()

    result = await session.execute(select(UsageLimit).where(UsageLimit.capability == capability))
    limit = result.scalar_one_or_none()
    if limit is None:
        limit = UsageLimit(
            capability=capability, used=0, cap=_default_cap(capability), window_start=window
        )
        session.add(limit)
    elif limit.window_start is None:
        # Defensive only: the column is NOT NULL in the database, so a missing
        # window means an in-memory row. Adopt this hour WITHOUT zeroing the
        # counter -- for a spend limit, an unknown window must fail closed. The
        # opposite reading would let a null silently disable the cap entirely.
        limit.window_start = window
    elif limit.window_start < window:
        # A new hour: the previous one's total says nothing about this budget.
        limit.used = 0
        limit.window_start = window

    if limit.used + units > limit.cap:
        raise ServiceUnavailableError(capability)

    limit.used += units
    await session.commit()


async def release_capability(
    session: AsyncSession, capability: str, *, app_name: str, units: int
) -> int:
    """Give back units a caller reserved up front and did not spend.

    **The partial-release path this project has wanted since v5.** Apps that
    reserve a whole run's worst case before the first call -- orchestrated,
    collaboration, and now the ReAct loop -- otherwise charge the shared hourly
    gate the ceiling for every run, including the common case of a run that
    answers early. `allowance_holds.refund` releases the *promise*; this
    releases the *spend*, and without it the two disagree.

    Floors at zero and never raises. It is called from teardown paths, where an
    exception would turn "the run finished and gave budget back" into a second
    failure on top of whatever ended the run.

    Args:
        session: An async SQLAlchemy session.
        capability: The capability to credit back.
        app_name: The app releasing the units, for symmetry with the rest of
            this module.
        units: How many to return. Zero or negative is a no-op.

    Returns:
        How many units were actually returned, which is less than `units` only
        when the window rolled over underneath the run -- in which case the
        reservation belonged to an hour that has already been zeroed and there
        is nothing to give back.
    """
    del app_name  # not yet used to partition usage, kept for interface symmetry
    if units <= 0:
        return 0

    window = utc_window()
    result = await session.execute(select(UsageLimit).where(UsageLimit.capability == capability))
    limit = result.scalar_one_or_none()
    if limit is None:
        return 0

    if limit.window_start is not None and limit.window_start < window:
        # The hour turned over while the run was in flight. The counter this
        # reservation belonged to has already been zeroed, so crediting it back
        # now would hand the new hour free budget the old one paid for.
        return 0

    returned = min(units, limit.used)
    limit.used -= returned
    await session.commit()

    logger.info(
        "capability_released", capability=capability, units=returned, requested=units
    )
    return returned


async def log_invocation(
    session: AsyncSession, *, app_name: str, capability: str, summary: str
) -> None:
    """Record one cross-app ServiceLogEntry row in the shared request log.

    Args:
        session: An async SQLAlchemy session to write through.
        app_name: The name of the app that made the request.
        capability: The capability invoked.
        summary: A short human-readable description of what happened.
    """
    session.add(ServiceLogEntry(app_name=app_name, capability=capability, summary=summary))
    await session.commit()


async def record_generation_request(
    session: AsyncSession,
    *,
    app_name: str,
    prompt_excerpt: str,
    response_excerpt: str,
    model_name: str,
    mode: str,
) -> None:
    """Record a language_generation_requests row for a successful generation call.

    Args:
        session: An async SQLAlchemy session to write through.
        app_name: The name of the app that made the request.
        prompt_excerpt: The prompt sent to the model (truncated for storage).
        response_excerpt: The model's response (truncated for storage).
        model_name: The model that actually served the request. Required, not
            defaulted: every caller here walks a fallback chain and knows what
            answered, so defaulting to the chain's first entry would log a
            model that may never have been called.
        mode: MODE_PLAIN or MODE_STRUCTURED -- whether a schema was demanded of
            the response. Required for the same reason as `model_name`: every
            caller knows which kind of call it made, and a default would
            record "plain" for schema-constrained calls, reintroducing exactly
            the ambiguity the column was added to remove.
    """
    session.add(
        LanguageGenerationRequest(
            app_name=app_name,
            prompt_excerpt=prompt_excerpt[:_EXCERPT_MAX_LENGTH],
            response_excerpt=response_excerpt[:_EXCERPT_MAX_LENGTH],
            model_name=model_name or _UNKNOWN_MODEL,
            mode=mode,
        )
    )
    await session.commit()


async def generate_text(
    session: AsyncSession, *, system_prompt: str, user_prompt: str, app_name: str
) -> str:
    """Generate text through the shared interface: enforce, call, log.

    Google-style docstring per project convention.

    Args:
        session: An async SQLAlchemy session for usage/logging bookkeeping.
        system_prompt: Instructions establishing the model's role.
        user_prompt: The request-specific prompt content.
        app_name: The name of the requesting app.

    Returns:
        The generated text.

    Raises:
        ServiceUnavailableError: If the generation capability's usage cap
            has been reached.
        GenerationServiceError: If the underlying provider call fails.
    """
    await reserve_capability(session, CAPABILITY_GENERATION, app_name=app_name)

    result = generation.generate_text(system_prompt=system_prompt, user_prompt=user_prompt)

    await record_generation_request(
        session,
        app_name=app_name,
        prompt_excerpt=user_prompt,
        response_excerpt=result.text,
        model_name=result.model,
        # This entry point takes no response_format, so it is plain by
        # construction -- not by assumption.
        mode=MODE_PLAIN,
    )
    await log_invocation(
        session,
        app_name=app_name,
        capability=CAPABILITY_GENERATION,
        summary=f"Generated text ({len(result.text)} chars) via {result.model}",
    )
    return result.text


async def represent_text(session: AsyncSession, *, text: str, app_name: str) -> list[float]:
    """Represent text through the shared interface: embed and log.

    Unlike generate_text/get_record/set_record, this reserves nothing. The
    embedding model runs in-process, so there is no third-party quota to
    protect -- see UNMETERED_CAPABILITIES. It never raises
    ServiceUnavailableError, which means callers embedding a visitor's text
    do not need a cap-exhausted branch.

    Args:
        session: An async SQLAlchemy session for logging bookkeeping.
        text: The text to represent.
        app_name: The name of the requesting app.

    Returns:
        The text's embedding vector.
    """
    vector = embedding.embed_text(text)

    session.add(
        TextRepresentation(
            source_type="shared_service_request",
            source_reference=app_name,
            model_name=get_settings().embedding_model_name,
            dimensions=len(vector),
        )
    )
    await session.commit()
    await log_invocation(
        session,
        app_name=app_name,
        capability=CAPABILITY_REPRESENTATION,
        summary=f"Represented text ({len(text)} chars)",
    )
    return vector


async def get_record(session: AsyncSession, *, key: str, app_name: str) -> StoredRecord | None:
    """Read a stored record through the shared interface: enforce, read, log.

    Args:
        session: An async SQLAlchemy session for usage/logging bookkeeping.
        key: The record's key.
        app_name: The name of the requesting app.

    Returns:
        The matching StoredRecord, or None if no record exists for that key.

    Raises:
        ServiceUnavailableError: If the storage capability's usage cap has
            been reached.
    """
    await reserve_capability(session, CAPABILITY_STORAGE, app_name=app_name)

    record = await storage.get_record(session, key)

    await log_invocation(
        session,
        app_name=app_name,
        capability=CAPABILITY_STORAGE,
        summary=f"Read stored record '{key}'" if record else f"Stored record '{key}' not found",
    )
    return record


async def set_record(session: AsyncSession, *, key: str, value: str, app_name: str) -> StoredRecord:
    """Write a stored record through the shared interface: enforce, write, log.

    Args:
        session: An async SQLAlchemy session for usage/logging bookkeeping.
        key: The record's key.
        value: The value to store.
        app_name: The name of the requesting app.

    Returns:
        The persisted StoredRecord.

    Raises:
        ServiceUnavailableError: If the storage capability's usage cap has
            been reached.
    """
    await reserve_capability(session, CAPABILITY_STORAGE, app_name=app_name)

    record = await storage.set_record(session, key=key, value=value, written_by=app_name)

    await log_invocation(
        session, app_name=app_name, capability=CAPABILITY_STORAGE, summary=f"Wrote stored record '{key}'"
    )
    return record
