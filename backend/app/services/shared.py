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

CAPABILITY_GENERATION = "generation"
CAPABILITY_REPRESENTATION = "representation"
CAPABILITY_STORAGE = "storage"
CAPABILITY_SEARCH = "search"

_EXCERPT_MAX_LENGTH = 1000


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
            f"The '{capability}' capability has reached its free-tier usage limit "
            "for today. It resets at 00:00 UTC."
        )


def _default_cap(capability: str) -> int:
    """Look up the configured daily cap for a capability.

    Args:
        capability: One of CAPABILITY_GENERATION, CAPABILITY_REPRESENTATION,
            CAPABILITY_STORAGE, or CAPABILITY_SEARCH.

    Returns:
        The configured free-tier default cap for that capability.
    """
    settings = get_settings()
    return {
        CAPABILITY_GENERATION: settings.generation_daily_limit,
        CAPABILITY_REPRESENTATION: settings.embedding_daily_limit,
        CAPABILITY_STORAGE: settings.storage_daily_limit,
        CAPABILITY_SEARCH: settings.search_daily_limit,
    }[capability]


def utc_today() -> date:
    """Return today's date in UTC.

    The window boundary is UTC rather than server-local so the reset happens
    at the same instant regardless of where the service is deployed.

    Returns:
        Today's UTC date.
    """
    return datetime.now(timezone.utc).date()


async def reserve_capability(session: AsyncSession, capability: str, *, app_name: str) -> None:
    """Check a capability's daily usage_limits row and increment it, or reject.

    The cap is a per-UTC-day budget. When the stored `window_start` predates
    today the counter is rolled over to zero before the cap is checked, so a
    capability that filled up yesterday serves again today without operator
    intervention.

    Google-style docstring per project convention.

    Args:
        session: An async SQLAlchemy session to read/write usage_limits through.
        capability: The capability being invoked.
        app_name: The name of the app making the request (unused for the
            check itself, kept for symmetry with the other shared functions
            and future per-app quota breakdowns).

    Raises:
        ServiceUnavailableError: If the capability's usage counter has
            already reached its configured cap *for today*.
    """
    del app_name  # not yet used to partition usage, kept for interface symmetry
    today = utc_today()

    result = await session.execute(select(UsageLimit).where(UsageLimit.capability == capability))
    limit = result.scalar_one_or_none()
    if limit is None:
        limit = UsageLimit(
            capability=capability, used=0, cap=_default_cap(capability), window_start=today
        )
        session.add(limit)
    elif limit.window_start is None:
        # Defensive only: the column is NOT NULL in the database, so a missing
        # window means an in-memory row. Adopt today's date WITHOUT zeroing the
        # counter -- for a spend limit, an unknown window must fail closed. The
        # opposite reading would let a null silently disable the cap entirely.
        limit.window_start = today
    elif limit.window_start < today:
        # A new day: yesterday's total says nothing about today's budget.
        limit.used = 0
        limit.window_start = today

    if limit.used >= limit.cap:
        raise ServiceUnavailableError(capability)

    limit.used += 1
    await session.commit()


async def log_invocation(
    session: AsyncSession, *, app_name: str, capability: str, summary: str
) -> None:
    """Record one cross-app ServiceLogEntry row for the console's request log.

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
    model_name: str | None = None,
) -> None:
    """Record a language_generation_requests row for a successful generation call.

    Args:
        session: An async SQLAlchemy session to write through.
        app_name: The name of the app that made the request.
        prompt_excerpt: The prompt sent to the model (truncated for storage).
        response_excerpt: The model's response (truncated for storage).
        model_name: The model that actually served the request. Callers that
            walk a fallback chain (e.g. the tool-use agent) know which model
            answered and should pass it; the default records the configured
            primary.
    """
    session.add(
        LanguageGenerationRequest(
            app_name=app_name,
            prompt_excerpt=prompt_excerpt[:_EXCERPT_MAX_LENGTH],
            response_excerpt=response_excerpt[:_EXCERPT_MAX_LENGTH],
            model_name=model_name or generation.PRIMARY_MODEL,
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

    text = generation.generate_text(system_prompt=system_prompt, user_prompt=user_prompt)

    await record_generation_request(
        session, app_name=app_name, prompt_excerpt=user_prompt, response_excerpt=text
    )
    await log_invocation(
        session,
        app_name=app_name,
        capability=CAPABILITY_GENERATION,
        summary=f"Generated text ({len(text)} chars)",
    )
    return text


async def represent_text(session: AsyncSession, *, text: str, app_name: str) -> list[float]:
    """Represent text through the shared interface: enforce, embed, log.

    Args:
        session: An async SQLAlchemy session for usage/logging bookkeeping.
        text: The text to represent.
        app_name: The name of the requesting app.

    Returns:
        The text's embedding vector.

    Raises:
        ServiceUnavailableError: If the representation capability's usage
            cap has been reached.
    """
    await reserve_capability(session, CAPABILITY_REPRESENTATION, app_name=app_name)

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
